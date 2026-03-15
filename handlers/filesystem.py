"""Filesystem browsing handler."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import secrets
import shutil
import stat
import struct
from pathlib import Path
from typing import TYPE_CHECKING

import decky  # type: ignore

if TYPE_CHECKING:
    from ws_server import WebSocketServer

# Limits — must match crates/protocol/src/constants.rs
FS_MAX_LIST_ENTRIES = 10_000
FS_MAX_TRANSFER_SIZE = 25 * 1024 * 1024  # 25 MiB — larger files use TCP

# Sandbox: allowed root directories.
_ALLOWED_ROOTS: list[Path] | None = None


def _get_allowed_roots() -> list[Path]:
    global _ALLOWED_ROOTS
    if _ALLOWED_ROOTS is not None:
        return _ALLOWED_ROOTS

    roots: list[Path] = []
    # Use abspath (not resolve) to avoid symlink issues on immutable distros
    # where /home -> /var/home.
    home = Path.home()
    if home.exists():
        roots.append(Path(os.path.abspath(home)))

    media = Path("/run/media")
    if media.exists():
        roots.append(Path(os.path.abspath(media)))

    _ALLOWED_ROOTS = roots
    return roots


def _validate_path(raw: str) -> Path:
    """Resolve and validate a path against the sandbox.

    Uses strict=False to avoid following symlinks for validation —
    this prevents rejecting files inside allowed roots that happen
    to be symlinks pointing outside (e.g. ~/.config/foo -> /usr/bin/foo).
    """
    if raw == "~" or raw.startswith("~/"):
        p = Path.home() / raw[2:] if raw.startswith("~/") else Path.home()
    else:
        p = Path(raw)

    # Resolve parent components (../) without following final symlinks.
    # Use the absolute path for sandbox check, not the symlink target.
    absolute = Path(os.path.abspath(p))
    for root in _get_allowed_roots():
        try:
            absolute.relative_to(root)
            return absolute
        except ValueError:
            continue

    raise ValueError(f"access denied: {absolute} is outside allowed roots")


def _validate_new_path(raw: str) -> Path:
    """Validate a path whose target may not exist yet (parent must be in sandbox)."""
    if raw == "~" or raw.startswith("~/"):
        p = Path.home() / raw[2:] if raw.startswith("~/") else Path.home()
    else:
        p = Path(raw)

    parent = Path(os.path.abspath(p.parent))
    for root in _get_allowed_roots():
        try:
            parent.relative_to(root)
            return parent / p.name
        except ValueError:
            continue

    raise ValueError(f"access denied: {p} is outside allowed roots")


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def handle_fs_list(
    server: WebSocketServer, websocket, msg_id: str, payload: dict
) -> None:
    raw_path = payload.get("path", "")
    show_hidden = payload.get("showHidden", False)

    if not raw_path:
        await server.send_error(websocket, msg_id, 400, "path is required")
        return

    try:
        canonical = _validate_path(raw_path)
    except ValueError as e:
        await server.send_error(websocket, msg_id, 400, str(e))
        return

    if not canonical.is_dir():
        await server.send_error(websocket, msg_id, 400, f"not a directory: {canonical}")
        return

    try:
        entries = []
        truncated = False

        for entry in canonical.iterdir():
            name = entry.name
            if not show_hidden and name.startswith("."):
                continue

            try:
                st = entry.stat()
            except OSError:
                continue

            is_dir = stat.S_ISDIR(st.st_mode)
            entries.append({
                "name": name,
                "path": str(entry),
                "isDir": is_dir,
                "size": 0 if is_dir else st.st_size,
                "modTime": int(st.st_mtime),
                "isSymlink": entry.is_symlink(),
            })

            if len(entries) >= FS_MAX_LIST_ENTRIES:
                truncated = True
                break

        entries.sort(key=lambda e: (not e["isDir"], e["name"].lower()))

        await server.send(websocket, msg_id, "fs_list_response", {
            "path": raw_path,
            "entries": entries,
            "truncated": truncated,
        })

    except PermissionError:
        await server.send_error(websocket, msg_id, 400, f"permission denied: {canonical}")
    except Exception as e:
        decky.logger.error(f"fs_list failed: {e}")
        await server.send_error(websocket, msg_id, 500, str(e))


async def handle_fs_mkdir(
    server: WebSocketServer, websocket, msg_id: str, payload: dict
) -> None:
    raw_path = payload.get("path", "")
    if not raw_path:
        await server.send_error(websocket, msg_id, 400, "path is required")
        return

    try:
        target = _validate_new_path(raw_path)
    except ValueError as e:
        await server.send_error(websocket, msg_id, 400, str(e))
        return

    try:
        target.mkdir(parents=True, exist_ok=True)
        await server.send(websocket, msg_id, "operation_result", {
            "success": True, "message": "",
        })
    except Exception as e:
        decky.logger.error(f"fs_mkdir failed: {e}")
        await server.send_error(websocket, msg_id, 500, str(e))


async def handle_fs_delete(
    server: WebSocketServer, websocket, msg_id: str, payload: dict
) -> None:
    raw_path = payload.get("path", "")
    if not raw_path:
        await server.send_error(websocket, msg_id, 400, "path is required")
        return

    try:
        canonical = _validate_path(raw_path)
    except ValueError as e:
        await server.send_error(websocket, msg_id, 400, str(e))
        return

    try:
        if canonical.is_dir():
            shutil.rmtree(canonical)
        else:
            canonical.unlink()
        await server.send(websocket, msg_id, "operation_result", {
            "success": True, "message": "",
        })
    except Exception as e:
        decky.logger.error(f"fs_delete failed: {e}")
        await server.send_error(websocket, msg_id, 500, str(e))


async def handle_fs_rename(
    server: WebSocketServer, websocket, msg_id: str, payload: dict
) -> None:
    old_path = payload.get("oldPath", "")
    new_path = payload.get("newPath", "")
    if not old_path or not new_path:
        await server.send_error(websocket, msg_id, 400, "oldPath and newPath are required")
        return

    try:
        old = _validate_path(old_path)
        new = _validate_new_path(new_path)
    except ValueError as e:
        await server.send_error(websocket, msg_id, 400, str(e))
        return

    try:
        old.rename(new)
        await server.send(websocket, msg_id, "operation_result", {
            "success": True, "message": "",
        })
    except Exception as e:
        decky.logger.error(f"fs_rename failed: {e}")
        await server.send_error(websocket, msg_id, 500, str(e))


async def handle_fs_download(
    server: WebSocketServer, websocket, msg_id: str, payload: dict
) -> None:
    raw_path = payload.get("path", "")
    if not raw_path:
        await server.send_error(websocket, msg_id, 400, "path is required")
        return

    try:
        canonical = _validate_path(raw_path)
    except ValueError as e:
        await server.send_error(websocket, msg_id, 400, str(e))
        return

    if canonical.is_dir():
        await server.send_error(websocket, msg_id, 400, "cannot download a directory")
        return

    try:
        size = canonical.stat().st_size

        # Always use TCP for file data.
        tcp_port, tcp_token = await _start_tcp_download_server(
            canonical, canonical.name,
        )
        await server.send(websocket, msg_id, "fs_download_ready", {
            "path": str(canonical),
            "size": size,
            "tcpPort": tcp_port,
            "tcpToken": tcp_token,
        })

    except PermissionError:
        await server.send_error(websocket, msg_id, 400, f"permission denied: {canonical}")
    except Exception as e:
        decky.logger.error(f"fs_download failed: {e}")
        await server.send_error(websocket, msg_id, 500, str(e))


# ---------------------------------------------------------------------------
# TCP download server (agent sends files to hub)
# ---------------------------------------------------------------------------

TCP_BUFFER_SIZE = 256 * 1024
TCP_AUTH_TIMEOUT = 5
TCP_CONNECT_TIMEOUT = 30


async def _start_tcp_download_server(
    file_path: Path, relative_path: str,
) -> tuple[int, str]:
    """Start a one-shot TCP server that sends a single file to the connecting Hub.

    Returns (port, token). The server runs in the background.
    """
    token = secrets.token_hex(16)  # 32 hex chars

    tcp_server = await asyncio.start_server(
        lambda r, w: _handle_download_client(r, w, token, file_path, relative_path),
        "0.0.0.0", 0,
    )
    port = tcp_server.sockets[0].getsockname()[1]
    decky.logger.info(f"TCP download server listening on port {port}")

    # Auto-close after timeout.
    async def _auto_close():
        await asyncio.sleep(TCP_CONNECT_TIMEOUT + 60)
        tcp_server.close()

    asyncio.create_task(_auto_close())
    return port, token


async def _handle_download_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    expected_token: str,
    file_path: Path,
    relative_path: str,
) -> None:
    """Handle a single Hub connection: authenticate and send file."""
    try:
        # Read token.
        token_bytes = await asyncio.wait_for(
            reader.readexactly(32), timeout=TCP_AUTH_TIMEOUT,
        )
        received_token = token_bytes.decode("ascii")

        if not secrets.compare_digest(received_token, expected_token):
            writer.write(bytes([0x00]))  # AUTH_REJECTED
            await writer.drain()
            decky.logger.warning("TCP download: invalid token")
            return

        writer.write(bytes([0x01]))  # AUTH_OK
        await writer.drain()
        decky.logger.info("TCP download: authenticated, sending file")

        # Send file header.
        path_bytes = relative_path.encode("utf-8")
        file_size = file_path.stat().st_size
        writer.write(struct.pack(">H", len(path_bytes)))
        writer.write(path_bytes)
        writer.write(struct.pack(">Q", file_size))

        # Stream file data with MD5.
        # Drain every ~4MB instead of every 256KB for much better throughput.
        hasher = hashlib.md5()
        bytes_since_drain = 0
        drain_threshold = 4 * 1024 * 1024
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(TCP_BUFFER_SIZE)
                if not chunk:
                    break
                hasher.update(chunk)
                writer.write(chunk)
                bytes_since_drain += len(chunk)
                if bytes_since_drain >= drain_threshold:
                    await writer.drain()
                    bytes_since_drain = 0
        await writer.drain()  # Final flush.

        # Write MD5 checksum.
        writer.write(hasher.digest())

        # End marker.
        writer.write(struct.pack(">H", 0))
        await writer.drain()

        # Wait for ACK.
        ack = await asyncio.wait_for(reader.readexactly(1), timeout=30)
        if ack[0] == 0x02:
            decky.logger.info(f"TCP download: file sent ({file_size} bytes), ACK received")
        else:
            decky.logger.warning(f"TCP download: unexpected ACK byte: {ack[0]:#x}")

    except Exception as e:
        decky.logger.error(f"TCP download handler error: {e}")
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def handle_fs_upload(
    server: WebSocketServer, websocket, msg_id: str, payload: dict
) -> None:
    dest_dir = payload.get("path", "")
    name = payload.get("name", "")

    if not dest_dir or not name:
        await server.send_error(websocket, msg_id, 400, "path and name are required")
        return

    try:
        canonical_dir = _validate_path(dest_dir)
    except ValueError as e:
        await server.send_error(websocket, msg_id, 400, str(e))
        return

    if not canonical_dir.is_dir():
        await server.send_error(websocket, msg_id, 400, f"not a directory: {canonical_dir}")
        return

    try:
        # Open TCP server to receive file from Hub.
        tcp_port, tcp_token = await _start_tcp_upload_server(canonical_dir)
        await server.send(websocket, msg_id, "fs_upload_ready", {
            "tcpPort": tcp_port,
            "tcpToken": tcp_token,
        })
    except Exception as e:
        decky.logger.error(f"fs_upload failed: {e}")
        await server.send_error(websocket, msg_id, 500, str(e))


# ---------------------------------------------------------------------------
# TCP upload server (agent receives files from hub)
# ---------------------------------------------------------------------------


async def _start_tcp_upload_server(dest_dir: Path) -> tuple[int, str]:
    """Start a one-shot TCP server that receives files from the Hub.

    Returns (port, token). The server runs in the background.
    """
    token = secrets.token_hex(16)

    tcp_server = await asyncio.start_server(
        lambda r, w: _handle_upload_client(r, w, token, dest_dir),
        "0.0.0.0", 0,
    )
    port = tcp_server.sockets[0].getsockname()[1]
    decky.logger.info(f"TCP upload server listening on port {port}")

    async def _auto_close():
        await asyncio.sleep(TCP_CONNECT_TIMEOUT + 60)
        tcp_server.close()

    asyncio.create_task(_auto_close())
    return port, token


async def _handle_upload_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    expected_token: str,
    dest_dir: Path,
) -> None:
    """Handle a single Hub connection: authenticate and receive file(s)."""
    try:
        # Authenticate.
        token_bytes = await asyncio.wait_for(
            reader.readexactly(32), timeout=TCP_AUTH_TIMEOUT,
        )
        received_token = token_bytes.decode("ascii")

        if not secrets.compare_digest(received_token, expected_token):
            writer.write(bytes([0x00]))
            await writer.drain()
            decky.logger.warning("TCP upload: invalid token")
            return

        writer.write(bytes([0x01]))
        await writer.drain()
        decky.logger.info("TCP upload: authenticated, receiving files")

        total_bytes = 0

        while True:
            # Read file header.
            path_len_bytes = await reader.readexactly(2)
            path_len = struct.unpack(">H", path_len_bytes)[0]
            if path_len == 0:
                break  # End marker.

            path_bytes = await reader.readexactly(path_len)
            rel_path = path_bytes.decode("utf-8")

            size_bytes = await reader.readexactly(8)
            file_size = struct.unpack(">Q", size_bytes)[0]

            # Write file.
            file_path = dest_dir / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)

            hasher = hashlib.md5()
            remaining = file_size

            with open(file_path, "wb") as f:
                while remaining > 0:
                    to_read = min(remaining, TCP_BUFFER_SIZE)
                    chunk = await reader.readexactly(to_read)
                    hasher.update(chunk)
                    f.write(chunk)
                    remaining -= len(chunk)
                    total_bytes += len(chunk)
                f.flush()
                os.fsync(f.fileno())

            # Verify MD5.
            expected_md5 = await reader.readexactly(16)
            actual_md5 = hasher.digest()
            if expected_md5 != actual_md5:
                decky.logger.error(
                    f"TCP upload: checksum mismatch for {rel_path}"
                )
                return

            decky.logger.info(f"TCP upload: received {rel_path} ({file_size} bytes)")

        # Send ACK.
        writer.write(bytes([0x02]))
        await writer.drain()
        decky.logger.info(f"TCP upload: complete ({total_bytes} bytes)")

    except Exception as e:
        decky.logger.error(f"TCP upload handler error: {e}")
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
