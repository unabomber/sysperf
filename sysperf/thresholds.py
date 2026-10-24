"""Configurable warn/critical thresholds used across panels and health checks."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Thresholds:
    cpu_warn: float = 70.0
    cpu_crit: float = 90.0
    mem_warn: float = 70.0
    mem_crit: float = 90.0
    swap_warn: float = 50.0
    swap_crit: float = 80.0
    disk_warn: float = 80.0
    disk_crit: float = 92.0
    temp_warn: float = 75.0
    temp_crit: float = 85.0

    def as_dict(self) -> dict:
        return {
            "cpu_warn": self.cpu_warn,
            "cpu_crit": self.cpu_crit,
            "mem_warn": self.mem_warn,
            "mem_crit": self.mem_crit,
            "swap_warn": self.swap_warn,
            "swap_crit": self.swap_crit,
            "disk_warn": self.disk_warn,
            "disk_crit": self.disk_crit,
            "temp_warn": self.temp_warn,
            "temp_crit": self.temp_crit,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Thresholds":
        defaults = cls()
        kwargs = {k: data.get(k, getattr(defaults, k)) for k in defaults.as_dict()}
        return cls(**kwargs)
