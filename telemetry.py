"""
Hardware telemetry collector for SteamOS/Linux.
Reads sysfs/procfs directly — no external dependencies (psutil, etc.).
Produces the same JSON structure as the Desktop Agent (Go).
"""

from __future__ import annotations

import asyncio
import glob
import os
import time
from typing import Callable, Awaitable, Optional

import decky  # type: ignore


class TelemetryCollector:
    """Collects hardware metrics from sysfs/procfs at a configurable interval."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._interval: float = 2.0
        self._send_fn: Optional[Callable[[dict], Awaitable[None]]] = None

        # CPU delta state (for usage calculation)
        self._prev_idle: int = 0
        self._prev_total: int = 0
        self._primed: bool = False

        # Cached hwmon paths (resolved once, reused)
        self._cpu_temp_path: Optional[str] = None
        self._gpu_busy_path: Optional[str] = None
        self._gpu_temp_path: Optional[str] = None
        self._gpu_freq_path: Optional[str] = None
        self._gpu_mem_freq_path: Optional[str] = None
        self._vram_used_path: Optional[str] = None
        self._vram_total_path: Optional[str] = None
        self._power_cap_path: Optional[str] = None
        self._power_avg_path: Optional[str] = None
        self._fan_path: Optional[str] = None
        self._paths_resolved: bool = False

    def start(self, interval: float, send_fn: Callable[[dict], Awaitable[None]]) -> None:
        """Start the collection loop."""
        if self._task and not self._task.done():
            return
        self._interval = max(1.0, min(interval, 10.0))
        self._send_fn = send_fn
        self._primed = False
        self._prev_idle = 0
        self._prev_total = 0
        self._task = asyncio.get_event_loop().create_task(self._loop())
        decky.logger.info(f"Telemetry collector started (interval={self._interval}s)")

    def stop(self) -> None:
        """Stop the collection loop."""
        if self._task and not self._task.done():
            self._task.cancel()
            self._task = None
            decky.logger.info("Telemetry collector stopped")

    def update_interval(self, seconds: float) -> None:
        """Update interval — restarts the loop if running."""
        send_fn = self._send_fn
        if self._task and not self._task.done() and send_fn:
            self.stop()
            self.start(seconds, send_fn)

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    # ── Internal loop ────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        try:
            while True:
                data = self._collect()
                if data and self._send_fn:
                    if self._primed:
                        await self._send_fn(data)
                    else:
                        # First tick: discard (CPU delta not yet valid)
                        self._primed = True
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            decky.logger.error(f"Telemetry loop error: {e}")

    # ── Path resolution (lazy, cached) ───────────────────────────────────────

    def _resolve_paths(self) -> None:
        """Resolve hwmon paths once. SteamOS hwmon order is stable per boot."""
        if self._paths_resolved:
            return

        # CPU temperature: k10temp (AMD) or coretemp (Intel)
        for hwmon in glob.glob("/sys/class/hwmon/hwmon*"):
            name = _read_file(os.path.join(hwmon, "name")).strip()
            if name in ("k10temp", "coretemp"):
                self._cpu_temp_path = os.path.join(hwmon, "temp1_input")

            # Fan speed
            fan_path = os.path.join(hwmon, "fan1_input")
            if os.path.exists(fan_path):
                self._fan_path = fan_path

            # Power — TDP cap (optional) and draw (average or input)
            power_cap = os.path.join(hwmon, "power1_cap")
            if os.path.exists(power_cap):
                self._power_cap_path = power_cap
            avg = os.path.join(hwmon, "power1_average")
            inp = os.path.join(hwmon, "power1_input")
            if os.path.exists(avg):
                self._power_avg_path = avg
            elif os.path.exists(inp) and not self._power_avg_path:
                self._power_avg_path = inp

        # GPU paths (AMDGPU — card0 or card1)
        for card in sorted(glob.glob("/sys/class/drm/card[0-9]")):
            busy = os.path.join(card, "device", "gpu_busy_percent")
            if os.path.exists(busy):
                self._gpu_busy_path = busy
                # GPU temperature
                for hwmon in glob.glob(os.path.join(card, "device", "hwmon", "hwmon*")):
                    temp = os.path.join(hwmon, "temp1_input")
                    if os.path.exists(temp):
                        self._gpu_temp_path = temp
                        break
                # GPU core frequency
                freq = os.path.join(card, "device", "pp_dpm_sclk")
                if os.path.exists(freq):
                    self._gpu_freq_path = freq
                # GPU memory frequency
                mclk = os.path.join(card, "device", "pp_dpm_mclk")
                if os.path.exists(mclk):
                    self._gpu_mem_freq_path = mclk
                # VRAM info
                vram_total = os.path.join(card, "device", "mem_info_vram_total")
                vram_used = os.path.join(card, "device", "mem_info_vram_used")
                if os.path.exists(vram_total):
                    self._vram_total_path = vram_total
                if os.path.exists(vram_used):
                    self._vram_used_path = vram_used
                break

        self._paths_resolved = True

    # ── Collect all metrics ──────────────────────────────────────────────────

    def _collect(self) -> dict:
        """Collect all available metrics into the canonical telemetry structure."""
        self._resolve_paths()
        ts = int(time.time() * 1000)  # Unix millis

        data: dict = {"timestamp": ts}

        cpu = self._read_cpu()
        if cpu:
            data["cpu"] = cpu

        gpu = self._read_gpu()
        if gpu:
            data["gpu"] = gpu

        mem = self._read_memory()
        if mem:
            data["memory"] = mem

        bat = self._read_battery()
        if bat:
            data["battery"] = bat

        pwr = self._read_power()
        if pwr:
            data["power"] = pwr

        fan = self._read_fan()
        if fan:
            data["fan"] = fan

        return data

    # ── CPU ───────────────────────────────────────────────────────────────────

    def _read_cpu(self) -> Optional[dict]:
        result: dict = {}

        # Usage from /proc/stat (delta-based)
        try:
            line = _read_file("/proc/stat").split("\n", 1)[0]  # "cpu  user nice system idle ..."
            parts = line.split()
            if len(parts) >= 5:
                values = [int(x) for x in parts[1:]]
                idle = values[3]
                total = sum(values)

                if self._prev_total > 0:
                    d_idle = idle - self._prev_idle
                    d_total = total - self._prev_total
                    if d_total > 0:
                        usage = (1.0 - d_idle / d_total) * 100.0
                        result["usagePercent"] = round(usage, 1)

                self._prev_idle = idle
                self._prev_total = total
        except Exception:
            pass

        # Temperature
        if self._cpu_temp_path:
            val = _read_int(self._cpu_temp_path)
            if val is not None:
                result["tempCelsius"] = round(val / 1000.0, 1)

        # Frequency (average across all cores)
        try:
            freqs = []
            for path in glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq"):
                val = _read_int(path)
                if val is not None:
                    freqs.append(val)
            if freqs:
                result["freqMHz"] = round(sum(freqs) / len(freqs) / 1000.0, 0)
        except Exception:
            pass

        return result if result else None

    # ── GPU ───────────────────────────────────────────────────────────────────

    def _read_gpu(self) -> Optional[dict]:
        result: dict = {}

        # Usage
        if self._gpu_busy_path:
            val = _read_int(self._gpu_busy_path)
            if val is not None:
                result["usagePercent"] = float(val)

        # Temperature
        if self._gpu_temp_path:
            val = _read_int(self._gpu_temp_path)
            if val is not None:
                result["tempCelsius"] = round(val / 1000.0, 1)

        # Core frequency from pp_dpm_sclk (active level marked with *)
        if self._gpu_freq_path:
            freq = self._read_dpm_freq(self._gpu_freq_path)
            if freq is not None:
                result["freqMHz"] = freq

        # Memory frequency from pp_dpm_mclk
        if self._gpu_mem_freq_path:
            mclk = self._read_dpm_freq(self._gpu_mem_freq_path)
            if mclk is not None:
                result["memFreqMHz"] = mclk

        # VRAM
        if self._vram_total_path:
            vram_total = _read_int(self._vram_total_path)
            if vram_total is not None:
                result["vramTotalBytes"] = vram_total
            if self._vram_used_path:
                vram_used = _read_int(self._vram_used_path)
                if vram_used is not None:
                    result["vramUsedBytes"] = vram_used

        return result if result else None

    @staticmethod
    def _read_dpm_freq(path: str) -> Optional[float]:
        """Parse active frequency from pp_dpm_sclk/pp_dpm_mclk.
        Looks for the line marked with *, falls back to the last entry."""
        try:
            content = _read_file(path).strip()
            if not content:
                return None
            last_freq: Optional[float] = None
            for line in content.split("\n"):
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                cleaned = parts[1].lower().replace("mhz", "")
                try:
                    freq = float(cleaned)
                except ValueError:
                    continue
                if "*" in line:
                    return freq
                last_freq = freq
            return last_freq
        except Exception:
            pass
        return None

    # ── Memory ────────────────────────────────────────────────────────────────

    def _read_memory(self) -> Optional[dict]:
        try:
            content = _read_file("/proc/meminfo")
            total_kb = 0
            available_kb = 0
            swap_total_kb = 0
            swap_free_kb = 0
            for line in content.split("\n"):
                if line.startswith("MemTotal:"):
                    total_kb = int(line.split()[1])
                elif line.startswith("MemAvailable:"):
                    available_kb = int(line.split()[1])
                elif line.startswith("SwapTotal:"):
                    swap_total_kb = int(line.split()[1])
                elif line.startswith("SwapFree:"):
                    swap_free_kb = int(line.split()[1])
            if total_kb > 0:
                total_bytes = total_kb * 1024
                available_bytes = available_kb * 1024
                usage = ((total_kb - available_kb) / total_kb) * 100.0
                result: dict = {
                    "totalBytes": total_bytes,
                    "availableBytes": available_bytes,
                    "usagePercent": round(usage, 1),
                }
                if swap_total_kb > 0:
                    result["swapTotalBytes"] = swap_total_kb * 1024
                    result["swapFreeBytes"] = swap_free_kb * 1024
                return result
        except Exception:
            pass
        return None

    # ── Battery ───────────────────────────────────────────────────────────────

    def _read_battery(self) -> Optional[dict]:
        bats = glob.glob("/sys/class/power_supply/BAT*")
        if not bats:
            return None
        bat = bats[0]
        try:
            capacity = _read_int(os.path.join(bat, "capacity"))
            status = _read_file(os.path.join(bat, "status")).strip()
            if capacity is not None:
                return {"capacity": capacity, "status": status}
        except Exception:
            pass
        return None

    # ── Power (TDP) ───────────────────────────────────────────────────────────

    def _read_power(self) -> Optional[dict]:
        result: dict = {}

        if self._power_cap_path:
            val = _read_int(self._power_cap_path)
            if val is not None:
                result["tdpWatts"] = round(val / 1_000_000.0, 1)

        if self._power_avg_path:
            val = _read_int(self._power_avg_path)
            if val is not None:
                result["powerWatts"] = round(val / 1_000_000.0, 1)

        return result if result else None

    # ── Fan ────────────────────────────────────────────────────────────────────

    def _read_fan(self) -> Optional[dict]:
        if self._fan_path:
            val = _read_int(self._fan_path)
            if val is not None:
                return {"rpm": val}
        return None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _read_file(path: str) -> str:
    """Read a sysfs/procfs file. Returns empty string on failure."""
    try:
        with open(path, "r") as f:
            return f.read()
    except Exception:
        return ""


def _read_int(path: str) -> Optional[int]:
    """Read and parse an integer from a sysfs file."""
    content = _read_file(path).strip()
    if content:
        try:
            return int(content)
        except ValueError:
            pass
    return None
