from __future__ import annotations

import threading

import pytest

from src.util.cancel import Cancelled, CancelToken


def test_a_new_token_is_not_cancelled() -> None:
    token = CancelToken()
    assert token.cancelled is False
    token.raise_if_cancelled()  # must not raise


def test_cancel_is_sticky_and_idempotent() -> None:
    token = CancelToken()
    token.cancel()
    token.cancel()
    assert token.cancelled is True
    with pytest.raises(Cancelled):
        token.raise_if_cancelled()
    with pytest.raises(Cancelled):
        token.raise_if_cancelled()


def test_cancelled_is_a_read_only_property() -> None:
    token = CancelToken()
    with pytest.raises(AttributeError):
        token.cancelled = True  # type: ignore[misc]
    assert token.cancelled is False


def test_tokens_are_independent() -> None:
    first, second = CancelToken(), CancelToken()
    first.cancel()
    assert first.cancelled
    assert not second.cancelled


def test_cancelled_is_a_plain_exception_not_a_base_exception_escape() -> None:
    assert issubclass(Cancelled, Exception)
    assert not issubclass(Cancelled, OSError | ValueError | KeyboardInterrupt)


def test_cancel_from_another_thread_is_seen_by_a_polling_worker() -> None:
    token = CancelToken()
    started = threading.Event()
    outcome: list[str] = []

    def worker() -> None:
        started.set()
        try:
            while True:
                token.raise_if_cancelled()
                threading.Event().wait(0.001)
        except Cancelled:
            outcome.append("cancelled")

    thread = threading.Thread(target=worker)
    thread.start()
    assert started.wait(5)
    token.cancel()
    thread.join(5)
    assert not thread.is_alive()
    assert outcome == ["cancelled"]
