"""WebSocket server for Hub connections."""

from __future__ import annotations

import asyncio
import json
from typing import Optional, TYPE_CHECKING

import decky  # type: ignore

from handlers import auth, info, upload, game, telemetry, console_log

if TYPE_CHECKING:
    from main import Plugin

HANDLERS = {
    "get_info": info.handle_get_info,
    "get_config": info.handle_get_config,
    "get_steam_users": info.handle_get_steam_users,
    "init_upload": upload.handle_init_upload,
    "upload_chunk": upload.handle_upload_chunk,
    "complete_upload": upload.handle_complete_upload,
    "cancel_upload": upload.handle_cancel_upload,
    "list_shortcuts": game.handle_list_shortcuts,
    "delete_game": game.handle_delete_game,
    "restart_steam": game.handle_restart_steam,
    "set_console_log_filter": console_log.handle_set_console_log_filter,
    "set_console_log_enabled": console_log.handle_set_console_log_enabled,
}


class WebSocketServer:
    """WebSocket server for Hub connections."""

    def __init__(self, plugin: Plugin):
        self.plugin = plugin
        self.server = None
        self.actual_port: int = 0
        self.connected_hub: Optional[dict] = None
        self.uploads: dict = {}
        self._send_queue: Optional[asyncio.Queue] = None
        self._write_task: Optional[asyncio.Task] = None
        self._active_websocket = None
        self._pending_artwork: dict[str, dict] = {}

    async def start(self) -> bool:
        """Start the WebSocket server. Returns True on success."""
        if self.server:
            decky.logger.info("WebSocket server already running")
            return True

        try:
            import websockets
        except ImportError:
            decky.logger.error("websockets package not found")
            return False

        try:
            self.server = await websockets.serve(
                self.handle_connection, "0.0.0.0", 0,
                max_size=50 * 1024 * 1024, reuse_address=True,
            )
            self.actual_port = self.server.sockets[0].getsockname()[1]
            decky.logger.info(f"WebSocket server started on port {self.actual_port}")
            return True
        except Exception as e:
            decky.logger.error(f"Failed to start WebSocket server: {e}")
            return False

    async def close_connection(self):
        if self._active_websocket:
            try:
                await self._active_websocket.close()
            except Exception:
                pass

    async def stop(self):
        await self.close_connection()
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None
            decky.logger.info("WebSocket server stopped")

    async def _write_pump(self, websocket, send_queue: asyncio.Queue):
        try:
            while True:
                msg_data = await send_queue.get()
                if msg_data is None:  # Shutdown signal
                    break
                try:
                    await websocket.send(msg_data)
                    decky.logger.info(f"WS SENT: {msg_data[:100]}...")
                except Exception as e:
                    decky.logger.error(f"Write error: {e}")
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            decky.logger.error(f"Write pump error: {e}")

    async def handle_connection(self, websocket):
        decky.logger.info(f"New connection from {websocket.remote_address}")
        authorized = False
        hub_id = None
        self._active_websocket = websocket

        send_queue = asyncio.Queue()
        write_task = asyncio.create_task(self._write_pump(websocket, send_queue))
        self._send_queue = send_queue
        self._write_task = write_task

        try:
            async for message in websocket:
                try:
                    if isinstance(message, bytes):
                        await upload.handle_binary(self, websocket, message)
                        continue

                    msg = json.loads(message)
                    msg_type = msg.get("type")
                    msg_id = msg.get("id", "")
                    payload = msg.get("payload", {})

                    decky.logger.info(f"WS RECV [{msg_type}] id={msg_id}")

                    if msg_type == "hub_connected":
                        hub_id, authorized = await auth.handle_hub_connected(
                            self, websocket, msg_id, payload
                        )
                    elif msg_type == "pair_confirm":
                        authorized = await auth.handle_pair_confirm(
                            self, websocket, msg_id, payload, hub_id
                        )
                    elif not authorized:
                        await self.send_error(websocket, msg_id, 401, "Not authorized")
                    elif msg_type == "ping":
                        await self.send(websocket, msg_id, "pong", None)
                    else:
                        handler = HANDLERS.get(msg_type)
                        if handler:
                            await handler(self, websocket, msg_id, payload)
                        else:
                            decky.logger.warning(f"Unknown message type: {msg_type}")

                except json.JSONDecodeError:
                    decky.logger.error("Failed to parse JSON message")
                except Exception as e:
                    decky.logger.error(f"Error handling message: {e}")

        except Exception as e:
            decky.logger.error(f"Connection error: {e}")
        finally:
            self._active_websocket = None

            await send_queue.put(None)
            write_task.cancel()
            try:
                await write_task
            except asyncio.CancelledError:
                pass

            await upload.cleanup_orphaned_uploads(self)

            self._pending_artwork.clear()

            if self.connected_hub and self.connected_hub.get("id") == hub_id:
                telemetry.stop_telemetry(self)
                console_log.stop_console_log(self)
                console_log.stop_game_log(self)
                self.connected_hub = None
                try:
                    await self.plugin.notify_frontend("console_log_toggle", {"enabled": False})
                    await self.plugin.notify_frontend("hub_disconnected", {})
                except Exception as e:
                    decky.logger.error(f"Failed to notify hub_disconnected: {e}")
            decky.logger.info(f"Connection closed: {websocket.remote_address}")

    async def send(self, websocket, msg_id: str, msg_type: str, payload):
        msg = {"id": msg_id, "type": msg_type}
        if payload is not None:
            msg["payload"] = payload
        json_str = json.dumps(msg)
        decky.logger.info(f"WS QUEUE [{msg_type}] id={msg_id}")
        if self._send_queue:
            await self._send_queue.put(json_str)
        else:
            decky.logger.error("Send queue not initialized!")

    async def send_error(self, websocket, msg_id: str, code: int, message: str):
        msg = {
            "id": msg_id,
            "type": "error",
            "error": {"code": code, "message": message},
        }
        if self._send_queue:
            await self._send_queue.put(json.dumps(msg))
        else:
            decky.logger.error("Send queue not initialized!")
