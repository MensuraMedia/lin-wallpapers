"""Reason codes: the minimal slice of the TECHNICAL-CONCEPT §15.2 catalogue that M1 needs (M6.1 grows it).

Services never return prose. They return a ``Reason`` — a code plus evidence — and this one catalogue
turns it into a sentence, so the GUI, the CLI and the log say the same thing. Every code maps to a
state, a headline, a message template and the evidence keys that template expects; ``render()`` raises
``MissingEvidenceError`` rather than let a ``{placeholder}`` reach the user.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from string import Formatter
from types import MappingProxyType

EVIDENCE_SUMMARY = "evidence"
"""Template field that stands for *all* evidence pairs, joined as ``key: value; key: value``."""


class CapabilityState(StrEnum):
    """The five states of TECHNICAL-CONCEPT §15.1."""

    AVAILABLE = "available"
    NEEDS_AUTHORIZATION = "needs_authorization"
    DEGRADED = "degraded"
    UNSUPPORTED = "unsupported"
    BLOCKED = "blocked"


class ReasonCode(StrEnum):
    DISPLAY_NOT_DETECTED = "DISPLAY_NOT_DETECTED"
    LOADER_MISSING = "LOADER_MISSING"
    VOLUME_OFFLINE = "VOLUME_OFFLINE"


@dataclass(frozen=True)
class Reason:
    """Why something is degraded, unsupported or blocked: a code, ordered evidence pairs, a remedy."""

    code: ReasonCode
    evidence: tuple[tuple[str, str], ...] = ()
    remedy: str = ""


@dataclass(frozen=True)
class ReasonSpec:
    """One catalogue entry. ``evidence_keys`` are the named keys the template needs."""

    code: ReasonCode
    state: CapabilityState
    headline: str
    template: str
    evidence_keys: tuple[str, ...] = ()


class MissingEvidenceError(LookupError):
    """A ``Reason`` lacks evidence its message template needs."""

    def __init__(self, code: ReasonCode, missing: tuple[str, ...]) -> None:
        super().__init__(f"{code.value}: missing evidence {', '.join(missing)}")
        self.code = code
        self.missing = missing


_SPECS: tuple[ReasonSpec, ...] = (
    ReasonSpec(
        ReasonCode.DISPLAY_NOT_DETECTED,
        CapabilityState.DEGRADED,
        "Partly supported",
        "No display could be measured in this session ({evidence}), so images can't be matched to a "
        "screen. Declare one with `--display 1920x1080` or in Settings → Displays.",
    ),
    ReasonSpec(
        ReasonCode.LOADER_MISSING,
        CapabilityState.DEGRADED,
        "Partly supported",
        "This system has no loader for {format}; those images are listed but can't be used.",
        ("format",),
    ),
    ReasonSpec(
        ReasonCode.VOLUME_OFFLINE,
        CapabilityState.BLOCKED,
        "Temporarily unavailable",
        "The drive {label} holding this image isn't connected.",
        ("label",),
    ),
)

CATALOGUE: Mapping[ReasonCode, ReasonSpec] = MappingProxyType({spec.code: spec for spec in _SPECS})


def template_fields(template: str) -> tuple[str, ...]:
    """The distinct ``{field}`` names of a template, in order of first use."""
    seen: dict[str, None] = {}
    for _literal, field, _format_spec, _conversion in Formatter().parse(template):
        if field is not None:
            seen.setdefault(field)
    return tuple(seen)


def spec_for(code: ReasonCode) -> ReasonSpec:
    return CATALOGUE[code]


def render(reason: Reason) -> str:
    """The plain-language message for ``reason``.

    Raises ``MissingEvidenceError`` when a key named by the template is absent, or when the template
    summarises the evidence (``{evidence}``) and there is none. When a key occurs twice in the
    evidence, the first pair wins.
    """
    spec = CATALOGUE[reason.code]
    values: dict[str, str] = {}
    for key, value in reason.evidence:
        values.setdefault(key, value)
    fields = template_fields(spec.template)
    if EVIDENCE_SUMMARY in fields and EVIDENCE_SUMMARY not in values and reason.evidence:
        values[EVIDENCE_SUMMARY] = "; ".join(f"{key}: {value}" for key, value in reason.evidence)
    missing = tuple(field for field in fields if field not in values)
    if missing:
        raise MissingEvidenceError(reason.code, missing)
    return spec.template.format_map(values)
