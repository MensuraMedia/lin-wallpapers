"""Shared utilities: the worker-to-UI thread pattern, logging, errors, units."""

from .threads import run_in_worker, shutdown

__all__ = ["run_in_worker", "shutdown"]
