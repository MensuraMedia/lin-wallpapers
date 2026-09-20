"""``ScanVM`` — one per app: start/cancel a scan and observe its progress (M1 §2.9, §3).

The scan itself runs on a worker thread (``run_in_worker``); the service calls ``on_progress`` there at
``≤ 10 Hz``. This view model coalesces those to the same cap and re-delivers every update through the
injected scheduler, so widgets only ever see the UI thread and only ever see a frozen :class:`ScanState`
— never a ``catalogue`` or ``scanner`` type. Nothing is started on construction: the first run happens
only when a page calls :meth:`start` (first-run consent lives in the page, contract §2.9).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future
from dataclasses import dataclass, replace

from src.catalogue.ingest import ScanProgress, ScanSummary
from src.scanner.displays import Display
from src.util.cancel import CancelToken
from src.util.threads import Scheduler, run_in_worker
from src.viewmodels.services import AppServices

_MIN_INTERVAL = 0.1  # ≤ 10 Hz


@dataclass(frozen=True)
class DisplayInfo:
    """One measured (or declared) display, as a page sees it."""

    name: str
    width: int
    height: int
    scale: float
    primary: bool
    source: str


@dataclass(frozen=True)
class ScanState:
    """The whole observable state of a scan; pages bind their banner to this and nothing else."""

    running: bool = False
    result: str | None = None  # None while running / never run; 'ok'|'cancelled'|'error' when finished
    scan_id: int = 0
    dirs: int = 0
    found: int = 0
    unchanged: int = 0
    probed: int = 0
    ideal: int = 0
    excluded: int = 0
    issues: int = 0
    walk_done: bool = False
    current_dir: str = ""
    displays: tuple[DisplayInfo, ...] = ()
    reason_code: str | None = None  # DISPLAY_NOT_DETECTED when the desktop could not be measured
    reason_remedy: str | None = None


class ScanVM:
    def __init__(self, services: AppServices) -> None:
        self._services = services
        self._scheduler: Scheduler = services.scheduler
        self._observers: list[Callable[[ScanState], None]] = []
        self._state = ScanState()
        self._cancel: CancelToken | None = None
        self._last_emit = 0.0

    # -- observation ------------------------------------------------------------------------------------

    @property
    def state(self) -> ScanState:
        return self._state

    def add_observer(self, cb: Callable[[ScanState], None]) -> Callable[[], None]:
        self._observers.append(cb)

        def remove() -> None:
            if cb in self._observers:
                self._observers.remove(cb)

        return remove

    # -- control ----------------------------------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._state.running

    def start(
        self, root_ids: Sequence[int] | None = None, declared: Sequence[Display] = ()
    ) -> Future[ScanSummary] | None:
        """Begin a scan on a worker thread. A no-op (returns ``None``) while one is already running."""
        if self._state.running:
            return None
        cancel = CancelToken()
        self._cancel = cancel
        self._last_emit = 0.0
        self._deliver(ScanState(running=True))
        wanted = None if root_ids is None else list(root_ids)
        chosen = list(declared)

        def work() -> ScanSummary:
            return self._services.scan.scan(wanted, chosen, self, cancel)

        def done(summary: ScanSummary | None, error: BaseException | None) -> None:
            self._on_finished(summary, error)

        return run_in_worker(work, done, scheduler=self._scheduler)

    def cancel(self) -> None:
        """Ask the running scan to stop; the final state arrives as usual once it unwinds."""
        if self._cancel is not None:
            self._cancel.cancel()

    # -- ScanListener (called on the worker thread) -----------------------------------------------------

    def on_progress(self, p: ScanProgress) -> None:
        now = time.monotonic()
        if now - self._last_emit < _MIN_INTERVAL:
            return
        self._last_emit = now
        state = self._state_from_progress(p)
        self._scheduler(lambda: self._set(state))

    # -- internals --------------------------------------------------------------------------------------

    def _state_from_progress(self, p: ScanProgress) -> ScanState:
        return ScanState(
            running=True,
            result=None,
            scan_id=p.scan_id,
            dirs=p.dirs,
            found=p.found,
            unchanged=p.unchanged,
            probed=p.probed,
            ideal=p.ideal,
            excluded=p.excluded,
            issues=p.issues,
            walk_done=p.walk_done,
            current_dir=p.current_dir,
        )

    def _on_finished(self, summary: ScanSummary | None, error: BaseException | None) -> None:
        if summary is None:
            self._set(replace(self._state, running=False, result="error"))
            self._cancel = None
            return
        p = summary.progress
        reason = summary.detection.reason
        state = ScanState(
            running=False,
            result=summary.result,
            scan_id=summary.scan_id,
            dirs=p.dirs,
            found=p.found,
            unchanged=p.unchanged,
            probed=p.probed,
            ideal=p.ideal,
            excluded=p.excluded,
            issues=p.issues,
            walk_done=p.walk_done,
            current_dir=p.current_dir,
            displays=tuple(
                DisplayInfo(d.name, d.width, d.height, d.scale, d.primary, d.source.value)
                for d in summary.detection.displays
            ),
            reason_code=None if reason is None else reason.code.value,
            reason_remedy=None if reason is None else reason.remedy,
        )
        self._cancel = None
        self._set(state)

    def _deliver(self, state: ScanState) -> None:
        self._scheduler(lambda: self._set(state))

    def _set(self, state: ScanState) -> None:
        self._state = state
        for observer in list(self._observers):
            observer(state)
