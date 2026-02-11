"""
Console log collector for Decky plugin.
Receives entries from the frontend JS hook and batches them to the Hub.
Same pattern as telemetry.py: async flush loop with buffer.
"""

from __future__ import annotations

import asyncio
import time
from typing import Callable, Awaitable, Optional

import decky  # type: ignore

MAX_BUFFER_SIZE = 200
MAX_BATCH_SIZE = 50
FLUSH_INTERVAL = 0.5  # 500ms


class ConsoleLogCollector:
    """Buffers console log entries and flushes them in batches."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._send_fn: Optional[Callable[[dict], Awaitable[None]]] = None
        self._buffer: list[dict] = []
        self._dropped: int = 0
        self._lock = asyncio.Lock()

    def start(self, send_fn: Callable[[dict], Awaitable[None]]) -> None:
        """Start the flush loop."""
        if self._task and not self._task.done():
            return
        self._send_fn = send_fn
        self._buffer = []
        self._dropped = 0
        self._task = asyncio.get_event_loop().create_task(self._loop())
        decky.logger.info("Console log collector started")

    def stop(self) -> None:
        """Stop the flush loop."""
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
            decky.logger.info("Console log collector stopped")
        self._buffer = []
        self._dropped = 0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def add_entry(self, level: str, text: str, source: str = "console",
                  url: str = "", line: int = 0,
                  segments: list | None = None) -> None:
        """Add a log entry to the buffer (called from frontend JS hook)."""
        entry = {
            "timestamp": int(time.time() * 1000),
            "level": level,
            "source": source,
            "text": text,
        }
        if url:
            entry["url"] = url
        if line:
            entry["line"] = line
        if segments:
            entry["segments"] = segments

        if len(self._buffer) >= MAX_BUFFER_SIZE:
            self._buffer.pop(0)
            self._dropped += 1
        self._buffer.append(entry)

    async def _loop(self) -> None:
        """Flush loop: sends batches at regular intervals."""
        try:
            while True:
                await asyncio.sleep(FLUSH_INTERVAL)
                await self._flush()
        except asyncio.CancelledError:
            # Final flush before exit
            await self._flush()
        except Exception as e:
            decky.logger.error(f"Console log loop error: {e}")

    async def _flush(self) -> None:
        """Send buffered entries as a batch."""
        if not self._buffer or not self._send_fn:
            return

        n = min(len(self._buffer), MAX_BATCH_SIZE)
        batch = {
            "entries": self._buffer[:n],
            "dropped": self._dropped,
        }
        self._buffer = self._buffer[n:]
        self._dropped = 0

        try:
            await self._send_fn(batch)
        except Exception as e:
            decky.logger.error(f"Console log send error: {e}")
