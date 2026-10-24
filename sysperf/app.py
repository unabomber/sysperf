"""The interactive Live dashboard loop and its keybindings.

The loop is event-driven: it sleeps in select() until the next sample is due
or a key/resize arrives, and only redraws when something actually changed.
(The original polled every 80 ms and rebuilt the whole dashboard each time,
which is what made it burn CPU while looking at an unchanged screen.)
"""
from __future__ import annotations

import os
import sys
import time
from typing import List, Optional, Tuple

import psutil
from rich.console import Console
from rich.live import Live

from .collector import SampleState
from .export import CsvLogger
from .panels import build_dashboard
from .thresholds import Thresholds

try:  # POSIX terminal control; absent on Windows (no live keys there)
    import select
    import signal
    import termios
    import tty
    HAVE_TTY = True
except ImportError:  # pragma: no cover
    HAVE_TTY = False

# Keys handled while typing a process-name filter (started with "/").
_FILTER_ENTER = {"\r", "\n"}
_FILTER_ESCAPE = "\x1b"
_FILTER_BACKSPACE = {"\x7f", "\b"}


def parse_keys(chunk: str) -> List[str]:
    """Split a raw terminal read into key presses.

    Arrow/function keys arrive as escape sequences (ESC [ ... final, or
    ESC O final) and must not leak into the filter text; a lone ESC is a real
    Escape press. Anything typed right after a sequence (or pasted) is kept."""
    keys: List[str] = []
    i, n = 0, len(chunk)
    while i < n:
        ch = chunk[i]
        if ch != "\x1b":
            keys.append(ch)
            i += 1
        elif i + 1 >= n:
            keys.append(ch)  # lone ESC
            i += 1
        elif chunk[i + 1] in "[O":
            j = i + 2
            while j < n and not ("@" <= chunk[j] <= "~"):
                j += 1  # skip parameter/intermediate bytes up to the final byte
            i = j + 1
        else:
            i += 2  # Alt+key: swallow the pair
    return keys


class Terminal:
    """Raw-ish keyboard input plus resize notification, with a blocking wait.

    wait(timeout) returns as soon as a key is pressed or the window is
    resized, or after `timeout` seconds (None = wait indefinitely)."""

    def __init__(self) -> None:
        self.fd: Optional[int] = None
        self._saved = None
        self._pipe: Optional[Tuple[int, int]] = None
        self._old_winch = None
        if HAVE_TTY and sys.stdin.isatty():
            try:
                self.fd = sys.stdin.fileno()
                self._saved = termios.tcgetattr(self.fd)
                tty.setcbreak(self.fd)
            except (termios.error, OSError, ValueError):
                self.fd = None
        if HAVE_TTY and hasattr(signal, "SIGWINCH"):
            # Self-pipe so a resize wakes select() immediately.
            r, w = os.pipe()
            os.set_blocking(r, False)
            os.set_blocking(w, False)
            self._pipe = (r, w)
            self._old_winch = signal.signal(signal.SIGWINCH, self._on_winch)

    def _on_winch(self, *_args) -> None:
        try:
            os.write(self._pipe[1], b"x")
        except OSError:
            pass

    def wait(self, timeout: Optional[float]) -> Tuple[List[str], bool]:
        """Block until input/resize/timeout. Returns (keys, resized)."""
        if not HAVE_TTY:
            time.sleep(0.25 if timeout is None else min(timeout, 0.25))
            return [], False

        watch = [fd for fd in (self.fd, self._pipe[0] if self._pipe else None) if fd is not None]
        if not watch:
            time.sleep(1.0 if timeout is None else timeout)
            return [], False

        try:
            ready, _, _ = select.select(watch, [], [], timeout)
        except InterruptedError:
            return [], True
        keys: List[str] = []
        resized = False
        for fd in ready:
            if self._pipe and fd == self._pipe[0]:
                try:
                    os.read(fd, 1024)
                except OSError:
                    pass
                resized = True
            elif fd == self.fd:
                try:
                    chunk = os.read(fd, 64).decode("utf-8", "ignore")
                except OSError:
                    chunk = ""
                keys.extend(parse_keys(chunk))
        return keys, resized

    def close(self) -> None:
        if self._old_winch is not None:
            try:
                signal.signal(signal.SIGWINCH, self._old_winch)
            except (ValueError, OSError):
                pass
        if self._pipe:
            for fd in self._pipe:
                try:
                    os.close(fd)
                except OSError:
                    pass
        if self.fd is not None and self._saved is not None:
            try:
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self._saved)
            except (termios.error, OSError):
                pass


def run(
    interval: float,
    history: int,
    show_processes: bool,
    thresholds: Optional[Thresholds] = None,
    compact: bool = False,
    process_limit: int = 8,
    log_csv: Optional[str] = None,
    config_path: Optional[str] = None,
) -> None:
    thresholds = thresholds or Thresholds()
    console = Console()
    state = SampleState(history=history, interval=interval, scan_processes=show_processes)
    paused = False
    filter_mode = False
    show_help = False

    csv_logger = CsvLogger(log_csv) if log_csv else None
    term = Terminal()
    data = None

    def render():
        size = console.size
        return build_dashboard(
            data, state, interval, show_processes, paused, thresholds,
            compact=compact, filter_mode=filter_mode, show_help=show_help,
            config_path=config_path, width=size.width, height=size.height,
            process_limit=process_limit,
        )

    try:
        # Prime the CPU counters, then let a moment pass so the first reading
        # is a real measurement rather than ~0.
        psutil.cpu_percent(interval=None, percpu=True)
        time.sleep(0.15)
        data = state.sample()

        with Live(render(), console=console, screen=True, auto_refresh=False) as live:
            next_sample = time.monotonic() + interval
            if csv_logger:
                csv_logger.log(data, time.time())
            dirty = False
            quit_requested = False

            while not quit_requested:
                now = time.monotonic()
                if not paused and now >= next_sample:
                    data = state.sample()
                    next_sample = now + interval
                    dirty = True
                    if csv_logger:
                        csv_logger.log(data, time.time())

                if dirty:
                    live.update(render(), refresh=True)
                    dirty = False

                timeout = None if paused else max(0.0, next_sample - time.monotonic())
                keys, resized = term.wait(timeout)
                if resized:
                    dirty = True

                for key in keys:
                    changed = True
                    if filter_mode:
                        if key in _FILTER_ENTER:
                            filter_mode = False
                        elif key == _FILTER_ESCAPE:
                            filter_mode = False
                            state.filter_text = ""
                        elif key in _FILTER_BACKSPACE:
                            state.filter_text = state.filter_text[:-1]
                        elif key.isprintable():
                            state.filter_text += key
                        dirty = dirty or changed
                        continue

                    lower = key.lower()
                    if lower == "q":
                        quit_requested = True
                        break
                    elif lower == "p":
                        paused = not paused
                        if not paused:
                            next_sample = 0.0  # resume with a fresh sample right away
                    elif lower == "r":
                        state.reset()
                    elif lower == "s":
                        state.cycle_sort()
                    elif key == "/":
                        filter_mode = True
                        state.filter_text = ""
                    elif lower == "x":
                        compact = not compact
                    elif lower == "h":
                        show_help = not show_help
                    else:
                        changed = False  # unbound key: nothing to redraw
                    dirty = dirty or changed
    except KeyboardInterrupt:
        pass
    finally:
        term.close()
        state.close()
        if csv_logger:
            csv_logger.close()
