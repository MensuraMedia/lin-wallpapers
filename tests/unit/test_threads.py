from __future__ import annotations

import pytest

from src.util import threads


def test_result_is_delivered_through_the_scheduler() -> None:
    seen: list[tuple[object, object]] = []
    future = threads.run_in_worker(
        lambda: 6 * 7,
        lambda result, error: seen.append((result, error)),
        scheduler=threads.immediate_scheduler,
    )
    assert future.result(timeout=5) == 42
    assert seen == [(42, None)]


def test_errors_are_delivered_not_lost() -> None:
    seen: list[BaseException | None] = []

    def boom() -> int:
        raise ValueError("nope")

    future = threads.run_in_worker(
        boom, lambda _r, error: seen.append(error), scheduler=threads.immediate_scheduler
    )
    with pytest.raises(ValueError):
        future.result(timeout=5)
    assert isinstance(seen[0], ValueError)


def test_shutdown_leaves_no_pool() -> None:
    threads.run_in_worker(lambda: None, scheduler=threads.immediate_scheduler).result(timeout=5)
    threads.shutdown()
    assert threads._executor is None
