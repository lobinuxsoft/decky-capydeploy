"""
Game log tailer for Decky plugin.
Watches log files produced by capydeploy-game-wrapper.sh and streams
entries to the Hub via the console_log_data channel (source: "game").
"""

from __future__ import annotations

import asyncio
import glob
import os
import time
from pathlib import Path
from typing import Callable, Awaitable, Optional

import decky  # type: ignore
from steam_utils import get_user_home

MAX_BATCH_SIZE = 50
POLL_INTERVAL = 0.2  # 200ms for file polling
FILE_WAIT_TIMEOUT = 30  # seconds to wait for log file to appear


class GameLogTailer:
    """Tails a game log file and sends entries as console_log_data batches."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._send_fn: Optional[Callable[[dict], Awaitable[None]]] = None
        self._current_appid: int = 0
        self._buffer: list[dict] = []

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, appid: int, send_fn: Callable[[dict], Awaitable[None]]) -> None:
        """Start tailing the most recent log file for the given appid."""
        self.stop()
        self._current_appid = appid
        self._send_fn = send_fn
        self._buffer = []
        self._task = asyncio.get_event_loop().create_task(self._run(appid))
        decky.logger.info(f"Game log tailer started for appId={appid}")

    def stop(self) -> None:
        """Stop the tailer."""
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
            decky.logger.info("Game log tailer stopped")
        self._buffer = []
        self._current_appid = 0

    async def _run(self, appid: int) -> None:
        """Main loop: find log file, tail it, flush batches."""
        log_dir = Path(get_user_home()) / ".local" / "share" / "capydeploy" / "logs"
        pattern = str(log_dir / f"game_{appid}_*.log")

        try:
            log_file = await self._wait_for_file(pattern)
            if not log_file:
                decky.logger.warning(f"No log file found for appId={appid} after {FILE_WAIT_TIMEOUT}s")
                return

            decky.logger.info(f"Tailing log file: {log_file}")
            await self._tail_file(log_file)

        except asyncio.CancelledError:
            await self._flush()
        except Exception as e:
            decky.logger.error(f"Game log tailer error: {e}")

    async def _wait_for_file(self, pattern: str) -> Optional[str]:
        """Wait for a log file matching the pattern to appear."""
        deadline = time.time() + FILE_WAIT_TIMEOUT
        last_file = self._find_latest(pattern)

        while time.time() < deadline:
            current = self._find_latest(pattern)
            if current and current != last_file:
                return current
            if current and not last_file:
                return current
            await asyncio.sleep(POLL_INTERVAL)

        # Return whatever is latest even if it existed before
        return self._find_latest(pattern)

    @staticmethod
    def _find_latest(pattern: str) -> Optional[str]:
        """Find the most recently modified file matching the glob pattern."""
        files = glob.glob(pattern)
        if not files:
            return None
        return max(files, key=os.path.getmtime)

    async def _tail_file(self, filepath: str) -> None:
        """Tail a file, reading new lines as they appear."""
        with open(filepath, "r") as f:
            while True:
                line = f.readline()
                if line:
                    self._add_entry(line.rstrip("\n"))
                    if len(self._buffer) >= MAX_BATCH_SIZE:
                        await self._flush()
                else:
                    await self._flush()
                    await asyncio.sleep(POLL_INTERVAL)

    def _add_entry(self, text: str) -> None:
        """Add a log line as a console log entry with source 'game'."""
        if not text:
            return

        # Simple heuristic for level detection
        level = "log"
        lower = text.lower()
        if "error" in lower or "fatal" in lower or "panic" in lower:
            level = "error"
        elif "warn" in lower:
            level = "warn"
        elif "debug" in lower or "trace" in lower:
            level = "debug"

        self._buffer.append({
            "timestamp": int(time.time() * 1000),
            "level": level,
            "source": "game",
            "text": text,
        })

    async def _flush(self) -> None:
        """Send buffered entries as a batch."""
        if not self._buffer or not self._send_fn:
            return

        n = min(len(self._buffer), MAX_BATCH_SIZE)
        batch = {
            "entries": self._buffer[:n],
            "dropped": 0,
        }
        self._buffer = self._buffer[n:]

        try:
            await self._send_fn(batch)
        except Exception as e:
            decky.logger.error(f"Game log send error: {e}")
