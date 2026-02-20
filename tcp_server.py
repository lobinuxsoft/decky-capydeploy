"""TCP data channel server for receiving bulk file transfers.

Wire format matches crates/data-channel (Rust implementation):

  HANDSHAKE (Hub -> Agent):     [32 bytes: hex token ASCII]
  AUTH RESPONSE (Agent -> Hub): [1 byte: 0x01=OK, 0x00=rejected]

  PER FILE (Hub -> Agent):
    [2 bytes BE: path_len]
    [path_len bytes: relative_path UTF-8]
    [8 bytes BE: file_size]
    [file_size bytes: raw file data]

  END MARKER: [2 bytes: 0x0000]
"""

from __future__ import annotations

import asyncio
import os
import secrets
import struct
from typing import Callable, Optional

import decky  # type: ignore

# Constants matching crates/data-channel/src/lib.rs
TCP_BUFFER_SIZE = 256 * 1024
TCP_CONNECT_TIMEOUT = 30
TCP_AUTH_TIMEOUT = 5
TOKEN_LEN = 32

AUTH_OK = 0x01
AUTH_REJECTED = 0x00


def _validate_path(path: str) -> None:
    """Validate a relative path for safety (no traversal, no absolute paths)."""
    if not path:
        raise ValueError("empty path")

    if os.path.isabs(path):
        raise ValueError(f"absolute path not allowed: {path}")

    normalized = os.path.normpath(path)
    if normalized == ".." or normalized.startswith(".." + os.sep):
        raise ValueError(f"parent traversal not allowed: {path}")


class TcpDataServer:
    """Ephemeral TCP server for receiving file data from the Hub."""

    def __init__(self):
        self._server: Optional[asyncio.AbstractServer] = None
        self._port: int = 0
        self._token: str = ""
        self._cancel_event = asyncio.Event()
        self._conn_future: Optional[asyncio.Future] = None

    @property
    def port(self) -> int:
        return self._port

    @property
    def token(self) -> str:
        return self._token

    async def start(self) -> tuple[int, str]:
        """Bind ephemeral port and generate token. Returns (port, token)."""
        self._token = secrets.token_hex(16)  # 32 hex chars
        self._cancel_event.clear()

        loop = asyncio.get_event_loop()
        self._conn_future = loop.create_future()

        async def _on_connect(reader, writer):
            """Deliver the first connection to accept_and_receive."""
            if self._conn_future and not self._conn_future.done():
                self._conn_future.set_result((reader, writer))
            else:
                writer.close()

        server = await asyncio.start_server(_on_connect, "0.0.0.0", 0)
        self._server = server
        self._port = server.sockets[0].getsockname()[1]

        decky.logger.info(f"TCP data channel listening on port {self._port}")
        return self._port, self._token

    async def accept_and_receive(
        self,
        install_path: str,
        progress_cb: Optional[Callable[[int, str], None]] = None,
    ) -> int:
        """Accept one connection, validate token, receive files.

        Returns total bytes received.
        """
        if not self._conn_future:
            raise RuntimeError("server not started")

        try:
            reader, writer = await asyncio.wait_for(
                self._conn_future, timeout=TCP_CONNECT_TIMEOUT
            )
        except asyncio.TimeoutError:
            raise TimeoutError("TCP data channel: connect timeout")
        finally:
            # Stop accepting further connections.
            if self._server:
                self._server.close()
                self._server = None

        addr = writer.get_extra_info("peername")
        decky.logger.info(f"TCP data channel: connection from {addr}")

        try:
            return await self._handle_connection(
                reader, writer, install_path, progress_cb
            )
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        install_path: str,
        progress_cb: Optional[Callable[[int, str], None]],
    ) -> int:
        """Handle a single TCP data connection."""
        # Read and validate token.
        try:
            token_data = await asyncio.wait_for(
                reader.readexactly(TOKEN_LEN), timeout=TCP_AUTH_TIMEOUT
            )
        except asyncio.TimeoutError:
            raise TimeoutError("TCP data channel: auth timeout")

        received_token = token_data.decode("ascii")

        if not secrets.compare_digest(received_token, self._token):
            decky.logger.warning("TCP data channel: invalid token")
            writer.write(bytes([AUTH_REJECTED]))
            await writer.drain()
            raise ValueError("TCP data channel: invalid token")

        writer.write(bytes([AUTH_OK]))
        await writer.drain()
        decky.logger.info("TCP data channel: authenticated")

        # Receive files.
        total_bytes = 0
        os.makedirs(install_path, exist_ok=True)

        while True:
            if self._cancel_event.is_set():
                raise asyncio.CancelledError("TCP data channel cancelled")

            # Read path_len (2 bytes BE).
            path_len_data = await reader.readexactly(2)
            path_len = struct.unpack(">H", path_len_data)[0]

            if path_len == 0:
                # End marker.
                decky.logger.info("TCP data channel: end marker received")
                break

            # Read relative path.
            path_data = await reader.readexactly(path_len)
            relative_path = path_data.decode("utf-8")

            # Read file size (8 bytes BE).
            size_data = await reader.readexactly(8)
            file_size = struct.unpack(">Q", size_data)[0]

            # Validate path.
            _validate_path(relative_path)

            # Write file to disk.
            full_path = os.path.join(install_path, relative_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            remaining = file_size
            with open(full_path, "wb") as f:
                while remaining > 0:
                    if self._cancel_event.is_set():
                        raise asyncio.CancelledError("TCP data channel cancelled")

                    to_read = min(remaining, TCP_BUFFER_SIZE)
                    chunk = await reader.read(to_read)
                    if not chunk:
                        raise ConnectionError("unexpected EOF during file data")

                    f.write(chunk)
                    remaining -= len(chunk)
                    total_bytes += len(chunk)

                    if progress_cb:
                        progress_cb(total_bytes, relative_path)

            decky.logger.info(
                f"TCP data channel: received {relative_path} ({file_size} bytes)"
            )

        decky.logger.info(
            f"TCP data channel: transfer complete ({total_bytes} bytes total)"
        )
        return total_bytes

    async def stop(self):
        """Close listener and cancel pending accept."""
        self._cancel_event.set()
        if self._conn_future and not self._conn_future.done():
            self._conn_future.cancel()
        if self._server:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                pass
            self._server = None
        decky.logger.info("TCP data channel: stopped")
