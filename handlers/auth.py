"""Authentication and pairing handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import decky  # type: ignore

from pairing import PAIRING_CODE_EXPIRY

if TYPE_CHECKING:
    from ws_server import WebSocketServer

# Protocol versioning — must match crates/protocol/src/constants.rs
PROTOCOL_VERSION = 1
PROTOCOL_MIN_SUPPORTED = 1


def _check_protocol_compatibility(peer_version: int) -> tuple[str, str]:
    """Check whether a peer's protocol version is compatible.

    Returns (status, reason) where status is one of:
    "compatible", "deprecated", "incompatible".
    """
    effective = 1 if peer_version == 0 else peer_version

    if effective < PROTOCOL_MIN_SUPPORTED:
        return (
            "incompatible",
            f"peer protocol v{effective} is below minimum supported v{PROTOCOL_MIN_SUPPORTED}",
        )

    if effective > PROTOCOL_VERSION:
        return (
            "incompatible",
            f"peer protocol v{effective} is above our current v{PROTOCOL_VERSION}",
        )

    if effective < PROTOCOL_VERSION:
        return ("deprecated", f"peer protocol v{effective} is deprecated")

    return ("compatible", "")


async def handle_hub_connected(
    server: WebSocketServer, websocket, msg_id: str, payload: dict
) -> tuple[str | None, bool]:
    """Handle hub_connected handshake. Returns (hub_id, authorized)."""
    hub_id = payload.get("hubId", "")
    hub_name = payload.get("name", "Unknown Hub")
    hub_version = payload.get("version", "")
    hub_platform = payload.get("platform", "")
    token = payload.get("token", "")
    hub_proto = payload.get("protocolVersion", 0)

    decky.logger.info(
        f"Hub connected: {hub_name} v{hub_version} ({hub_platform}, proto: v{hub_proto})"
    )

    # Reject incompatible protocol versions before any auth.
    compat_status, compat_reason = _check_protocol_compatibility(hub_proto)
    if compat_status == "incompatible":
        decky.logger.warning(f"Rejecting hub {hub_id}: {compat_reason}")
        await server.send_error(websocket, msg_id, 406, compat_reason)
        return None, False

    # Check if token is valid
    if token and hub_id and server.plugin.pairing.validate_token(hub_id, token):
        server.connected_hub = {
            "id": hub_id, "name": hub_name,
            "version": hub_version, "platform": hub_platform,
        }
        tel_enabled = server.plugin.settings.getSetting("telemetry_enabled", False)
        tel_interval = server.plugin.settings.getSetting("telemetry_interval", 2)
        cl_enabled = server.plugin.settings.getSetting("console_log_enabled", False)
        await server.send(websocket, msg_id, "agent_status", {
            "name": server.plugin.agent_name,
            "version": server.plugin.version,
            "platform": "linux",
            "acceptConnections": server.plugin.accept_connections,
            "telemetryEnabled": tel_enabled,
            "telemetryInterval": tel_interval,
            "consoleLogEnabled": cl_enabled,
            "protocolVersion": PROTOCOL_VERSION,
        })
        await server.plugin.notify_frontend("hub_connected", {
            "name": hub_name,
            "version": hub_version,
        })
        # Start telemetry if enabled
        from handlers import telemetry, console_log
        if tel_enabled:
            telemetry.start_telemetry(server, tel_interval)
        # Start console log if enabled
        if cl_enabled:
            console_log.start_console_log(server)
        return hub_id, True

    # Need pairing
    if not hub_id:
        await server.send_error(websocket, msg_id, 401, "hub_id required")
        return None, False

    code = server.plugin.pairing.generate_code(hub_id, hub_name, hub_platform)
    if code is None:
        remaining = server.plugin.pairing.lockout_remaining()
        await server.send_error(
            websocket, msg_id, 429,
            f"Pairing locked out. Try again in {remaining}s",
        )
        return hub_id, False

    await server.send(websocket, msg_id, "pairing_required", {
        "code": code,
        "expiresIn": PAIRING_CODE_EXPIRY,
    })
    await server.plugin.notify_frontend("pairing_code", {"code": code})
    return hub_id, False


async def handle_pair_confirm(
    server: WebSocketServer, websocket, msg_id: str, payload: dict, hub_id: str
) -> bool:
    """Handle pairing confirmation. Returns True if authorized."""
    code = payload.get("code", "")
    token = server.plugin.pairing.validate_code(hub_id, code)

    if token:
        server.connected_hub = {
            "id": hub_id, "name": server.plugin.pairing.pending_hub_name,
        }
        await server.send(websocket, msg_id, "pair_success", {"token": token})
        await server.plugin.notify_frontend("pairing_success", {})
        return True

    # Check if this failure triggered a lockout
    if server.plugin.pairing.is_locked_out():
        remaining = server.plugin.pairing.lockout_remaining()
        await server.send(websocket, msg_id, "pair_failed", {
            "reason": f"Too many failed attempts. Locked for {remaining}s",
        })
        await server.plugin.notify_frontend("pairing_locked", {
            "remainingSeconds": remaining,
        })
    else:
        await server.send(websocket, msg_id, "pair_failed", {"reason": "Invalid code"})
    return False
