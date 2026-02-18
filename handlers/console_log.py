"""Console log and game log handlers and lifecycle functions."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

import decky  # type: ignore

if TYPE_CHECKING:
    from ws_server import WebSocketServer


# ── Message handlers ──────────────────────────────────────────────────────

async def handle_set_console_log_filter(
    server: WebSocketServer, websocket, msg_id: str, payload: dict
) -> None:
    """Handle set_console_log_filter: update log level bitmask."""
    mask = payload.get("levelMask", 15)
    if server.plugin.console_log:
        server.plugin.console_log.set_level_mask(mask)
    decky.logger.info(f"Console log filter updated: mask=0x{mask:02x}")
    await server.send(websocket, msg_id, "set_console_log_filter", {"levelMask": mask})


async def handle_set_console_log_enabled(
    server: WebSocketServer, websocket, msg_id: str, payload: dict
) -> None:
    """Handle set_console_log_enabled: toggle console log streaming remotely."""
    enabled = payload.get("enabled", False)
    await server.plugin.set_console_log_enabled(enabled)
    decky.logger.info(f"Console log enabled (remote): {enabled}")
    await server.send(websocket, msg_id, "set_console_log_enabled", {"enabled": enabled})


# ── Console log lifecycle ─────────────────────────────────────────────────

def start_console_log(server: WebSocketServer) -> None:
    """Start sending console log data to the connected Hub."""
    if not server.connected_hub or not server.plugin.console_log:
        return
    server.plugin.console_log.start(_make_console_callback(server))
    decky.logger.info("Console log streaming started")


def stop_console_log(server: WebSocketServer) -> None:
    """Stop sending console log data."""
    if server.plugin.console_log:
        server.plugin.console_log.stop()


def _make_console_callback(server: WebSocketServer):
    """Create a console log data callback bound to the server."""
    async def _send_console_log_data(batch: dict) -> None:
        if not server.connected_hub or not server._send_queue:
            return
        msg = {
            "id": str(uuid.uuid4()),
            "type": "console_log_data",
            "payload": batch,
        }
        await server._send_queue.put(json.dumps(msg))
    return _send_console_log_data


async def send_console_log_status(server: WebSocketServer) -> None:
    """Notify the Hub about console log enabled/disabled changes."""
    if not server.connected_hub or not server._send_queue:
        return
    level_mask = 15  # default
    if server.plugin.console_log:
        level_mask = server.plugin.console_log.level_mask
    msg = {
        "id": str(uuid.uuid4()),
        "type": "console_log_status",
        "payload": {
            "enabled": server.plugin.settings.getSetting("console_log_enabled", False),
            "levelMask": level_mask,
        },
    }
    await server._send_queue.put(json.dumps(msg))


# ── Game log lifecycle ────────────────────────────────────────────────────

def start_game_log(server: WebSocketServer, app_id: int) -> None:
    """Start tailing game log for the given appId."""
    if not server.connected_hub or not server.plugin.game_log_tailer:
        return
    server.plugin.game_log_tailer.start(app_id, _make_game_log_callback(server))
    decky.logger.info(f"Game log tailing started for appId={app_id}")


def stop_game_log(server: WebSocketServer) -> None:
    """Stop tailing game log."""
    if server.plugin.game_log_tailer:
        server.plugin.game_log_tailer.stop()


def _make_game_log_callback(server: WebSocketServer):
    """Create a game log data callback bound to the server — reuses console_log_data channel."""
    async def _send_game_log_data(batch: dict) -> None:
        if not server.connected_hub or not server._send_queue:
            return
        msg = {
            "id": str(uuid.uuid4()),
            "type": "console_log_data",
            "payload": batch,
        }
        await server._send_queue.put(json.dumps(msg))
    return _send_game_log_data
