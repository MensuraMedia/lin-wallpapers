from __future__ import annotations

import dataclasses
import re

import pytest

from src.capability.reasons import (
    CATALOGUE,
    EVIDENCE_SUMMARY,
    CapabilityState,
    MissingEvidenceError,
    Reason,
    ReasonCode,
    ReasonSpec,
    render,
    spec_for,
    template_fields,
)

PLACEHOLDER = re.compile(r"[{}]")


def _full_evidence(spec: ReasonSpec) -> tuple[tuple[str, str], ...]:
    keys = spec.evidence_keys or ("probe",)
    return tuple((key, f"<{key}>") for key in keys)


def test_the_minimal_catalogue_has_exactly_the_m1_codes() -> None:
    assert {code.name for code in ReasonCode} == {"DISPLAY_NOT_DETECTED", "LOADER_MISSING", "VOLUME_OFFLINE"}
    assert all(code.value == code.name for code in ReasonCode)


@pytest.mark.parametrize("code", list(ReasonCode))
def test_every_code_has_a_complete_entry(code: ReasonCode) -> None:
    spec = spec_for(code)
    assert spec is CATALOGUE[code]
    assert spec.code is code
    assert isinstance(spec.state, CapabilityState)
    assert (
        spec.state is not CapabilityState.AVAILABLE
    )  # a reason explains why something is *not* plain available
    assert spec.headline.strip()
    assert spec.template.strip()


@pytest.mark.parametrize("code", list(ReasonCode))
def test_template_fields_and_declared_evidence_keys_agree(code: ReasonCode) -> None:
    spec = spec_for(code)
    named = tuple(field for field in template_fields(spec.template) if field != EVIDENCE_SUMMARY)
    assert set(named) == set(spec.evidence_keys)
    assert len(set(spec.evidence_keys)) == len(spec.evidence_keys)
    assert all(field.isidentifier() for field in template_fields(spec.template))


def test_states_follow_the_concept_table() -> None:
    assert spec_for(ReasonCode.DISPLAY_NOT_DETECTED).state is CapabilityState.DEGRADED
    assert spec_for(ReasonCode.LOADER_MISSING).state is CapabilityState.DEGRADED
    assert spec_for(ReasonCode.VOLUME_OFFLINE).state is CapabilityState.BLOCKED


@pytest.mark.parametrize("code", list(ReasonCode))
def test_render_with_full_evidence_leaves_no_placeholder(code: ReasonCode) -> None:
    spec = spec_for(code)
    text = render(Reason(code, _full_evidence(spec)))
    assert not PLACEHOLDER.search(text)
    for _key, value in _full_evidence(spec):
        assert value in text


@pytest.mark.parametrize("code", list(ReasonCode))
def test_render_without_evidence_raises_instead_of_leaking_a_placeholder(code: ReasonCode) -> None:
    with pytest.raises(MissingEvidenceError) as caught:
        render(Reason(code))
    assert caught.value.code is code
    assert caught.value.missing
    assert code.value in str(caught.value)


def test_render_names_the_missing_key() -> None:
    with pytest.raises(MissingEvidenceError) as caught:
        render(Reason(ReasonCode.LOADER_MISSING, (("fromat", "AVIF"),)))
    assert caught.value.missing == ("format",)


def test_display_not_detected_summarises_every_probe_attempt_in_order() -> None:
    reason = Reason(
        ReasonCode.DISPLAY_NOT_DETECTED,
        (("xrandr", "binary not found"), ("drm", "no connected connector")),
        remedy="--display WxH",
    )
    text = render(reason)
    assert "(xrandr: binary not found; drm: no connected connector)" in text
    assert "--display" in text


def test_evidence_values_are_inserted_literally() -> None:
    text = render(Reason(ReasonCode.VOLUME_OFFLINE, (("label", "{format} {0} %s"),)))
    assert "{format} {0} %s" in text


def test_extra_evidence_is_allowed_and_first_duplicate_wins() -> None:
    text = render(
        Reason(ReasonCode.LOADER_MISSING, (("format", "AVIF"), ("format", "HEIF"), ("pillow", "10.2")))
    )
    assert "AVIF" in text
    assert "HEIF" not in text


def test_reason_is_frozen_hashable_and_defaults_are_empty() -> None:
    reason = Reason(ReasonCode.VOLUME_OFFLINE)
    assert reason.evidence == ()
    assert reason.remedy == ""
    assert hash(reason) == hash(Reason(ReasonCode.VOLUME_OFFLINE))
    with pytest.raises(dataclasses.FrozenInstanceError):
        reason.remedy = "plug it in"  # type: ignore[misc]


def test_the_catalogue_is_read_only() -> None:
    with pytest.raises(TypeError):
        CATALOGUE[ReasonCode.VOLUME_OFFLINE] = spec_for(ReasonCode.LOADER_MISSING)  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec_for(ReasonCode.VOLUME_OFFLINE).template = ""  # type: ignore[misc]
