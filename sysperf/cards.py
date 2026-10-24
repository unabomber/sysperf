"""KPI hero cards: the big, glanceable strip at the top of the dashboard."""
from __future__ import annotations

from typing import Iterable, List, Optional

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from . import bigfont, theme

MIN_CARD_WIDTH = 25  # fits a 3-digit "100%" LED readout plus border/padding


def _card(icon: str, label: str, percent: float, subtitle: str, bar_width: int = 18) -> Panel:
    color = theme.heat_color(percent)
    digits = f"{int(round(max(0.0, min(100.0, percent))))}"
    body_lines = bigfont.render_number(digits, color)
    body = Group(
        *body_lines,
        Text(""),
        theme.gradient_bar(percent, bar_width),
        Text(subtitle, style="grey62"),
    )
    return Panel(
        body,
        title=f"[bold]{icon} {label}[/bold]",
        box=box.ROUNDED,
        border_style=color,
        padding=(0, 1),
    )


def cpu_card(cpu_total: float, load1: float) -> Panel:
    return _card("🖥", "CPU", cpu_total, f"load {load1:.2f}")


def memory_card(vm) -> Panel:
    subtitle = f"{theme_human(vm.used)} / {theme_human(vm.total)}"
    return _card("🧠", "MEMORY", vm.percent, subtitle)


def disk_card(root) -> Panel:
    free = max(0, root.total - root.used)
    return _card("💾", "DISK /", root.percent, f"{theme_human(free)} free")


def net_card(rx: float, tx: float, rx_series, tx_series) -> Panel:
    from .format_utils import human_rate

    net_max = max(max(rx_series, default=1), max(tx_series, default=1), 1)
    body = Group(
        Text.assemble(("↓ ", "bold " + theme.EMERALD), (human_rate(rx), "bold")),
        theme.gradient_sparkline(rx_series, 18, net_max),
        Text(""),
        Text.assemble(("↑ ", "bold " + theme.SKY), (human_rate(tx), "bold")),
        theme.gradient_sparkline(tx_series, 18, net_max),
    )
    accent = theme.heat_color(min(100.0, (rx + tx) / max(net_max, 1) * 100))
    return Panel(body, title="[bold]🌐 NETWORK[/bold]", box=box.ROUNDED, border_style=accent, padding=(0, 1))


def theme_human(value: float) -> str:
    from .format_utils import human_bytes

    return human_bytes(value)


def kpi_cards(data, state, max_width: int, include_extras_panel: Optional[Panel] = None) -> List[Panel]:
    """Build the ordered list of hero cards, dropping the optional extras
    card first if the terminal is too narrow to fit everything."""
    vm = data["memory"]
    root = data["root"]
    load1, _, _ = data["load"]

    cards = [
        cpu_card(float(data["cpu_total"]), load1),
        memory_card(vm),
        disk_card(root),
        net_card(float(data["rx_rate"]), float(data["tx_rate"]), state.rx, state.tx),
    ]

    if include_extras_panel is not None and max_width >= (len(cards) + 1) * MIN_CARD_WIDTH:
        cards.append(include_extras_panel)

    return cards
