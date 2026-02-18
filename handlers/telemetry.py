"""Telemetry lifecycle and status functions."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

import decky  # type: ignore

if TYPE_CHECKING:
    from ws_server import WebSocketServer


def start_telemetry(server: WebSocketServer, interval: float) -> None:
    """Start sending telemetry data to the connected Hub."""
    if not server.connected_hub or not server.plugin.telemetry:
        return
    server.plugin.telemetry.start(interval, _make_send_callback(server))
    decky.logger.info(f"Telemetry streaming started (interval={interval}s)")


def stop_telemetry(server: WebSocketServer) -> None:
    """Stop sending telemetry data."""
    if server.plugin.telemetry:
        server.plugin.telemetry.stop()


def _make_send_callback(server: WebSocketServer):
    """Create a telemetry data callback bound to the server."""
    async def _send_telemetry_data(data: dict) -> None:
        if not server.connected_hub or not server._send_queue:
            return
        msg = {
            "id": str(uuid.uuid4()),
            "type": "telemetry_data",
            "payload": data,
        }
        await server._send_queue.put(json.dumps(msg))
    return _send_telemetry_data


async def send_telemetry_status(server: WebSocketServer) -> None:
    """Notify the Hub about telemetry enabled/interval changes."""
    if not server.connected_hub or not server._send_queue:
        return
    msg = {
        "id": str(uuid.uuid4()),
        "type": "telemetry_status",
        "payload": {
            "enabled": server.plugin.settings.getSetting("telemetry_enabled", False),
            "interval": server.plugin.settings.getSetting("telemetry_interval", 2),
        },
    }
    await server._send_queue.put(json.dumps(msg))
