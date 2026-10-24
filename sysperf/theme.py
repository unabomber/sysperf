"""The "Aurora" visual theme: a curated truecolor palette plus gradient
helpers used throughout the panels for a cohesive, premium look.

Rich degrades truecolor hex styles automatically on terminals that don't
support them, so this stays safe on older terminals too.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Iterable, List, Sequence, Tuple

from rich.text import Text

# ---- palette -----------------------------------------------------------

BG_CHIP = "grey15"
FG_CHIP = "grey93"

CYAN = "#22d3ee"
SKY = "#38bdf8"
INDIGO = "#818cf8"
VIOLET = "#a78bfa"
MAGENTA = "#f472b6"
AMBER = "#fbbf24"
ROSE = "#fb7185"
RED = "#ef4444"
EMERALD = "#34d399"
MUTED = "grey58"
DIM = "grey42"
TRACK = "grey23"

BRAND_GRADIENT = [CYAN, SKY, INDIGO, VIOLET, MAGENTA]

_HEAT_STOPS: List[Tuple[float, str]] = [
    (0.0, EMERALD),
    (0.45, CYAN),
    (0.70, AMBER),
    (0.85, ROSE),
    (1.0, RED),
]

BLOCKS8 = " ▁▂▃▄▅▆▇█"


# ---- color math ----------------------------------------------------------

def _hex_to_rgb(value: str) -> Tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _rgb_to_hex(rgb: Tuple[float, float, float]) -> str:
    r, g, b = (max(0, min(255, int(round(c)))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def lerp_color(c1: str, c2: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    return _rgb_to_hex((r1 + (r2 - r1) * t, g1 + (g2 - g1) * t, b1 + (b2 - b1) * t))


def _heat_color_exact(percent: float) -> str:
    p = max(0.0, min(100.0, percent)) / 100.0
    for (t0, c0), (t1, c1) in zip(_HEAT_STOPS, _HEAT_STOPS[1:]):
        if t0 <= p <= t1:
            local_t = (p - t0) / (t1 - t0) if t1 > t0 else 0.0
            return lerp_color(c0, c1, local_t)
    return _HEAT_STOPS[-1][1]


# Precomputed once: heat_color() is called hundreds of times per frame, so
# it's a table lookup rather than repeated hex parsing and interpolation.
_HEAT_TABLE = [_heat_color_exact(i) for i in range(101)]


def heat_color(percent: float) -> str:
    """A smooth emerald -> cyan -> amber -> rose -> red ramp for 0-100."""
    if percent <= 0:
        return _HEAT_TABLE[0]
    if percent >= 100:
        return _HEAT_TABLE[100]
    return _HEAT_TABLE[int(percent + 0.5)]


# ---- text helpers ----------------------------------------------------------

def gradient_text(s: str, stops: Sequence[str] = None, bold: bool = True) -> Text:
    stops = list(stops or BRAND_GRADIENT)
    text = Text(no_wrap=True, overflow="crop")
    if not s:
        return text
    n = max(1, len(s) - 1)
    for i, ch in enumerate(s):
        t = i / n
        seg = t * (len(stops) - 1)
        idx = min(int(seg), len(stops) - 2) if len(stops) > 1 else 0
        local_t = seg - idx
        color = lerp_color(stops[idx], stops[idx + 1], local_t) if len(stops) > 1 else stops[0]
        text.append(ch, style=f"bold {color}" if bold else color)
    return text


def chip(label: str, value: str, accent: str = CYAN) -> Text:
    text = Text(no_wrap=True, overflow="crop")
    text.append(f" {label} ", style=f"bold black on {accent}")
    text.append(f" {value} ", style=f"{FG_CHIP} on {BG_CHIP}")
    return text


@lru_cache(maxsize=4096)
def _bar(filled_n: int, width: int, heat_pct: int, start_color: str) -> Text:
    end_color = _HEAT_TABLE[heat_pct]
    text = Text(no_wrap=True, overflow="crop")
    for i in range(filled_n):
        t = i / max(1, filled_n - 1) if filled_n > 1 else 1.0
        text.append("█", style=f"bold {lerp_color(start_color, end_color, t)}")
    text.append("░" * (width - filled_n), style=TRACK)
    return text


def gradient_bar(value: float, width: int = 24, start_color: str = SKY) -> Text:
    """A left-to-right gradient progress bar, ramping from `start_color`
    toward the value's heat color as it fills — reads as a mini heatmap.

    Bars repeat constantly (idle cores sit at 0%, etc.), so they're cached.
    Treat the returned Text as read-only; Rich only reads it, and
    Text.append(Text) copies, so sharing it is safe."""
    value = max(0.0, min(100.0, value))
    return _bar(int(round(width * value / 100)), width, int(value + 0.5), start_color)


def append_runs(text: Text, items: Iterable[Tuple[str, str]]) -> Text:
    """Append (string, style) pairs, merging adjacent equal styles into one
    span. Rich's per-frame cost and the bytes written to the terminal both
    scale with the number of styled segments, so idle stretches of a chart
    (or the blank cells of an LED digit) collapse into a single segment."""
    run_style = None
    buf: List[str] = []
    for s, style in items:
        if style == run_style:
            buf.append(s)
        else:
            if buf:
                text.append("".join(buf), style=run_style)
            run_style, buf = style, [s]
    if buf:
        text.append("".join(buf), style=run_style)
    return text


def gradient_sparkline(values: Iterable[float], width: int = 32, maximum: float = None) -> Text:
    vals = list(values)[-width:]
    text = Text(no_wrap=True, overflow="crop")
    if not vals:
        return text
    max_value = maximum if maximum is not None else max(vals)
    if max_value <= 0:
        max_value = 1.0
    top_idx = len(BLOCKS8) - 1
    items = []
    for v in vals:
        ratio = max(0.0, min(1.0, v / max_value))
        idx = int(round(ratio * top_idx))
        items.append((BLOCKS8[idx], heat_color(ratio * 100)) if idx else ("·", DIM))
    return append_runs(text, items)


def area_chart(values: Iterable[float], width: int = 32, maximum: float = None) -> Tuple[Text, Text]:
    """A two-row block area chart — roughly double the vertical resolution
    of a single-line sparkline, in the style of modern TUI graphs."""
    vals = list(values)[-width:]
    top, bottom = Text(no_wrap=True, overflow="crop"), Text(no_wrap=True, overflow="crop")
    if not vals:
        return top, bottom
    max_value = maximum if maximum is not None else max(vals)
    if max_value <= 0:
        max_value = 1.0
    levels = len(BLOCKS8) - 1
    top_items, bottom_items = [], []
    for v in vals:
        ratio = max(0.0, min(1.0, v / max_value))
        total_level = int(round(ratio * levels * 2))
        bottom_level = min(levels, total_level)
        top_level = max(0, total_level - levels)
        color = heat_color(ratio * 100)
        bottom_items.append((BLOCKS8[bottom_level], color) if bottom_level else ("·", DIM))
        top_items.append((BLOCKS8[top_level], color) if top_level else (" ", "grey11"))
    append_runs(top, top_items)
    append_runs(bottom, bottom_items)
    return top, bottom


def inline_metric(value: float, width: int = 8) -> Text:
    """A compact `percent + mini gradient bar` combo for table cells."""
    text = Text(no_wrap=True, overflow="crop")
    text.append(f"{value:5.1f}% ", style=f"bold {heat_color(value)}")
    text.append(gradient_bar(value, width))
    return text
