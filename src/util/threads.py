"""The worker-to-UI pattern, defined once so no later module invents its own.

``run_in_worker(fn, on_done)`` runs ``fn`` on a pool thread and delivers the outcome on the main
loop. Workers never touch widgets; results cross back through the scheduler (``GLib.idle_add``
under GTK). The scheduler is always injected: the GUI passes ``src.util.glib_loop.glib_scheduler``,
the CLI and the tests pass ``immediate_scheduler`` — so this module never imports ``gi`` and is safe
for the service layers.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, TypeVar

T = TypeVar("T")

Scheduler = Callable[[Callable[[], Any]], Any]
OnDone = Callable[[T | None, BaseException | None], None]

_executor: ThreadPoolExecutor | None = None


def _pool() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="lwp-worker")
    return _executor


def immediate_scheduler(callback: Callable[[], Any]) -> None:
    """Deliver ``callback`` on the calling (worker) thread — for the CLI and tests."""
    callback()


def run_in_worker(
    fn: Callable[[], T],
    on_done: OnDone[T] | None = None,
    *,
    scheduler: Scheduler,
) -> Future[T]:
    """Run ``fn`` off the UI thread; call ``on_done(result, error)`` through ``scheduler``."""

    def _job() -> T:
        try:
            result = fn()
        except BaseException as error:
            if on_done is not None:
                captured = error
                scheduler(lambda: on_done(None, captured))
            raise
        if on_done is not None:
            scheduler(lambda: on_done(result, None))
        return result

    return _pool().submit(_job)


def shutdown(wait: bool = True) -> None:
    """Stop the pool, so closing the app leaves no thread behind."""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=wait, cancel_futures=True)
        _executor = None
