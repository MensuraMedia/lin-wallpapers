"""Shared fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.apply.registry import Environment

FAKEROOTS = Path(__file__).parent / "fakeroot"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def fakeroot(tmp_path: Path, request: pytest.FixtureRequest) -> Environment:
    """A writable copy of a fake root, as the ``Environment`` a provider probes.

    ``@pytest.mark.parametrize("fakeroot", ["mint-cinnamon"], indirect=True)`` selects a shape;
    the default is the empty ``base`` skeleton.
    """
    shape = getattr(request, "param", "base")
    root = tmp_path / "root"
    shutil.copytree(FAKEROOTS / shape, root)
    return Environment(root=root, env={})
