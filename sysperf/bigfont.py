"""A tiny 5-row dot-matrix digit font for LED-style hero numbers.

Only digits and '.' are needed for the KPI cards, so the font stays small
and legible rather than trying to cover the full character set.
"""
from __future__ import annotations

from typing import List

from rich.text import Text

from .theme import append_runs

FONT = {
    "0": ["###", "#.#", "#.#", "#.#", "###"],
    "1": [".#.", "##.", ".#.", ".#.", "###"],
    "2": ["###", "..#", "###", "#..", "###"],
    "3": ["###", "..#", "###", "..#", "###"],
    "4": ["#.#", "#.#", "###", "..#", "..#"],
    "5": ["###", "#..", "###", "..#", "###"],
    "6": ["###", "#..", "###", "#.#", "###"],
    "7": ["###", "..#", ".#.", ".#.", ".#."],
    "8": ["###", "#.#", "###", "#.#", "###"],
    "9": ["###", "#.#", "###", "..#", "###"],
    ".": [".", ".", ".", ".", "#"],
    " ": [" ", " ", " ", " ", " "],
}

ROWS = 5


def render_number(value: str, color: str, cell: str = "█") -> List[Text]:
    """Render `value` (digits and '.') as 5 lines of chunky LED-style text.

    Each row is built as (string, style) pairs and run-length merged, so a
    row of a few digits is a handful of segments rather than one per pixel."""
    lit_style = f"bold {color}"
    lit, dark = cell * 2, "  "
    lines = []
    for row in range(ROWS):
        items = []
        for ch in value:
            glyph = FONT.get(ch, FONT[" "])
            pattern = glyph[row] if row < len(glyph) else ""
            for col_char in pattern:
                items.append((lit, lit_style) if col_char == "#" else (dark, ""))
            items.append((" ", ""))
        lines.append(append_runs(Text(no_wrap=True, overflow="crop"), items))
    return lines
