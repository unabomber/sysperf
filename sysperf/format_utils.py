"""Formatting helpers shared by the collector and the panels."""
from __future__ import annotations

from typing import Iterable, List, Optional

from rich.text import Text

BLOCKS = "▁▂▃▄▅▆▇█"


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def sparkline(values: Iterable[float], width: int = 40, maximum: Optional[float] = None) -> str:
    vals = list(values)[-width:]
    if not vals:
        return ""
    max_value = maximum if maximum is not None else max(vals)
    if max_value <= 0:
        max_value = 1.0
    chars: List[str] = []
    for value in vals:
        ratio = clamp(value / max_value, 0.0, 1.0)
        idx = int(round(ratio * (len(BLOCKS) - 1)))
        chars.append(BLOCKS[idx])
    return "".join(chars)


def human_bytes(value: float) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    value = float(value)
    for unit in units:
        if abs(value) < 1024.0 or unit == units[-1]:
            return f"{value:,.1f} {unit}"
        value /= 1024.0
    return f"{value:,.1f} PiB"


def human_rate(value: float) -> str:
    return f"{human_bytes(value)}/s"


def percent_style(value: float, warn: float = 70.0, crit: float = 90.0) -> str:
    if value >= crit:
        return "bold red"
    if value >= warn:
        return "bold yellow"
    return "bold green"


def temp_style(value: float, warn: float = 75.0, crit: float = 85.0) -> str:
    return percent_style(value, warn, crit)


def bar(value: float, width: int = 20, warn: float = 70.0, crit: float = 90.0) -> Text:
    value = clamp(value, 0, 100)
    filled = int(round(width * value / 100))
    style = percent_style(value, warn, crit)
    text = Text()
    text.append("█" * filled, style=style)
    text.append("░" * (width - filled), style="grey30")
    return text


def truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 1:
        return value[:limit]
    return value[: limit - 1] + "…"
