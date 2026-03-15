"""WebSocket message handlers, split by domain."""

from . import auth, info, upload, game, telemetry, console_log, filesystem

__all__ = ["auth", "info", "upload", "game", "telemetry", "console_log", "filesystem"]
