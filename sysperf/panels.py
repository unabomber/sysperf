"""Rich panel builders and the overall dashboard layout — the "Aurora" theme."""
from __future__ import annotations

from functools import lru_cache
from typing import Dict, List, Optional, Sequence

import psutil
from rich import box
from rich.align import Align
from rich.console import Group
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import theme
from .cards import MIN_CARD_WIDTH, kpi_cards
from .collector import SampleState, boot_uptime, host_info, local_ip, process_rows
from .format_utils import human_bytes, human_rate, truncate
from .thresholds import Thresholds

KEYBINDS = [
    ("q", "quit"),
    ("p", "pause"),
    ("r", "reset graphs"),
    ("s", "cycle process sort"),
    ("/", "filter processes"),
    ("x", "toggle compact CPU view"),
    ("h", "toggle help"),
]

@lru_cache(maxsize=1)
def _logical_cpus() -> int:
    return psutil.cpu_count(logical=True) or 1


HEADER_SIZE = 4
FOOTER_SIZE = 3
KPI_ROW_HEIGHT = 10
MIN_MAIN_HEIGHT = 14
STATUS_COLORS = {
    "running": theme.EMERALD,
    "sleeping": theme.MUTED,
    "disk-sleep": theme.AMBER,
    "stopped": theme.AMBER,
    "zombie": theme.RED,
}


def make_header(data: Dict[str, object], paused: bool, show_ip: bool = True, width: Optional[int] = None) -> Panel:
    host, kernel = host_info()
    cpu_count = _logical_cpus()
    temp = data["temp"]
    w = width or 999

    brand = theme.gradient_text("SYS", stops=[theme.CYAN, theme.SKY])
    brand.append("PERF", style=f"bold {theme.MAGENTA}")
    status_dot = Text("●  ", style=f"bold {theme.EMERALD if not paused else theme.AMBER}")
    title_line = Text()
    title_line.append_text(status_dot)
    title_line.append_text(brand)
    if w >= 70:
        title_line.append("  a real-time system dashboard", style="grey58 italic")
    if paused:
        title_line.append("   ⏸ PAUSED", style=f"bold {theme.AMBER} reverse")

    # Lower-priority chips drop off first on narrow terminals so the row
    # never wraps or gets cropped mid-chip.
    chips = Text()
    chips.append_text(theme.chip("HOST", truncate(host, 18), theme.INDIGO))
    if w >= 80:
        chips.append(" ")
        chips.append_text(theme.chip("THREADS", str(cpu_count), theme.SKY))
    if w >= 95:
        chips.append(" ")
        chips.append_text(theme.chip("KERNEL", truncate(f"Linux {kernel}", 20), theme.VIOLET))
    chips.append(" ")
    chips.append_text(theme.chip("UPTIME", boot_uptime(), theme.CYAN))
    if show_ip and w >= 115:
        ip = local_ip()
        if ip:
            chips.append(" ")
            chips.append_text(theme.chip("IP", ip, theme.EMERALD))
    if temp is not None and w >= 90:
        chips.append(" ")
        chips.append_text(theme.chip("CPU TEMP", f"{temp:.0f}°C", theme.heat_color(temp)))

    body = Group(Align.center(title_line), Align.center(chips))
    return Panel(body, box=box.HEAVY, border_style=theme.INDIGO, padding=(0, 1))


def make_cpu_panel(data: Dict[str, object], state: SampleState, thresholds: Thresholds, compact: bool, width: Optional[int] = None) -> Panel:
    total = float(data["cpu_total"])
    cores: Sequence[float] = data["cpu_per_core"]
    load1, load5, load15 = data["load"]
    logical = max(1, len(cores))
    cap_pct = (load1 / logical) * 100

    title = Text(" ⚙ CPU ", style="bold")
    table = Table.grid(expand=True)
    table.add_column(ratio=1, no_wrap=True, overflow="crop")
    table.add_column(justify="right", width=8, no_wrap=True, overflow="crop")
    table.add_row(
        Text("Utilisation", style="bold grey78"),
        Text(f"{total:5.1f}%", style=f"bold {theme.heat_color(total)}"),
    )
    table.add_row(theme.gradient_bar(total, 30), theme.gradient_sparkline(state.cpu, 24, 100))
    table.add_row(
        Text(f"Load  1m {load1:.2f}   5m {load5:.2f}   15m {load15:.2f}", style="grey62"),
        Text(f"{cap_pct:4.0f}% cap", style=f"bold {theme.heat_color(cap_pct)}"),
    )

    if compact:
        return Panel(table, title=title, box=box.ROUNDED, border_style=theme.heat_color(total))

    # The CPU panel occupies roughly 3/5 of the console width (left column,
    # ratio=3 vs. ratio=2) — estimate it to size the core grid without wrapping.
    panel_width = (int(width * 3 / 5) - 4) if width else 70
    cell_width = 20  # "C00 " + a 10-wide bar + " 100%"
    max_columns = max(1, panel_width // cell_width)
    if len(cores) >= 6:
        columns = min(4, max(2, max_columns))
    else:
        columns = min(2, max(1, max_columns))
    bar_width = 10 if columns <= 3 else 8

    core_table = Table.grid(expand=True, padding=(0, 1))
    for _ in range(columns):
        core_table.add_column(ratio=1, no_wrap=True, overflow="crop")
    cells: List[Text] = []
    for idx, value in enumerate(cores):
        cell = Text(no_wrap=True, overflow="crop")
        cell.append(f"C{idx:02d} ", style="grey58")
        cell.append(theme.gradient_bar(value, bar_width))
        cell.append(f" {value:4.0f}%", style=theme.heat_color(value))
        cells.append(cell)
    while len(cells) % columns:
        cells.append(Text(""))
    for i in range(0, len(cells), columns):
        core_table.add_row(*cells[i:i + columns])

    return Panel(Group(table, Text(""), core_table), title=title, box=box.ROUNDED, border_style=theme.heat_color(total))


def make_memory_panel(data: Dict[str, object], thresholds: Thresholds, width: Optional[int] = None) -> Panel:
    vm = data["memory"]
    swap = data["swap"]
    root = data["root"]
    other_disks = data.get("other_disks") or []

    # The memory panel occupies roughly 2/5 of the console width (right
    # column, ratio=2 vs. ratio=3). The "used/total percent" readout is the
    # important bit, so it always gets its width first; the bar gets
    # whatever's left over (down to a thin sliver on very narrow terminals).
    panel_width = (int(width * 2 / 5) - 4) if width else 50
    label_width = 6
    remaining = max(10, panel_width - label_width)
    value_width = 24
    bar_width = min(32, max(2, remaining - value_width))

    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(width=label_width, no_wrap=True, overflow="crop")
    table.add_column(width=bar_width, no_wrap=True, overflow="crop")
    table.add_column(justify="right", width=value_width, no_wrap=True, overflow="crop")

    def row(label: str, percent: float, used: float, total: float) -> None:
        table.add_row(
            label,
            theme.gradient_bar(percent, bar_width),
            Text(f"{human_bytes(used)}/{human_bytes(total)} {percent:.0f}%", style=f"bold {theme.heat_color(percent)}"),
        )

    row("RAM", vm.percent, vm.used, vm.total)
    row("Swap", swap.percent, swap.used, swap.total)
    row("Root /", root.percent, root.used, root.total)
    for disk in other_disks:
        row(truncate(disk["mountpoint"], label_width), disk["percent"], disk["used"], disk["total"])

    available = getattr(vm, "available", 0)
    cached = getattr(vm, "cached", 0)
    info = Text(f"Available {human_bytes(available)}   Cached {human_bytes(cached)}", style="grey58")
    return Panel(Group(table, info), title="[bold]🧠 Memory & Storage[/bold]", box=box.ROUNDED, border_style=theme.heat_color(vm.percent))


def make_io_panel(data: Dict[str, object], state: SampleState) -> Panel:
    rx = float(data["rx_rate"])
    tx = float(data["tx_rate"])
    read = float(data["read_rate"])
    write = float(data["write_rate"])
    net = data["net"]
    pernic = data.get("pernic") or []

    net_max = max(max(state.rx, default=1), max(state.tx, default=1), 1)
    disk_max = max(max(state.disk_read, default=1), max(state.disk_write, default=1), 1)

    def area_row(label: str, value: float, series, maximum: float, accent: str) -> Table:
        top, bottom = theme.area_chart(series, 34, maximum)
        grid = Table.grid(expand=True)
        grid.add_column(width=11, no_wrap=True, overflow="crop")
        grid.add_column(width=13, no_wrap=True, overflow="crop")
        grid.add_column(ratio=1, no_wrap=True, overflow="crop")
        grid.add_row(Text(label, style=f"bold {accent}"), Text(human_rate(value), style="bold"), top)
        grid.add_row("", "", bottom)
        return grid

    parts = [
        area_row("Net ↓", rx, state.rx, net_max, theme.EMERALD),
        area_row("Net ↑", tx, state.tx, net_max, theme.SKY),
        area_row("Disk R", read, state.disk_read, disk_max, theme.VIOLET),
        area_row("Disk W", write, state.disk_write, disk_max, theme.AMBER),
    ]

    if len(pernic) > 1:
        nic_table = Table.grid(expand=True, padding=(0, 1))
        nic_table.add_column(width=10, no_wrap=True, overflow="crop")
        nic_table.add_column(justify="right", width=12, no_wrap=True, overflow="crop")
        nic_table.add_column(justify="right", width=12, no_wrap=True, overflow="crop")
        nic_table.add_row(Text("Interface", style="grey58"), Text("↓", style="grey58"), Text("↑", style="grey58"))
        for name, rx_rate, tx_rate in pernic[:3]:
            nic_table.add_row(truncate(name, 10), Text(human_rate(rx_rate), style=theme.EMERALD), Text(human_rate(tx_rate), style=theme.SKY))
        parts.append(nic_table)

    totals = Text(f"Totals  ↓ {human_bytes(net.bytes_recv)}   ↑ {human_bytes(net.bytes_sent)}", style="grey58")
    parts.append(totals)
    return Panel(Group(*parts), title="[bold]🌐 Throughput[/bold]", box=box.ROUNDED, border_style=theme.SKY)


def make_extras_panel(data: Dict[str, object], thresholds: Thresholds) -> Optional[Panel]:
    """GPU + battery panel. Returns None when neither is available (panel is omitted)."""
    gpus = data.get("gpus") or []
    battery = data.get("battery")
    if not gpus and not battery:
        return None

    rows: List[Text] = []
    for g in gpus:
        line = Text()
        line.append(f"GPU{g['index']} ", style="bold")
        line.append(truncate(str(g["name"]), 18).ljust(18), style="grey62")
        line.append(f" {g['util']:5.1f}%", style=theme.heat_color(g["util"]))
        if g["mem_total_mib"]:
            mem_pct = 100.0 * g["mem_used_mib"] / g["mem_total_mib"]
            line.append(f"  VRAM {mem_pct:4.0f}%", style=theme.heat_color(mem_pct))
        if g.get("temp") is not None:
            line.append(f"  {g['temp']:.0f}°C", style=theme.heat_color(g["temp"]))
        if g.get("power_w") is not None:
            line.append(f"  {g['power_w']:.0f}W", style="grey58")
        rows.append(line)

    if battery is not None:
        line = Text()
        icon = "⚡" if battery["plugged"] else "🔋"
        line.append(f"{icon} Battery ", style="bold")
        line.append(f"{battery['percent']:.0f}%", style=theme.heat_color(100 - battery["percent"]))
        if battery["plugged"]:
            line.append("  charging", style="grey58")
        elif isinstance(battery["secsleft"], (int, float)) and battery["secsleft"] > 0:
            hours, rem = divmod(int(battery["secsleft"]), 3600)
            minutes = rem // 60
            line.append(f"  {hours}h{minutes:02d}m left", style="grey58")
        rows.append(line)

    body = Text("\n").join(rows) if rows else Text("")
    return Panel(body, title="[bold]⚡ GPU / Power[/bold]", box=box.ROUNDED, border_style=theme.MAGENTA, padding=(0, 1))


def make_process_panel(state: SampleState, limit: int = 8) -> Panel:
    table = Table(expand=True, box=None, padding=(0, 1))
    table.add_column("", width=1)
    table.add_column("PID", justify="right", width=8, style="grey58", no_wrap=True)
    table.add_column("Process", ratio=1, no_wrap=True, overflow="crop")
    table.add_column("CPU", justify="left", width=15, no_wrap=True, overflow="crop")
    table.add_column("MEM", justify="left", width=15, no_wrap=True, overflow="crop")
    table.add_column("State", justify="center", width=10, no_wrap=True, overflow="crop")

    for pid, name, cpu, mem, status in process_rows(state.proc_rows, limit, state.sort_mode, state.filter_text):
        accent = theme.heat_color(max(cpu, mem))
        status_color = STATUS_COLORS.get(status, theme.MUTED)
        table.add_row(
            Text("▎", style=f"bold {accent}"),
            str(pid),
            truncate(name, 28),
            theme.inline_metric(cpu, 8),
            theme.inline_metric(mem, 8),
            Text(status, style=status_color),
        )

    title = f"[bold]📊 Top Processes[/bold] [grey58]· sort {state.sort_mode}[/grey58]"
    footer_bits = []
    if state.filter_text:
        footer_bits.append(Text(f"filter: {state.filter_text}", style=f"bold {theme.AMBER}"))
    group = Group(table, *footer_bits) if footer_bits else table
    return Panel(group, title=title, box=box.ROUNDED, border_style=theme.VIOLET)


def make_health_panel(data: Dict[str, object], thresholds: Thresholds) -> Panel:
    cpu = float(data["cpu_total"])
    vm = data["memory"]
    root = data["root"]
    temp = data["temp"]
    load1, _, _ = data["load"]
    cpus = _logical_cpus()

    checks: List[tuple] = []

    def add(label: str, ok: bool, detail: str, warn: bool = False) -> None:
        if ok:
            checks.append(("✓", theme.EMERALD, f"{label}: {detail}"))
        elif warn:
            checks.append(("▲", theme.AMBER, f"{label}: {detail}"))
        else:
            checks.append(("✕", theme.RED, f"{label}: {detail}"))

    add("CPU", cpu < thresholds.cpu_crit, f"{cpu:.0f}% utilised", warn=cpu < thresholds.cpu_crit + 7)
    add("RAM", vm.percent < thresholds.mem_crit, f"{vm.percent:.0f}% used", warn=vm.percent < thresholds.mem_crit + 6)
    add("Disk", root.percent < thresholds.disk_crit, f"{root.percent:.0f}% used on /", warn=root.percent < thresholds.disk_crit + 5)
    add("Load", load1 < cpus * 1.25, f"{load1:.2f} on {cpus} threads", warn=load1 < cpus * 2)
    if temp is None:
        checks.append(("·", theme.DIM, "Temperature: sensor unavailable"))
    else:
        add("Temperature", temp < thresholds.temp_crit, f"{temp:.0f}°C", warn=temp < thresholds.temp_crit + 7)

    battery = data.get("battery")
    if battery is not None and not battery["plugged"] and battery["percent"] < 15:
        checks.append(("✕", theme.RED, f"Battery: {battery['percent']:.0f}% remaining, unplugged"))

    processes = data.get("proc_count") or 0
    threads = data.get("thread_count") or 0

    text = Text()
    for idx, (icon, color, message) in enumerate(checks):
        if idx:
            text.append("\n")
        text.append(f"{icon} ", style=f"bold {color}")
        text.append(message, style=color)
    text.append(f"\n\nProcesses {processes:,}   Threads {threads:,}", style="grey58")
    return Panel(text, title="[bold]💠 Health[/bold]", box=box.ROUNDED, border_style="grey50")


def make_footer(interval: float, filter_mode: bool) -> Panel:
    footer = Text()
    if filter_mode:
        footer.append("⌨ ", style="bold")
        footer.append("Type to filter", style=f"bold {theme.AMBER}")
        footer.append("  ·  Enter to apply  ·  Esc to clear", style="grey58")
    else:
        for idx, (key, label) in enumerate(KEYBINDS):
            if idx:
                footer.append("   ")
            footer.append(f" {key} ", style=f"bold black on {theme.CYAN}")
            footer.append(f" {label}", style="grey70")
        footer.append(f"    refresh {interval:g}s", style="grey50")
    return Panel(Align.center(footer), box=box.ROUNDED, border_style="grey35", padding=(0, 1))


def make_help_panel(config_path: Optional[str], thresholds: Thresholds) -> Panel:
    lines = [theme.gradient_text("Keybindings", stops=[theme.CYAN, theme.VIOLET])]
    for key, label in KEYBINDS:
        line = Text()
        line.append(f"  {key:<3}", style=f"bold {theme.CYAN}")
        line.append(label, style="grey78")
        lines.append(line)

    lines.append(Text(""))
    lines.append(theme.gradient_text("Thresholds (warn / crit)", stops=[theme.CYAN, theme.VIOLET]))
    lines.append(Text.assemble(("  CPU  ", "grey78"), (f"{thresholds.cpu_warn:.0f}% / {thresholds.cpu_crit:.0f}%", "bold")))
    lines.append(Text.assemble(("  RAM  ", "grey78"), (f"{thresholds.mem_warn:.0f}% / {thresholds.mem_crit:.0f}%", "bold")))
    lines.append(Text.assemble(("  Disk ", "grey78"), (f"{thresholds.disk_warn:.0f}% / {thresholds.disk_crit:.0f}%", "bold")))
    lines.append(Text.assemble(("  Temp ", "grey78"), (f"{thresholds.temp_warn:.0f}°C / {thresholds.temp_crit:.0f}°C", "bold")))

    if config_path:
        lines.append(Text(""))
        lines.append(Text(f"Config file: {config_path}", style="grey58"))

    return Panel(Group(*lines), title="[bold]❔ Help[/bold]", box=box.ROUNDED, border_style=theme.VIOLET)


def build_dashboard(
    data: Dict[str, object],
    state: SampleState,
    interval: float,
    show_processes: bool,
    paused: bool,
    thresholds: Thresholds,
    compact: bool = False,
    filter_mode: bool = False,
    show_help: bool = False,
    config_path: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    process_limit: int = 8,
) -> Layout:
    layout = Layout()

    extras_panel = make_extras_panel(data, thresholds)
    base_card_count = 4
    show_kpis = width is None or width >= base_card_count * MIN_CARD_WIDTH
    if show_kpis and height is not None:
        needed = HEADER_SIZE + KPI_ROW_HEIGHT + FOOTER_SIZE + MIN_MAIN_HEIGHT
        show_kpis = height >= needed

    sections = [Layout(name="header", size=HEADER_SIZE)]
    if show_kpis:
        sections.append(Layout(name="kpis", size=KPI_ROW_HEIGHT))
    sections.append(Layout(name="main"))
    sections.append(Layout(name="footer", size=FOOTER_SIZE))
    layout.split_column(*sections)

    layout["header"].update(make_header(data, paused, width=width))
    layout["footer"].update(make_footer(interval, filter_mode))

    if show_kpis:
        cards = kpi_cards(data, state, width or 999, include_extras_panel=extras_panel)
        layout["kpis"].split_row(*[Layout(name=f"kpi{i}", ratio=1) for i in range(len(cards))])
        for i, card in enumerate(cards):
            layout["kpis"][f"kpi{i}"].update(card)

    if show_help:
        layout["main"].update(make_help_panel(config_path, thresholds))
        return layout

    layout["main"].split_row(Layout(name="left", ratio=3), Layout(name="right", ratio=2))
    layout["left"].split_column(Layout(name="cpu", ratio=3), Layout(name="io", ratio=2))
    layout["cpu"].update(make_cpu_panel(data, state, thresholds, compact, width=width))
    layout["io"].update(make_io_panel(data, state))

    right_children = [Layout(name="memory", ratio=2)]
    if extras_panel is not None and not show_kpis:
        # Only show the standalone extras panel when it isn't already
        # riding along in the KPI strip.
        right_children.append(Layout(name="extras", ratio=1))
    if show_processes:
        right_children.append(Layout(name="processes", ratio=3))
    right_children.append(Layout(name="health", ratio=2))

    layout["right"].split_column(*right_children)
    layout["memory"].update(make_memory_panel(data, thresholds, width=width))
    if extras_panel is not None and not show_kpis:
        layout["extras"].update(extras_panel)
    if show_processes:
        layout["processes"].update(make_process_panel(state, process_limit))
    layout["health"].update(make_health_panel(data, thresholds))

    return layout
