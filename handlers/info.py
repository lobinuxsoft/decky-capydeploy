"""Info and config query handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from steam_utils import get_steam_users

if TYPE_CHECKING:
    from ws_server import WebSocketServer


async def handle_get_info(
    server: WebSocketServer, websocket, msg_id: str, payload: dict
) -> None:
    """Return agent info."""
    await server.send(websocket, msg_id, "info_response", {
        "agent": {
            "id": server.plugin.agent_id,
            "name": server.plugin.agent_name,
            "platform": "linux",
            "version": server.plugin.version,
            "acceptConnections": server.plugin.accept_connections,
        }
    })


async def handle_get_config(
    server: WebSocketServer, websocket, msg_id: str, payload: dict
) -> None:
    """Return agent config."""
    await server.send(websocket, msg_id, "config_response", {
        "installPath": server.plugin.install_path,
    })


async def handle_get_steam_users(
    server: WebSocketServer, websocket, msg_id: str, payload: dict
) -> None:
    """Return Steam users from userdata directory."""
    users = get_steam_users()
    proto_users = [{"id": u["id"]} for u in users]
    await server.send(websocket, msg_id, "steam_users_response", {"users": proto_users})
