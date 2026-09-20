"""The provider contract and registry (TECHNICAL-CONCEPT §17.1–17.2).

Everything variable about a machine — desktop, locker, greeter, splash system, boot manager — is
a ``SurfaceProvider`` registered here and selected by a runtime probe. M0 ships the contract and
the registry with no implementations; the data types below are deliberately minimal and are
filled out by the milestones that use them (M3 detection, M4 plans, M5 privileged steps).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class Surface(Enum):
    """The five screens."""

    DESKTOP = "desktop"
    LOCK = "lock"
    LOGIN = "login"
    SPLASH = "splash"
    BOOTMENU = "bootmenu"


@dataclass(frozen=True)
class Environment:
    """What a probe may look at. ``root`` is ``/`` on a real machine and a fake root in tests."""

    root: Path = Path("/")
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Detection:
    """Evidence-based detection: never a bare bool, always *why* (§17.1 rule 2)."""

    confidence: float
    evidence: tuple[str, ...] = ()
    reason_code: str | None = None  # from the §15.2 catalogue when confidence is 0

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within 0..1")


@dataclass(frozen=True)
class Capabilities:
    can_apply: bool = False
    needs_root: bool = False
    needs_restart: bool = False
    supports_per_monitor: bool = False
    formats: tuple[str, ...] = ()


@dataclass(frozen=True)
class CurrentState:
    """What is set now, and where that answer came from."""

    image: Path | None
    source: str


@dataclass(frozen=True)
class Step:
    """One planned operation. A step that cannot describe its own undo cannot be planned."""

    op: str
    description: str
    inverse: str
    needs_root: bool = False

    def __post_init__(self) -> None:
        if not self.inverse:
            raise ValueError(f"step {self.op!r} does not describe its own inverse")


@dataclass(frozen=True)
class Result:
    ok: bool
    message: str = ""


@dataclass(frozen=True)
class Verification:
    ok: bool
    checks: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreviewSpec:
    """Geometry and chrome for a surface's mock-up (M3)."""

    width: int
    height: int
    chrome: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SurfaceProvider(Protocol):
    """The contract every provider implements. No GTK, no UI, no user interaction."""

    id: str
    surface: Surface

    def detect(self, env: Environment) -> Detection: ...
    def capabilities(self) -> Capabilities: ...
    def current(self) -> CurrentState | None: ...
    def plan(self, image: Path, options: dict[str, Any]) -> list[Step]: ...
    def apply(self, steps: Sequence[Step], ctx: dict[str, Any]) -> Result: ...
    def verify(self, ctx: dict[str, Any]) -> Verification: ...
    def revert(self, backup: Path) -> Result: ...
    def preview_spec(self) -> PreviewSpec: ...


class RegistryError(Exception):
    """A provider could not be registered."""


class ProviderRegistry:
    """Providers by id, selectable per surface by detection confidence."""

    def __init__(self) -> None:
        self._providers: dict[str, SurfaceProvider] = {}

    def register(self, provider: SurfaceProvider) -> SurfaceProvider:
        if not isinstance(provider, SurfaceProvider):
            raise RegistryError(f"{provider!r} does not implement SurfaceProvider")
        if not isinstance(provider.surface, Surface):
            raise RegistryError(f"{provider.id}: surface must be a Surface")
        if provider.id in self._providers:
            raise RegistryError(f"provider id already registered: {provider.id}")
        self._providers[provider.id] = provider
        return provider

    def get(self, provider_id: str) -> SurfaceProvider:
        return self._providers[provider_id]

    def for_surface(self, surface: Surface) -> list[SurfaceProvider]:
        return [p for p in self._providers.values() if p.surface is surface]

    def select(self, surface: Surface, env: Environment) -> tuple[SurfaceProvider, Detection] | None:
        """The best-detected provider for a surface, or ``None`` when nothing claims it.

        A provider whose ``detect()`` raises disables only itself (§17.1 rule 7).
        """
        best: tuple[SurfaceProvider, Detection] | None = None
        for provider in self.for_surface(surface):
            try:
                detection = provider.detect(env)
            except Exception:
                continue
            if detection.confidence > 0 and (best is None or detection.confidence > best[1].confidence):
                best = (provider, detection)
        return best

    def __iter__(self) -> Iterator[SurfaceProvider]:
        return iter(self._providers.values())

    def __len__(self) -> int:
        return len(self._providers)


registry = ProviderRegistry()
