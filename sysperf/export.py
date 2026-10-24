"""Turning a collector sample into JSON (one-shot) or CSV rows (continuous log)."""
from __future__ import annotations

import csv
import os
from typing import Dict, List


def snapshot_to_dict(data: Dict[str, object], timestamp: float) -> Dict[str, object]:
    vm = data["memory"]
    swap = data["swap"]
    root = data["root"]
    load1, load5, load15 = data["load"]
    battery = data.get("battery")
    gpus = data.get("gpus") or []

    return {
        "timestamp": timestamp,
        "cpu_percent": data["cpu_total"],
        "cpu_per_core": list(data["cpu_per_core"]),
        "load1": load1,
        "load5": load5,
        "load15": load15,
        "mem_percent": vm.percent,
        "mem_used": vm.used,
        "mem_total": vm.total,
        "swap_percent": swap.percent,
        "disk_root_percent": root.percent,
        "disk_root_used": root.used,
        "disk_root_total": root.total,
        "net_rx_rate": data["rx_rate"],
        "net_tx_rate": data["tx_rate"],
        "disk_read_rate": data["read_rate"],
        "disk_write_rate": data["write_rate"],
        "cpu_temp_c": data["temp"],
        "battery_percent": battery["percent"] if battery else None,
        "gpu_util_avg": (sum(g["util"] for g in gpus) / len(gpus)) if gpus else None,
    }


CSV_FIELDS = [
    "timestamp", "cpu_percent", "load1", "load5", "load15",
    "mem_percent", "swap_percent", "disk_root_percent",
    "net_rx_rate", "net_tx_rate", "disk_read_rate", "disk_write_rate",
    "cpu_temp_c", "battery_percent", "gpu_util_avg",
]


class CsvLogger:
    """Appends one row per sample to a CSV file, writing a header once."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._write_header = not os.path.isfile(path) or os.path.getsize(path) == 0
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._fh = open(path, "a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if self._write_header:
            self._writer.writeheader()
            self._fh.flush()

    def log(self, data: Dict[str, object], timestamp: float) -> None:
        row = snapshot_to_dict(data, timestamp)
        self._writer.writerow(row)
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.close()
        except OSError:
            pass
