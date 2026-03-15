"""TCP file transfer handlers: fs_download, fs_upload."""

from __future__ import annotations

import asyncio
import hashlib
import os
import secrets
import struct
from pathlib import Path
from typing import TYPE_CHECKING

import decky  # type: ignore

from .sandbox import validate_path

if TYPE_CHECKING:
    from ws_server import WebSocketServer

TCP_BUFFER_SIZE = 256 * 1024
TCP_AUTH_TIMEOUT = 5
TCP_CONNECT_TIMEOUT = 30
DRAIN_THRESHOLD = 4 * 1024 * 1024  # Drain every ~4MB for throughput.


# ---------------------------------------------------------------------------
# WS handlers
# ---------------------------------------------------------------------------


async def handle_fs_download(
    server: WebSocketServer, websocket, msg_id: str, payload: dict
) -> None:
    raw_path = payload.get("path", "")
    if not raw_path:
        await server.send_error(websocket, msg_id, 400, "path is required")
        return

    try:
        canonical = validate_path(raw_path)
    except ValueError as e:
        await server.send_error(websocket, msg_id, 400, str(e))
        return

    if canonical.is_dir():
        await server.send_error(websocket, msg_id, 400, "cannot download a directory")
        return

    try:
        size = canonical.stat().st_size
        tcp_port, tcp_token = await _start_tcp_download_server(canonical, canonical.name)
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


async def handle_fs_upload(
    server: WebSocketServer, websocket, msg_id: str, payload: dict
) -> None:
    dest_dir = payload.get("path", "")
    name = payload.get("name", "")

    if not dest_dir or not name:
        await server.send_error(websocket, msg_id, 400, "path and name are required")
        return

    try:
        canonical_dir = validate_path(dest_dir)
    except ValueError as e:
        await server.send_error(websocket, msg_id, 400, str(e))
        return

    if not canonical_dir.is_dir():
        await server.send_error(websocket, msg_id, 400, f"not a directory: {canonical_dir}")
        return

    try:
        tcp_port, tcp_token = await _start_tcp_upload_server(canonical_dir)
        await server.send(websocket, msg_id, "fs_upload_ready", {
            "tcpPort": tcp_port,
            "tcpToken": tcp_token,
        })
    except Exception as e:
        decky.logger.error(f"fs_upload failed: {e}")
        await server.send_error(websocket, msg_id, 500, str(e))


# ---------------------------------------------------------------------------
# TCP download server (agent sends files to hub)
# ---------------------------------------------------------------------------


async def _start_tcp_download_server(
    file_path: Path, relative_path: str,
) -> tuple[int, str]:
    token = secrets.token_hex(16)
    tcp_server = await asyncio.start_server(
        lambda r, w: _handle_download_client(r, w, token, file_path, relative_path),
        "0.0.0.0", 0,
    )
    port = tcp_server.sockets[0].getsockname()[1]
    decky.logger.info(f"TCP download server listening on port {port}")

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
    try:
        token_bytes = await asyncio.wait_for(
            reader.readexactly(32), timeout=TCP_AUTH_TIMEOUT,
        )
        received_token = token_bytes.decode("ascii")

        if not secrets.compare_digest(received_token, expected_token):
            writer.write(bytes([0x00]))
            await writer.drain()
            decky.logger.warning("TCP download: invalid token")
            return

        writer.write(bytes([0x01]))
        await writer.drain()
        decky.logger.info("TCP download: authenticated, sending file")

        path_bytes = relative_path.encode("utf-8")
        file_size = file_path.stat().st_size
        writer.write(struct.pack(">H", len(path_bytes)))
        writer.write(path_bytes)
        writer.write(struct.pack(">Q", file_size))

        hasher = hashlib.md5()
        bytes_since_drain = 0
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(TCP_BUFFER_SIZE)
                if not chunk:
                    break
                hasher.update(chunk)
                writer.write(chunk)
                bytes_since_drain += len(chunk)
                if bytes_since_drain >= DRAIN_THRESHOLD:
                    await writer.drain()
                    bytes_since_drain = 0
        await writer.drain()

        writer.write(hasher.digest())
        writer.write(struct.pack(">H", 0))
        await writer.drain()

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


# ---------------------------------------------------------------------------
# TCP upload server (agent receives files from hub)
# ---------------------------------------------------------------------------


async def _start_tcp_upload_server(dest_dir: Path) -> tuple[int, str]:
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
    try:
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
            path_len_bytes = await reader.readexactly(2)
            path_len = struct.unpack(">H", path_len_bytes)[0]
            if path_len == 0:
                break

            path_bytes = await reader.readexactly(path_len)
            rel_path = path_bytes.decode("utf-8")

            size_bytes = await reader.readexactly(8)
            file_size = struct.unpack(">Q", size_bytes)[0]

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

            expected_md5 = await reader.readexactly(16)
            actual_md5 = hasher.digest()
            if expected_md5 != actual_md5:
                decky.logger.error(f"TCP upload: checksum mismatch for {rel_path}")
                return

            decky.logger.info(f"TCP upload: received {rel_path} ({file_size} bytes)")

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
