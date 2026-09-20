"""Cooperative cancellation: one token per long-running job, polled by every thread working on it.

Pure stdlib and free of GTK, so the scanner, the catalogue writer and the CLI share it. Imported as
``src.util.cancel`` — it is deliberately not re-exported from ``src.util``.
"""

from __future__ import annotations

import threading


class Cancelled(Exception):
    """Raised by ``CancelToken.raise_if_cancelled()`` once the token has been cancelled."""


class CancelToken:
    """A thread-safe, one-way flag. Once cancelled it stays cancelled; there is no reset."""

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        """Request cancellation. Idempotent; callable from any thread."""
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise Cancelled()
