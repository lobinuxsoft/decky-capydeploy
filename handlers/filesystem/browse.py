"""Browse handlers: fs_list, fs_mkdir, fs_delete, fs_rename."""

from __future__ import annotations

import shutil
import stat
from typing import TYPE_CHECKING

import decky  # type: ignore

from .sandbox import FS_MAX_LIST_ENTRIES, validate_new_path, validate_path

if TYPE_CHECKING:
    from ws_server import WebSocketServer


async def handle_fs_list(
    server: WebSocketServer, websocket, msg_id: str, payload: dict
) -> None:
    raw_path = payload.get("path", "")
    show_hidden = payload.get("showHidden", False)

    if not raw_path:
        await server.send_error(websocket, msg_id, 400, "path is required")
        return

    try:
        canonical = validate_path(raw_path)
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
        target = validate_new_path(raw_path)
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
        canonical = validate_path(raw_path)
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
        old = validate_path(old_path)
        new = validate_new_path(new_path)
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
