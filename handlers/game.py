"""Game management handlers: list, delete, restart Steam."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import decky  # type: ignore

if TYPE_CHECKING:
    from ws_server import WebSocketServer


async def handle_list_shortcuts(
    server: WebSocketServer, websocket, msg_id: str, payload: dict
) -> None:
    """Return shortcuts from tracked data (SteamClient writes VDF lazily)."""
    tracked = server.plugin.settings.getSetting("tracked_shortcuts", [])
    shortcuts = []
    for sc in tracked:
        shortcuts.append({
            "appId": sc.get("appId", 0),
            "name": sc.get("name", ""),
            "exe": sc.get("exe", ""),
            "startDir": sc.get("startDir", ""),
            "launchOptions": "",
            "lastPlayed": 0,
        })
    await server.send(websocket, msg_id, "shortcuts_response", {"shortcuts": shortcuts})


async def handle_delete_game(
    server: WebSocketServer, websocket, msg_id: str, payload: dict
) -> None:
    """Delete a game completely (like Go agent's handleDeleteGame)."""
    import shutil

    app_id = payload.get("appId", 0)
    tracked = server.plugin.settings.getSetting("tracked_shortcuts", [])

    # Find game by appId
    game = None
    for sc in tracked:
        if sc.get("appId") == app_id:
            game = sc
            break

    if not game:
        await server.send_error(websocket, msg_id, 404, "game not found")
        return

    game_name = game.get("name", game.get("gameName", ""))

    # Notify frontend: delete start
    await server.plugin.notify_frontend("operation_event", {
        "type": "delete",
        "status": "start",
        "gameName": game_name,
        "progress": 0,
        "message": "Eliminando...",
    })

    # Delete game folder
    start_dir = game.get("startDir", "").strip('"')
    if start_dir and os.path.isdir(start_dir):
        try:
            shutil.rmtree(start_dir)
            decky.logger.info(f"Deleted game folder: {start_dir}")
        except Exception as e:
            decky.logger.error(f"Failed to delete game folder: {e}")

    # Notify frontend to remove Steam shortcut via SteamClient.Apps.RemoveShortcut
    await server.plugin.notify_frontend("remove_shortcut", {"appId": app_id})

    # Remove from tracked list
    tracked = [sc for sc in tracked if sc.get("appId") != app_id]
    server.plugin.settings.setSetting("tracked_shortcuts", tracked)

    # Notify complete
    await server.plugin.notify_frontend("operation_event", {
        "type": "delete",
        "status": "complete",
        "gameName": game_name,
        "progress": 100,
        "message": "Eliminado",
    })

    await server.send(websocket, msg_id, "operation_result", {
        "status": "deleted",
        "gameName": game_name,
        "steamRestarted": False,
    })


async def handle_restart_steam(
    server: WebSocketServer, websocket, msg_id: str, payload: dict
) -> None:
    """Gracefully shutdown Steam. In Gaming Mode the session manager restarts it automatically."""
    import subprocess

    try:
        subprocess.Popen(
            ["steam", "-shutdown"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        await server.send(websocket, msg_id, "steam_response", {
            "success": True, "message": "restarting",
        })
    except Exception as e:
        await server.send(websocket, msg_id, "steam_response", {
            "success": False, "message": str(e),
        })
