"""Data collection: turns psutil (and friends) into plain dicts/lists.

Kept free of any Rich/rendering imports so it can be reused or unit tested
independently of the terminal UI.

Cost control: not everything needs refreshing every sample. The cheap,
fast-moving counters (CPU, memory, network, disk I/O) are read every
interval; sensors, mounts, the process table and process/thread counts are
refreshed on slower cadences and served from a cache in between.
"""
from __future__ import annotations

import heapq
import os
import platform
import socket
import time
from collections import deque, namedtuple
from dataclasses import dataclass, field
from datetime import timedelta
from functools import lru_cache
from typing import Callable, Deque, Dict, List, Optional, Tuple

import psutil

from . import gpu as gpu_module

SKIP_FSTYPES = {
    "squashfs", "tmpfs", "devtmpfs", "overlay", "aufs", "proc", "sysfs",
    "cgroup", "cgroup2", "devpts", "autofs", "mqueue", "debugfs", "tracefs",
    "binfmt_misc", "fusectl", "configfs", "pstore", "securityfs", "rpc_pipefs",
    "nsfs",
}
SKIP_MOUNT_PREFIXES = ("/snap/", "/var/lib/docker/")

SORT_MODES = ("cpu", "mem", "pid", "name")

# Refresh cadences in seconds for the slower-moving data.
TEMP_EVERY = 3.0
BATTERY_EVERY = 15.0
DISKS_EVERY = 10.0
IFACES_EVERY = 5.0
COUNTS_EVERY = 5.0
PROC_MIN_EVERY = 2.0

NetTotals = namedtuple("NetTotals", "bytes_recv bytes_sent")

Row = Tuple[int, str, float, float, str]


def safe_cpu_temp() -> Tuple[Optional[float], List[Tuple[str, float]]]:
    try:
        temps = psutil.sensors_temperatures(fahrenheit=False)
    except (AttributeError, OSError):
        return None, []

    readings: List[Tuple[str, float]] = []
    for chip, entries in temps.items():
        for entry in entries:
            if entry.current is None:
                continue
            label = entry.label or chip
            readings.append((label, float(entry.current)))

    if not readings:
        return None, []

    preferred = [t for name, t in readings if any(k in name.lower() for k in ("package", "tdie", "tctl", "cpu"))]
    selected = max(preferred) if preferred else max(t for _, t in readings)
    return selected, readings


def safe_battery() -> Optional[Dict[str, object]]:
    try:
        battery = psutil.sensors_battery()
    except (AttributeError, OSError, NotImplementedError):
        return None
    if battery is None:
        return None
    return {
        "percent": float(battery.percent),
        "plugged": bool(battery.power_plugged),
        "secsleft": battery.secsleft,
    }


def other_partitions(exclude_mount: str = "/", limit: int = 4) -> List[Dict[str, object]]:
    results: List[Dict[str, object]] = []
    try:
        partitions = psutil.disk_partitions(all=False)
    except OSError:
        return results

    for part in partitions:
        if part.mountpoint == exclude_mount:
            continue
        if part.fstype in SKIP_FSTYPES:
            continue
        if part.mountpoint.startswith(SKIP_MOUNT_PREFIXES):
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        results.append(
            {
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "used": usage.used,
                "total": usage.total,
                "percent": usage.percent,
            }
        )

    results.sort(key=lambda r: r["percent"], reverse=True)
    return results[:limit]


def boot_uptime() -> str:
    seconds = max(0, int(time.time() - psutil.boot_time()))
    return str(timedelta(seconds=seconds))


@lru_cache(maxsize=1)
def host_info() -> Tuple[str, str]:
    """(hostname, kernel release) — neither changes while we're running."""
    return socket.gethostname(), platform.release()


_ip_cache: List[object] = [0.0, None]
_IP_TTL = 60.0


def local_ip() -> Optional[str]:
    now = time.monotonic()
    if now < _ip_cache[0]:
        return _ip_cache[1]

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ip: Optional[str] = None
    try:
        sock.settimeout(0.2)
        # No packet is actually sent for UDP connect(); this just asks the
        # OS which local address would be used to reach the target.
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
    except OSError:
        ip = None
    finally:
        sock.close()
    _ip_cache[0], _ip_cache[1] = now + _IP_TTL, ip
    return ip


def thread_count() -> Optional[int]:
    """Total kernel threads. /proc/loadavg's 4th field is "running/total"
    scheduling entities — one tiny read instead of walking every process."""
    try:
        with open("/proc/loadavg", "r") as fh:
            return int(fh.read().split()[3].split("/")[1])
    except (OSError, ValueError, IndexError):
        pass
    try:  # non-Linux fallback: slow, but only runs on COUNTS_EVERY
        return sum(p.num_threads() for p in psutil.process_iter() if p.is_running())
    except (psutil.Error, OSError):
        return None


_HAVE_PROC = os.path.exists("/proc/self/stat")
_CLK_TCK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
_PAGE_SIZE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
_STATE_NAMES = {
    "R": "running", "S": "sleeping", "D": "disk-sleep", "Z": "zombie",
    "T": "stopped", "t": "stopped", "X": "dead", "x": "dead", "I": "idle",
    "W": "waking", "K": "wakekill", "P": "parked",
}


class ProcScanner:
    """Fast Linux process table straight from /proc.

    One read of /proc/<pid>/stat yields the name, state, CPU time and RSS, so
    this avoids psutil's per-process object/decorator overhead (~5x faster
    on a box with hundreds of processes). /proc/<pid>/stat is world-readable,
    so there are no permission gaps either."""

    def __init__(self) -> None:
        self._prev: Dict[int, Tuple[int, int]] = {}  # pid -> (starttime, cpu ticks)
        self._prev_time: Optional[float] = None
        self._total_mem = psutil.virtual_memory().total or 1

    def scan(self) -> List[Row]:
        now = time.monotonic()
        elapsed = (now - self._prev_time) if self._prev_time is not None else 0.0
        prev, cur = self._prev, {}
        rows: List[Row] = []
        mem_scale = _PAGE_SIZE * 100.0 / self._total_mem
        cpu_scale = (100.0 / _CLK_TCK / elapsed) if elapsed > 0 else 0.0

        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                fd = os.open(f"/proc/{entry}/stat", os.O_RDONLY)
                try:
                    data = os.read(fd, 2048)
                finally:
                    os.close(fd)
            except OSError:
                continue  # exited between listdir and open
            try:
                lparen, rparen = data.index(b"("), data.rindex(b")")
                fields = data[rparen + 2:].split()
                pid = int(entry)
                ticks = int(fields[11]) + int(fields[12])
                start = int(fields[19])
                rss = int(fields[21])
                state = fields[0].decode("ascii", "replace")
            except (ValueError, IndexError):
                continue

            cur[pid] = (start, ticks)
            old = prev.get(pid)
            cpu = ((ticks - old[1]) * cpu_scale) if old is not None and old[0] == start and cpu_scale else 0.0
            rows.append((
                pid,
                data[lparen + 1:rparen].decode("utf-8", "replace"),
                cpu,
                rss * mem_scale,
                _STATE_NAMES.get(state, state),
            ))

        self._prev, self._prev_time = cur, now
        return rows


def scan_processes() -> List[Row]:
    """Portable (psutil) process table — used where /proc isn't available."""
    rows: List[Row] = []
    for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status"]):
        try:
            info = proc.info
            rows.append((
                int(info.get("pid") or 0),
                str(info.get("name") or "?"),
                float(info.get("cpu_percent") or 0),
                float(info.get("memory_percent") or 0),
                str(info.get("status") or "?"),
            ))
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
            continue
    return rows


def process_rows(rows: List[Row], limit: int = 8, sort_mode: str = "cpu", name_filter: str = "") -> List[Row]:
    """Pick the top `limit` rows from an already-scanned process table.

    Pure function over cached rows, so changing sort/filter is instant and
    costs no extra /proc reads."""
    needle = name_filter.strip().lower()
    if needle:
        rows = [r for r in rows if needle in r[1].lower()]

    if sort_mode == "mem":
        return heapq.nlargest(limit, rows, key=lambda r: r[3])
    if sort_mode == "pid":
        return heapq.nsmallest(limit, rows, key=lambda r: r[0])
    if sort_mode == "name":
        return heapq.nsmallest(limit, rows, key=lambda r: r[1].lower())
    return heapq.nlargest(limit, rows, key=lambda r: (r[2], r[3]))


@dataclass
class SampleState:
    history: int = 60
    interval: float = 1.0
    scan_processes: bool = True   # skip the process scan entirely if the table is hidden
    stream_gpu: bool = True       # False => one-shot nvidia-smi (used by --once)
    cpu: Deque[float] = field(init=False)
    load: Deque[float] = field(init=False)
    rx: Deque[float] = field(init=False)
    tx: Deque[float] = field(init=False)
    disk_read: Deque[float] = field(init=False)
    disk_write: Deque[float] = field(init=False)
    last_net: object = field(default=None)
    last_disk: object = field(default=None)
    last_pernic: Dict[str, object] = field(default_factory=dict)
    last_time: Optional[float] = None
    proc_rows: List[Row] = field(default_factory=list)
    sort_index: int = 0
    filter_text: str = ""
    _cache: Dict[str, Tuple[float, object]] = field(default_factory=dict)
    _gpu: Optional[gpu_module.GpuMonitor] = None
    _scanner: Optional[ProcScanner] = None

    def __post_init__(self) -> None:
        self.cpu = deque(maxlen=self.history)
        self.load = deque(maxlen=self.history)
        self.rx = deque(maxlen=self.history)
        self.tx = deque(maxlen=self.history)
        self.disk_read = deque(maxlen=self.history)
        self.disk_write = deque(maxlen=self.history)

    @property
    def sort_mode(self) -> str:
        return SORT_MODES[self.sort_index % len(SORT_MODES)]

    def cycle_sort(self) -> None:
        self.sort_index = (self.sort_index + 1) % len(SORT_MODES)

    def reset(self) -> None:
        for series in (self.cpu, self.load, self.rx, self.tx, self.disk_read, self.disk_write):
            series.clear()
        self.last_net = None
        self.last_disk = None
        self.last_pernic = {}
        self.last_time = None

    def close(self) -> None:
        if self._gpu is not None:
            self._gpu.stop()

    def _cached(self, key: str, now: float, every: float, fn: Callable[[], object]) -> object:
        entry = self._cache.get(key)
        if entry is None or now >= entry[0]:
            entry = (now + every, fn())
            self._cache[key] = entry
        return entry[1]

    def _gpus(self) -> List[Dict[str, object]]:
        if not self.stream_gpu:
            return gpu_module.get_gpu_stats()
        if self._gpu is None:
            self._gpu = gpu_module.GpuMonitor()
            self._gpu.start()
        return self._gpu.latest()

    def _pernic_rates(self, now: float, pernic: Dict[str, object], elapsed: float) -> List[Tuple[str, float, float]]:
        def up_interfaces():
            try:
                return {n for n, s in psutil.net_if_stats().items() if s.isup}
            except OSError:
                return None

        up = self._cached("ifaces", now, IFACES_EVERY, up_interfaces)

        rates: List[Tuple[str, float, float]] = []
        for name, counters in pernic.items():
            if name == "lo" or name.startswith(("veth", "docker")):
                continue
            if up is not None and name not in up:
                continue
            prev = self.last_pernic.get(name)
            if prev is not None:
                rx_rate = max(0, counters.bytes_recv - prev.bytes_recv) / elapsed
                tx_rate = max(0, counters.bytes_sent - prev.bytes_sent) / elapsed
                if rx_rate > 0 or tx_rate > 0:
                    rates.append((name, rx_rate, tx_rate))
        self.last_pernic = pernic
        rates.sort(key=lambda r: r[1] + r[2], reverse=True)
        return rates

    def sample(self) -> Dict[str, object]:
        now = time.monotonic()

        # --- cheap, every-sample counters -----------------------------------
        cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
        cpu_total = (sum(cpu_per_core) / len(cpu_per_core)) if cpu_per_core else 0.0
        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disk_io = psutil.disk_io_counters()
        root = psutil.disk_usage("/")

        # One /proc/net/dev read; the aggregate is just the sum of the NICs.
        pernic = psutil.net_io_counters(pernic=True)
        net = NetTotals(
            sum(c.bytes_recv for c in pernic.values()),
            sum(c.bytes_sent for c in pernic.values()),
        )

        elapsed = (now - self.last_time) if self.last_time is not None else 1.0
        elapsed = max(elapsed, 0.001)

        rx_rate = tx_rate = read_rate = write_rate = 0.0
        if self.last_net is not None:
            rx_rate = max(0, net.bytes_recv - self.last_net.bytes_recv) / elapsed
            tx_rate = max(0, net.bytes_sent - self.last_net.bytes_sent) / elapsed
        if self.last_disk is not None and disk_io is not None:
            read_rate = max(0, disk_io.read_bytes - self.last_disk.read_bytes) / elapsed
            write_rate = max(0, disk_io.write_bytes - self.last_disk.write_bytes) / elapsed

        pernic_rates = self._pernic_rates(now, pernic, elapsed)

        try:
            load1, load5, load15 = os.getloadavg()
        except (AttributeError, OSError):
            load1 = load5 = load15 = 0.0

        self.cpu.append(cpu_total)
        self.load.append(load1)
        self.rx.append(rx_rate)
        self.tx.append(tx_rate)
        self.disk_read.append(read_rate)
        self.disk_write.append(write_rate)

        self.last_net = net
        self.last_disk = disk_io
        self.last_time = now

        # --- slower cadences, served from cache in between -------------------
        temp, all_temps = self._cached("temps", now, TEMP_EVERY, safe_cpu_temp)
        if self.scan_processes:
            if self._scanner is None and _HAVE_PROC:
                self._scanner = ProcScanner()
            scan = self._scanner.scan if self._scanner is not None else scan_processes
            self.proc_rows = self._cached("procs", now, max(PROC_MIN_EVERY, self.interval), scan)

        return {
            "cpu_total": cpu_total,
            "cpu_per_core": cpu_per_core,
            "memory": vm,
            "swap": swap,
            "load": (load1, load5, load15),
            "net": net,
            "disk_io": disk_io,
            "rx_rate": rx_rate,
            "tx_rate": tx_rate,
            "read_rate": read_rate,
            "write_rate": write_rate,
            "pernic": pernic_rates,
            "temp": temp,
            "temps": all_temps,
            "root": root,
            "other_disks": self._cached("disks", now, DISKS_EVERY, other_partitions),
            "battery": self._cached("battery", now, BATTERY_EVERY, safe_battery),
            "gpus": self._gpus(),
            "proc_count": self._cached("pids", now, COUNTS_EVERY, lambda: len(psutil.pids())),
            "thread_count": self._cached("threads", now, COUNTS_EVERY, thread_count),
        }
