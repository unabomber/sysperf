"""Optional NVIDIA GPU polling via `nvidia-smi`.

No extra Python dependency is required. Two modes:

* `GpuMonitor` keeps ONE long-lived `nvidia-smi -l` process and reads its
  output from a background thread. Spawning nvidia-smi per sample costs
  ~40 ms of CPU each time (NVML init), so streaming is far cheaper.
* `get_gpu_stats()` is a one-shot query, used by `--once`.

Any failure (binary missing, driver error, unexpected output) simply means
"no GPUs" so this stays fully optional on machines without NVIDIA hardware.
"""
from __future__ import annotations

import atexit
import shutil
import subprocess
import threading
from typing import Dict, List, Optional

_FIELDS = "index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw"
_STREAM_FIELDS = _FIELDS + ",count"

_unavailable = False


def _parse_float(raw: str) -> Optional[float]:
    raw = raw.strip()
    if not raw or raw.upper() in ("N/A", "[N/A]", "[NOT SUPPORTED]"):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def parse_line(line: str, fallback_index: int = 0) -> Optional[Dict[str, object]]:
    parts = [p.strip() for p in line.strip().split(",")]
    if len(parts) < 7:
        return None
    try:
        index = int(parts[0])
    except ValueError:
        index = fallback_index
    count = int(parts[7]) if len(parts) > 7 and parts[7].isdigit() else None
    return {
        "index": index,
        "name": parts[1] or f"GPU{index}",
        "util": _parse_float(parts[2]) or 0.0,
        "mem_used_mib": _parse_float(parts[3]) or 0.0,
        "mem_total_mib": _parse_float(parts[4]) or 0.0,
        "temp": _parse_float(parts[5]),
        "power_w": _parse_float(parts[6]),
        "count": count,
    }


def get_gpu_stats(timeout: float = 1.0) -> List[Dict[str, object]]:
    """One-shot query; returns [] if unavailable."""
    global _unavailable
    if _unavailable:
        return []
    try:
        result = subprocess.run(
            ["nvidia-smi", f"--query-gpu={_FIELDS}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=timeout,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        _unavailable = True
        return []
    if result.returncode != 0 or not result.stdout.strip():
        _unavailable = True
        return []
    gpus = []
    for line in result.stdout.strip().splitlines():
        gpu = parse_line(line, len(gpus))
        if gpu is not None:
            gpus.append(gpu)
    return gpus


class GpuMonitor:
    """Streams GPU stats from a single `nvidia-smi -l <period>` process."""

    def __init__(self, period: int = 3) -> None:
        self._period = max(1, int(period))
        self._latest: List[Dict[str, object]] = []
        self._proc: Optional[subprocess.Popen] = None
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        if shutil.which("nvidia-smi") is None:
            return
        try:
            self._proc = subprocess.Popen(
                ["nvidia-smi", f"--query-gpu={_STREAM_FIELDS}", "--format=csv,noheader,nounits",
                 "-l", str(self._period)],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                text=True, bufsize=1,
            )
        except OSError:
            self._proc = None
            return
        atexit.register(self.stop)
        threading.Thread(target=self._read, name="sysperf-gpu", daemon=True).start()

    def _read(self) -> None:
        batch: List[Dict[str, object]] = []
        try:
            for line in self._proc.stdout:  # blocks; costs nothing while idle
                gpu = parse_line(line, len(batch))
                if gpu is None:
                    continue
                batch.append(gpu)
                if len(batch) >= (gpu["count"] or 1):
                    self._latest = batch
                    batch = []
        except (OSError, ValueError):
            pass
        self._latest = []  # nvidia-smi exited; stop showing stale data

    def latest(self) -> List[Dict[str, object]]:
        return self._latest

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                proc.kill()
