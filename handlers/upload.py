"""Upload, binary transfer, and artwork handlers."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import random
import time
from typing import TYPE_CHECKING

import decky  # type: ignore

from artwork import download_artwork, apply_from_data
from steam_utils import expand_path
from tcp_server import TcpDataServer
from upload import UploadSession

if TYPE_CHECKING:
    from ws_server import WebSocketServer

CHUNK_SIZE = 1024 * 1024  # 1MB


def _validate_safe_path(file_path: str) -> None:
    """Validate that a relative path does not escape its base directory.

    Raises ValueError on absolute paths, parent traversal (..), or empty paths.
    """
    if not file_path:
        raise ValueError("empty path")

    if os.path.isabs(file_path):
        raise ValueError(f"absolute path not allowed: {file_path}")

    normalized = os.path.normpath(file_path)

    if normalized == ".." or normalized.startswith(".." + os.sep):
        raise ValueError(f"parent directory traversal not allowed: {file_path}")


async def handle_init_upload(
    server: WebSocketServer, websocket, msg_id: str, payload: dict
) -> None:
    """Initialize an upload session."""
    config = payload.get("config", {})
    game_name = config.get("gameName", "Unknown")
    total_size = payload.get("totalSize", 0)
    files = payload.get("files", [])

    try:
        _validate_safe_path(game_name)
    except ValueError as e:
        await server.send_error(websocket, msg_id, 400, f"invalid game name: {e}")
        return

    upload_id = f"upload-{int(time.time())}-{random.randint(1000, 9999)}"
    session = UploadSession(upload_id, game_name, total_size, files)
    expanded = expand_path(server.plugin.install_path)
    session.install_path = os.path.join(expanded, game_name)
    session.executable = config.get("executable", "")
    server.uploads[upload_id] = session

    os.makedirs(session.install_path, exist_ok=True)

    decky.logger.info(f"Upload started: {game_name} ({total_size} bytes) -> {session.install_path}")
    await server.plugin.notify_frontend("operation_event", {
        "type": "install",
        "status": "start",
        "gameName": game_name,
        "progress": 0,
    })

    # Start TCP data channel *before* sending the response so the Hub
    # receives tcpPort/tcpToken in the InitUploadResponse itself.
    tcp = TcpDataServer()
    session.tcp_server = tcp
    tcp_port = None
    tcp_token = None
    try:
        tcp_port, tcp_token = await tcp.start()
    except Exception as e:
        decky.logger.warning(f"Failed to start TCP data channel: {e}")
        session.tcp_server = None

    resp_payload = {
        "uploadId": upload_id,
        "chunkSize": CHUNK_SIZE,
    }
    if tcp_port is not None and tcp_token is not None:
        resp_payload["tcpPort"] = tcp_port
        resp_payload["tcpToken"] = tcp_token

    await server.send(websocket, msg_id, "upload_init_response", resp_payload)

    if tcp_port is not None and tcp_token is not None:
        # Spawn background task to receive files via TCP.
        async def _tcp_receive():
            try:
                last_pct = 0.0
                last_time = time.monotonic()

                def _progress_cb(total_bytes: int, current_file: str):
                    nonlocal last_pct, last_time
                    session.transferred = total_bytes
                    session.current_file = current_file
                    pct = session.progress()
                    now = time.monotonic()
                    # Throttle progress: >= 2% change or >= 500ms.
                    if pct >= 100.0 or (pct - last_pct) >= 2.0 or (now - last_time) >= 0.5:
                        last_pct = pct
                        last_time = now
                        asyncio.get_event_loop().call_soon_threadsafe(
                            lambda: asyncio.ensure_future(
                                server.plugin.notify_frontend("upload_progress", {
                                    "uploadId": upload_id,
                                    "transferredBytes": total_bytes,
                                    "totalBytes": session.total_size,
                                    "currentFile": current_file,
                                    "percentage": pct,
                                })
                            )
                        )

                total = await tcp.accept_and_receive(
                    session.install_path, _progress_cb
                )
                decky.logger.info(
                    f"TCP data channel complete for {upload_id}: {total} bytes"
                )
            except Exception as e:
                decky.logger.warning(
                    f"TCP data channel failed for {upload_id}: {e}"
                )

        asyncio.create_task(_tcp_receive())


async def _write_chunk(
    server: WebSocketServer, websocket, msg_id: str,
    upload_id: str, file_path: str, offset: int, chunk_data: bytes
) -> None:
    """Write a chunk to disk and emit progress. Shared by JSON and binary paths."""
    session = server.uploads.get(upload_id)
    if not session:
        await server.send_error(websocket, msg_id, 404, "Upload not found")
        return

    try:
        _validate_safe_path(file_path)
    except ValueError as e:
        await server.send_error(websocket, msg_id, 400, f"invalid file path: {e}")
        return

    full_path = os.path.join(session.install_path, file_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    with open(full_path, "ab" if offset > 0 else "wb") as f:
        f.seek(offset)
        f.write(chunk_data)

    session.transferred += len(chunk_data)
    session.current_file = file_path

    progress = session.progress()
    await server.plugin.notify_frontend("upload_progress", {
        "uploadId": upload_id,
        "transferredBytes": session.transferred,
        "totalBytes": session.total_size,
        "currentFile": file_path,
        "percentage": progress,
    })

    await server.send(websocket, msg_id, "upload_chunk_response", {
        "uploadId": upload_id,
        "bytesWritten": len(chunk_data),
        "totalWritten": session.transferred,
    })


async def handle_upload_chunk(
    server: WebSocketServer, websocket, msg_id: str, payload: dict
) -> None:
    """Handle a chunk upload (JSON path)."""
    upload_id = payload.get("uploadId", "")
    file_path = payload.get("filePath", "")
    offset = payload.get("offset", 0)
    data = payload.get("data", b"")

    if isinstance(data, str):
        data = base64.b64decode(data)

    await _write_chunk(server, websocket, msg_id, upload_id, file_path, offset, data)


async def handle_binary(server: WebSocketServer, websocket, data: bytes) -> None:
    """Handle binary messages. Format: [4 bytes: header len][header JSON][binary data]

    Routes based on header 'type' field:
    - "artwork_image" -> apply artwork bytes to Steam grid directory
    - default (no type / has uploadId) -> upload chunk flow
    """
    if len(data) < 4:
        decky.logger.error("Binary message too short")
        return

    header_len = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]
    if len(data) < 4 + header_len:
        decky.logger.error("Binary message header incomplete")
        return

    try:
        header = json.loads(data[4:4 + header_len].decode('utf-8'))
    except Exception as e:
        decky.logger.error(f"Invalid binary header: {e}")
        return

    binary_data = data[4 + header_len:]
    msg_type = header.get("type", "")

    if msg_type == "artwork_image":
        await _handle_binary_artwork(server, websocket, header, binary_data)
        return

    # Default: upload chunk flow
    msg_id = header.get("id", "")
    upload_id = header.get("uploadId", "")
    file_path = header.get("filePath", "")
    offset = header.get("offset", 0)

    decky.logger.info(f"Binary chunk: {upload_id}/{file_path} offset={offset} size={len(binary_data)}")
    await _write_chunk(server, websocket, msg_id, upload_id, file_path, offset, binary_data)


async def _handle_binary_artwork(
    server: WebSocketServer, websocket, header: dict, data: bytes
) -> None:
    """Handle artwork_image binary message.

    When appId=0 (pre-CompleteUpload phase): store artwork as pending
    base64 so handle_complete_upload can include it in create_shortcut.
    When appId>0: write directly to Steam grid directory.
    """
    msg_id = header.get("id", "")
    app_id = header.get("appId", 0)
    artwork_type = header.get("artworkType", "")
    content_type = header.get("contentType", "")

    decky.logger.info(
        f"Artwork image: appId={app_id} type={artwork_type} "
        f"contentType={content_type} size={len(data)}"
    )

    if app_id == 0:
        # Pre-CompleteUpload: store as pending for the frontend flow
        fmt = "png"
        if "jpeg" in content_type or "jpg" in content_type:
            fmt = "jpg"

        b64 = base64.b64encode(data).decode("ascii")
        server._pending_artwork[artwork_type] = {"data": b64, "format": fmt}
        decky.logger.info(f"Stored pending artwork: {artwork_type} ({len(data)} bytes)")
        await server.send(websocket, msg_id, "artwork_image_response", {
            "success": True,
            "artworkType": artwork_type,
        })
        return

    try:
        # Write to filesystem (fallback for Steam restart)
        apply_from_data(app_id, artwork_type, data, content_type)

        # Notify frontend to apply via SteamClient API (instant, no restart)
        fmt = "png"
        if "jpeg" in content_type or "jpg" in content_type:
            fmt = "jpg"

        b64 = base64.b64encode(data).decode("ascii")
        await server.plugin.notify_frontend("update_artwork", {
            "appId": app_id,
            "artworkType": artwork_type,
            "data": b64,
            "format": fmt,
        })

        await server.send(websocket, msg_id, "artwork_image_response", {
            "success": True,
            "artworkType": artwork_type,
        })
    except Exception as e:
        decky.logger.error(f"Failed to apply artwork: {e}")
        await server.send(websocket, msg_id, "artwork_image_response", {
            "success": False,
            "artworkType": artwork_type,
            "error": str(e),
        })


async def handle_complete_upload(
    server: WebSocketServer, websocket, msg_id: str, payload: dict
) -> None:
    """Complete an upload and create shortcut."""
    upload_id = payload.get("uploadId", "")
    create_shortcut = payload.get("createShortcut", False)
    shortcut_config = payload.get("shortcut", {})

    session = server.uploads.get(upload_id)
    if not session:
        await server.send_error(websocket, msg_id, 404, "Upload not found")
        return

    # Stop TCP data channel if active.
    if session.tcp_server:
        await session.tcp_server.stop()
        session.tcp_server = None

    session.status = "complete"
    decky.logger.info(f"Upload complete: {session.game_name}")

    result = {
        "success": True,
        "path": session.install_path,
    }

    if create_shortcut and shortcut_config:
        # Agent calculates all paths — Hub only provides the executable filename
        exe_name = os.path.basename(session.executable.replace("\\", "/"))
        exe_path = os.path.join(session.install_path, exe_name)

        if os.path.exists(exe_path):
            os.chmod(exe_path, 0o755)

        quoted_start_dir = f'"{session.install_path}"'
        shortcut_name = shortcut_config.get("name", session.game_name)

        artwork_b64 = {}
        raw_artwork = shortcut_config.get("artwork", {})
        if raw_artwork:
            artwork_b64 = await download_artwork(raw_artwork)

        # Merge pending local artwork (received via binary WS before CompleteUpload)
        if server._pending_artwork:
            decky.logger.info(
                f"Merging {len(server._pending_artwork)} pending local artwork(s)"
            )
            for art_type, art_data in server._pending_artwork.items():
                artwork_b64[art_type] = art_data
            server._pending_artwork.clear()

        # Pass icon URL directly (backend will download it after shortcut creation)
        icon_url = raw_artwork.get("icon", "")

        await server.plugin.notify_frontend("create_shortcut", {
            "name": shortcut_name,
            "exe": exe_path,
            "startDir": quoted_start_dir,
            "artwork": artwork_b64,
            "iconUrl": icon_url,
        })

        tracked = server.plugin.settings.getSetting("tracked_shortcuts", [])
        tracked.append({
            "name": shortcut_name,
            "exe": exe_path,
            "startDir": session.install_path,
            "appId": 0,
            "gameName": session.game_name,
            "installedAt": time.time(),
        })
        server.plugin.settings.setSetting("tracked_shortcuts", tracked)

    await server.plugin.notify_frontend("operation_event", {
        "type": "install",
        "status": "complete",
        "gameName": session.game_name,
        "progress": 100,
    })

    del server.uploads[upload_id]

    await server.send(websocket, msg_id, "operation_result", result)


async def handle_cancel_upload(
    server: WebSocketServer, websocket, msg_id: str, payload: dict
) -> None:
    """Cancel an active upload."""
    import shutil

    upload_id = payload.get("uploadId", "")
    session = server.uploads.get(upload_id)

    if session:
        # Stop TCP data channel if active.
        if session.tcp_server:
            await session.tcp_server.stop()
            session.tcp_server = None

        session.status = "cancelled"
        if session.install_path and os.path.exists(session.install_path):
            try:
                shutil.rmtree(session.install_path)
            except Exception as e:
                decky.logger.error(f"Failed to cleanup cancelled upload: {e}")
        del server.uploads[upload_id]
        decky.logger.info(f"Upload cancelled: {session.game_name}")

    await server.send(websocket, msg_id, "operation_result", {"success": True})


async def cleanup_orphaned_uploads(server: WebSocketServer) -> None:
    """Cleanup incomplete uploads when client disconnects unexpectedly."""
    import shutil

    orphaned = [
        uid for uid, session in server.uploads.items()
        if session.status == "active"
    ]

    for upload_id in orphaned:
        session = server.uploads.get(upload_id)
        if session:
            decky.logger.warning(f"Cleaning orphaned upload: {session.game_name}")
            # Remove partially uploaded files
            if session.install_path and os.path.exists(session.install_path):
                try:
                    shutil.rmtree(session.install_path)
                    decky.logger.info(f"Removed orphaned folder: {session.install_path}")
                except Exception as e:
                    decky.logger.error(f"Failed to cleanup orphaned upload: {e}")
            del server.uploads[upload_id]

    if orphaned:
        decky.logger.info(f"Cleaned up {len(orphaned)} orphaned upload(s)")
