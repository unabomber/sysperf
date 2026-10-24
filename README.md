# Ubuntu SysPerf CLI

A live system performance dashboard for Ubuntu terminals, styled as a proper
modern dashboard: gradient hero cards with chunky LED-style numbers, a
heat-mapped colour ramp across every bar and graph, and a two-row area chart
for network/disk throughput — not just another `htop` clone.

## Features

- **Hero KPI strip** — big LED-digit readouts for CPU / Memory / Disk / Network, each
  with a gradient progress bar, shown automatically on terminals wide and tall enough
  (about 100×32+); gracefully drops to a detail-only layout on smaller terminals
- A cohesive "Aurora" gradient theme — every bar, sparkline, and border shifts
  smoothly from emerald → cyan → amber → rose → red as a metric gets hotter
- Two-row block area charts for network and disk throughput (roughly double the
  vertical resolution of a single-line sparkline)
- A colour-coded per-core heatmap grid, load averages, and per-core mini bars
- RAM, swap, and root filesystem usage, plus other mounted filesystems sorted by usage
- Per-interface network breakdown when more than one NIC is active
- NVIDIA GPU utilisation/VRAM/temperature/power via `nvidia-smi`, shown automatically when available
- Battery status (percent, charging state, time remaining) on laptops
- CPU temperatures when exposed by Linux sensors
- Top processes with inline gradient CPU/MEM bars, sortable (`s`) and filterable by name (`/`)
- Health/status messages for high load, memory, disk, temperature and low battery
- Configurable warn/critical thresholds (CLI flags or a saved config file)
- One-shot JSON snapshot mode (`--once`) for cron/scripting, and continuous CSV logging (`--log-csv`)
- Fully responsive layout — the header, KPI strip, core grid, and memory panel all
  adapt column counts and truncate gracefully rather than wrapping on narrow terminals
- In-app help overlay (`h`) listing keybindings and active thresholds

## Performance

SysPerf is built to be cheap to leave running. Measured on an 8-core Ubuntu box
(160×45 terminal, 1 s interval, ~450 processes): **~3% of one core**, down from
50–60% in 3.0. How:

- **Event-driven loop** — it sleeps in `select()` until the next sample or a keypress/resize,
  and redraws only when something changed. Paused = zero CPU and zero terminal output.
- **Tiered refresh** — CPU/memory/network/disk I/O refresh every interval; the process table
  every 2 s; sensors every 3 s; mounts every 10 s; process/thread counts every 5 s.
- **Fast process scanner** — reads one `/proc/<pid>/stat` per process instead of going through
  psutil's per-process objects (~5× faster), with psutil as the non-Linux fallback.
- **Streaming GPU stats** — one long-lived `nvidia-smi -l` instead of spawning it every sample
  (each spawn costs ~40 ms of CPU).
- Cached gradient colours/bars and merged style runs, so each frame has fewer segments to
  render and write.

Want it even lighter? `sysperf --interval 2` roughly halves the remaining cost, and
`--no-processes` skips the process scan entirely.

## Install

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
./install.sh
sysperf
```

Or run directly:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m sysperf.main
```

Upgrading an existing install just means re-running `install.sh` — it reinstalls into the same virtualenv.

## Keybindings

| Key | Action |
| --- | --- |
| `q` / `Ctrl+C` | Quit |
| `p` | Pause / resume sampling |
| `r` | Reset graph history |
| `s` | Cycle process sort (CPU → MEM → PID → name) |
| `/` | Filter processes by name (Enter to apply, Esc to clear) |
| `x` | Toggle compact CPU view (hides the per-core grid) |
| `h` | Toggle the help overlay |

## Options

```bash
sysperf --interval 1
sysperf --interval 0.5 --history 60
sysperf --no-processes
sysperf --compact --process-limit 12
```

### Thresholds

Warn/critical thresholds drive both the colour coding and the Health panel:

```bash
sysperf --cpu-warn 60 --cpu-crit 85 --mem-warn 75 --mem-crit 92
```

Full list: `--cpu-warn/--cpu-crit`, `--mem-warn/--mem-crit`, `--swap-warn/--swap-crit`,
`--disk-warn/--disk-crit`, `--temp-warn/--temp-crit`.

### Persisting your defaults

```bash
sysperf --interval 2 --cpu-warn 60 --save-config
```

Saves the effective options to `~/.config/sysperf/config.json` (or `$XDG_CONFIG_HOME/sysperf/config.json`),
which is loaded automatically on every future run. Use `--config PATH` to point at a different file.

### Scripting and logging

```bash
sysperf --once            # print one JSON sample to stdout and exit
sysperf --log-csv metrics.csv   # append a CSV row per sample while the dashboard runs
```

## Notes

- Looks best in a truecolor terminal (GNOME Terminal, Konsole, Alacritty, Windows Terminal, iTerm2, etc.)
  with a font that covers basic emoji/symbols. It still works fine on 256-colour/basic terminals — Rich
  downgrades the gradients automatically — and the KPI hero strip simply hides itself on terminals
  narrower than ~100 columns or shorter than ~32 rows.
- Some hardware temperature sensors may require additional kernel support and are not available on every machine/VM.
- The GPU panel only appears when an NVIDIA GPU and `nvidia-smi` are present; other vendors aren't polled.
- The battery panel only appears on machines that report one (laptops).
