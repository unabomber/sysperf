"""Thin entry point kept for backwards compatibility.

The implementation lives in cli.py/app.py/collector.py/panels.py; this module
just exposes `main()` so `python -m sysperf.main` and the `sysperf` console
script (sysperf.main:main) keep working.
"""
from __future__ import annotations

from .cli import main

__all__ = ["main"]

if __name__ == "__main__":
    main()
