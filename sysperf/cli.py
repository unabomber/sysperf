"""Argument parsing, config merging, and the three run modes (live/--once/--save-config)."""
from __future__ import annotations

import argparse
import json
import sys
import time

from . import __version__
from .collector import SampleState
from .config import default_config_path, load_config, save_config
from .export import snapshot_to_dict
from .thresholds import Thresholds

_THRESHOLD_FLAGS = [
    ("cpu_warn", "--cpu-warn", "CPU warn %% (default: %(default)s)"),
    ("cpu_crit", "--cpu-crit", "CPU critical %% (default: %(default)s)"),
    ("mem_warn", "--mem-warn", "Memory warn %% (default: %(default)s)"),
    ("mem_crit", "--mem-crit", "Memory critical %% (default: %(default)s)"),
    ("swap_warn", "--swap-warn", "Swap warn %% (default: %(default)s)"),
    ("swap_crit", "--swap-crit", "Swap critical %% (default: %(default)s)"),
    ("disk_warn", "--disk-warn", "Disk warn %% (default: %(default)s)"),
    ("disk_crit", "--disk-crit", "Disk critical %% (default: %(default)s)"),
    ("temp_warn", "--temp-warn", "Temperature warn C (default: %(default)s)"),
    ("temp_crit", "--temp-crit", "Temperature critical C (default: %(default)s)"),
]


def build_parser(config: dict) -> argparse.ArgumentParser:
    defaults = Thresholds.from_dict(config.get("thresholds", {}))

    parser = argparse.ArgumentParser(description="Live Ubuntu system performance dashboard")
    parser.add_argument("--version", action="version", version=f"sysperf {__version__}")
    parser.add_argument("--interval", type=float, default=config.get("interval", 1.0), help="sampling interval in seconds (default: %(default)s)")
    parser.add_argument("--history", type=int, default=config.get("history", 60), help="number of samples kept for graphs (default: %(default)s)")
    parser.add_argument("--no-processes", action="store_true", default=config.get("no_processes", False), help="hide the top-processes table")
    parser.add_argument("--compact", action="store_true", default=config.get("compact", False), help="start with the compact CPU view (hide per-core grid)")
    parser.add_argument("--process-limit", type=int, default=config.get("process_limit", 8), help="rows shown in the process table (default: %(default)s)")

    parser.add_argument("--once", action="store_true", help="print a single JSON sample to stdout and exit (for scripting/cron)")
    parser.add_argument("--log-csv", default=config.get("log_csv"), help="append one CSV row per sample to this file while running")

    parser.add_argument("--config", default=None, help=f"path to config file (default: {default_config_path()})")
    parser.add_argument("--save-config", action="store_true", help="persist the effective options (including thresholds) to the config file and exit")

    for field_name, flag, help_text in _THRESHOLD_FLAGS:
        parser.add_argument(flag, type=float, default=getattr(defaults, field_name), help=help_text)

    return parser


def thresholds_from_args(args: argparse.Namespace) -> Thresholds:
    return Thresholds(**{field_name: getattr(args, field_name) for field_name, _, _ in _THRESHOLD_FLAGS})


def validate(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.interval < 0.2:
        parser.error("--interval must be at least 0.2 seconds")
    if args.history < 10:
        parser.error("--history must be at least 10")
    if args.process_limit < 1:
        parser.error("--process-limit must be at least 1")


def run_once(thresholds: Thresholds) -> None:
    state = SampleState(history=1, stream_gpu=False, scan_processes=False)
    # cpu_percent needs one throwaway call to establish a baseline
    import psutil

    psutil.cpu_percent(interval=None, percpu=True)
    time.sleep(0.2)
    data = state.sample()
    snapshot = snapshot_to_dict(data, time.time())
    json.dump(snapshot, sys.stdout, indent=2)
    sys.stdout.write("\n")


def main() -> None:
    config_path_hint = None
    # Peek at --config early so it can influence which config file supplies defaults.
    prelim = argparse.ArgumentParser(add_help=False)
    prelim.add_argument("--config", default=None)
    known, _ = prelim.parse_known_args()
    config_path_hint = known.config
    config = load_config(config_path_hint)

    parser = build_parser(config)
    args = parser.parse_args()
    validate(parser, args)
    thresholds = thresholds_from_args(args)

    if args.save_config:
        payload = {
            "interval": args.interval,
            "history": args.history,
            "no_processes": args.no_processes,
            "compact": args.compact,
            "process_limit": args.process_limit,
            "log_csv": args.log_csv,
            "thresholds": thresholds.as_dict(),
        }
        path = save_config(payload, args.config)
        print(f"Saved config to {path}")
        return

    if args.once:
        run_once(thresholds)
        return

    from .app import run

    run(
        interval=args.interval,
        history=args.history,
        show_processes=not args.no_processes,
        thresholds=thresholds,
        compact=args.compact,
        process_limit=args.process_limit,
        log_csv=args.log_csv,
        config_path=args.config or default_config_path(),
    )
