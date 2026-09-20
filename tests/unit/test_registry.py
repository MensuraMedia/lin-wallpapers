from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from src.apply.registry import (
    Capabilities,
    CurrentState,
    Detection,
    Environment,
    PreviewSpec,
    ProviderRegistry,
    RegistryError,
    Result,
    Step,
    Surface,
    SurfaceProvider,
    Verification,
)


class FakeProvider:
    def __init__(self, id: str, surface: Surface, confidence: float = 1.0, broken: bool = False):
        self.id = id
        self.surface = surface
        self._confidence = confidence
        self._broken = broken

    def detect(self, env: Environment) -> Detection:
        if self._broken:
            raise RuntimeError("probe exploded")
        return Detection(self._confidence, evidence=(f"{env.root}/marker",))

    def capabilities(self) -> Capabilities:
        return Capabilities(can_apply=True)

    def current(self) -> CurrentState | None:
        return None

    def plan(self, image: Path, options: dict[str, Any]) -> list[Step]:
        return [Step("noop", "do nothing", inverse="do nothing")]

    def apply(self, steps: Sequence[Step], ctx: dict[str, Any]) -> Result:
        return Result(True)

    def verify(self, ctx: dict[str, Any]) -> Verification:
        return Verification(True)

    def revert(self, backup: Path) -> Result:
        return Result(True)

    def preview_spec(self) -> PreviewSpec:
        return PreviewSpec(1920, 1080)


def test_protocol_shape() -> None:
    """The contract of TECHNICAL-CONCEPT §17.1: these eight methods, plus id and surface."""
    members = {name for name in vars(SurfaceProvider) if not name.startswith("_")}
    assert {
        "detect",
        "capabilities",
        "current",
        "plan",
        "apply",
        "verify",
        "revert",
        "preview_spec",
    } <= members
    assert isinstance(FakeProvider("x", Surface.DESKTOP), SurfaceProvider)
    assert not isinstance(object(), SurfaceProvider)


def test_five_surfaces() -> None:
    assert {s.value for s in Surface} == {"desktop", "lock", "login", "splash", "bootmenu"}


def test_register_and_lookup() -> None:
    reg = ProviderRegistry()
    provider = reg.register(FakeProvider("desktop_fake", Surface.DESKTOP))
    assert reg.get("desktop_fake") is provider
    assert reg.for_surface(Surface.DESKTOP) == [provider]
    assert reg.for_surface(Surface.SPLASH) == []
    assert len(reg) == 1


def test_rejects_duplicates_and_non_providers() -> None:
    reg = ProviderRegistry()
    reg.register(FakeProvider("a", Surface.LOCK))
    with pytest.raises(RegistryError):
        reg.register(FakeProvider("a", Surface.LOCK))
    with pytest.raises(RegistryError):
        reg.register(object())  # type: ignore[arg-type]


def test_select_prefers_confidence_and_survives_a_broken_provider(fakeroot: Environment) -> None:
    reg = ProviderRegistry()
    reg.register(FakeProvider("weak", Surface.LOGIN, confidence=0.4))
    strong = reg.register(FakeProvider("strong", Surface.LOGIN, confidence=0.9))
    reg.register(FakeProvider("broken", Surface.LOGIN, broken=True))
    reg.register(FakeProvider("absent", Surface.LOGIN, confidence=0.0))

    selected = reg.select(Surface.LOGIN, fakeroot)
    assert selected is not None
    provider, detection = selected
    assert provider is strong
    assert detection.evidence  # detection always says why
    assert reg.select(Surface.BOOTMENU, fakeroot) is None


def test_the_shipped_registry_is_empty_in_m0() -> None:
    from src.apply import registry

    assert len(registry) == 0


def test_step_must_describe_its_inverse() -> None:
    with pytest.raises(ValueError):
        Step("write", "write a file", inverse="")


def test_detection_confidence_is_bounded() -> None:
    with pytest.raises(ValueError):
        Detection(1.5)


def test_fakeroot_skeleton(fakeroot: Environment) -> None:
    for sub in ("etc/lightdm", "etc/default/grub.d", "usr/share/plymouth/themes", "boot/grub"):
        assert (fakeroot.root / sub).is_dir()
