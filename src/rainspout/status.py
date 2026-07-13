"""Live run status: the single in-place line `spout run` redraws.

While a run executes, its state — items done, the current work item, the
stage's own status line and progress — is drawn as **one line at the bottom
of the terminal that launched the run**, rewritten in place (carriage
return, no scrolling). The mechanism is event-driven: every `set_status` /
`set_progress` call a stage makes is an execution point inside the running
process, and the base class forwards it here; boundary events (plan
computed, stage started, work item finished, run finished) always redraw,
while the high-frequency stage ticks redraw at most once per
``min_interval`` seconds.

The line is drawn on stderr so stdout stays clean for piping, and it is
toggled by ``spout run --live/--no-live`` (default: on only when stderr is
an interactive terminal). Drawing is strictly best-effort — a display
problem must never fail science — so write errors are swallowed.
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from typing import TextIO


class LiveStatus:
    """Redraws the run's state as one in-place terminal line.

    Permanent output (the plan line, per-work-item results) is printed by
    the CLI's notify callback; call :meth:`clear` first so those lines never
    collide with the live one. :meth:`finished` clears the line for good —
    the CLI prints its own final summary.
    """

    def __init__(
        self,
        stream: TextIO,
        *,
        min_interval: float = 0.1,
        clock: Callable[[], float] = time.monotonic,
        width: int | None = None,
    ) -> None:
        self._stream = stream
        self._min_interval = min_interval
        self._clock = clock
        self._width = width
        self._last_draw: float | None = None
        self._drawn_len = 0
        # run state, accumulated from driver/runner events
        self._cycle = 0
        self._to_run = 0
        self._cycle_done = 0
        self._failed = 0
        self._polling = False
        self._current: tuple[str, str] | None = None  # (cell_id, stage)
        self._status_line = ""
        self._progress: float | None = None

    # -- events from the driver ------------------------------------------------

    def plan(self, *, cycle: int, to_run: int, done: int, failed: int, missing: int) -> None:
        self._cycle = cycle
        self._to_run = to_run
        self._cycle_done = 0
        self._polling = False
        self._draw(force=True)

    def item_finished(self, status: str) -> None:
        self._cycle_done += 1
        if status != "succeeded":
            self._failed += 1
        self._current = None
        self._status_line = ""
        self._progress = None
        self._draw(force=True)

    def polling(self, cycle: int) -> None:
        self._cycle = cycle
        self._polling = True
        self._current = None
        self._draw(force=True)

    def finished(self, *, stopped: bool) -> None:
        self.clear()

    # -- events from the runner / the stage's own reporting calls ---------------

    def stage_started(self, cell_id: str, instance: str) -> None:
        self._polling = False
        self._current = (cell_id, instance)
        self._status_line = ""
        self._progress = None
        self._draw(force=True)

    def stage_tick(self, status_line: str, progress: float | None) -> None:
        if self._current is None:  # a tick outside a work item: nothing to attach it to
            return
        self._status_line = status_line
        self._progress = progress
        self._draw()

    # -- the drawing -------------------------------------------------------------

    def clear(self) -> None:
        """Blank the live line so a permanent line can print in its place."""
        if self._drawn_len == 0:
            return
        try:
            self._stream.write("\r" + " " * self._drawn_len + "\r")
            self._stream.flush()
        except OSError:
            pass
        self._drawn_len = 0

    def _compose(self) -> str:
        if self._polling:
            return f"cycle {self._cycle} drained — polling…"
        parts = [f"{self._cycle_done}/{self._to_run}"]
        if self._failed:
            parts.append(f"{self._failed} failed")
        if self._current is not None:
            cell_id, stage = self._current
            now = f"[{cell_id}] {stage}"
            if self._status_line:
                now += f" — {self._status_line}"
            if self._progress is not None:
                now += f" {self._progress:.0%}"
            parts.append(now)
        return " · ".join(parts)

    def _draw(self, force: bool = False) -> None:
        now = self._clock()
        if (
            not force
            and self._last_draw is not None
            and now - self._last_draw < self._min_interval
        ):
            return
        width = self._width or shutil.get_terminal_size().columns
        line = self._compose()[: max(1, width - 1)]
        # pad over whatever the previous, possibly longer, line left behind
        padded = line + " " * max(0, self._drawn_len - len(line))
        try:
            self._stream.write("\r" + padded)
            self._stream.flush()
        except OSError:
            # best-effort by contract: a display problem never fails science
            return
        self._drawn_len = len(line)
        self._last_draw = now


ReportHook = Callable[[str, "float | None"], None]


def make_stage_hook(reporter: LiveStatus) -> ReportHook:
    """The callable the runner attaches to a stage for the duration of run()."""

    def hook(status_line: str, progress: float | None) -> None:
        reporter.stage_tick(status_line, progress)

    return hook
