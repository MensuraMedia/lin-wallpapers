"""Safety tests for the privileged apply engine — dry-run only, no root.

These never touch the real system: they exercise plan construction, the
idempotent write step against a tmp file, and the standalone script's
``--dry-run`` output via subprocess.
"""

from __future__ import annotations

import subprocess
import sys

import pytest
from PIL import Image

from linwallpaper.privileged import HELPER
from linwallpaper.privileged import lw_privileged as lw


@pytest.fixture()
def sample(tmp_path):
    p = tmp_path / "sample.png"
    Image.new("RGB", (2000, 1200), (30, 90, 160)).save(p)
    return str(p)


@pytest.mark.parametrize("surface", lw.SURFACES)
def test_plan_is_nonempty_backs_up_and_is_dropin_only(surface, sample, tmp_path):
    plan = lw.build_plan(surface, sample, "fill", "1920x1080", tmp_path / "backup")
    assert plan.steps, "plan must not be empty"

    # No package conffile is ever a target.
    assert plan.forbidden() == []
    targets = {str(p) for p, _ in plan.all_target_files()}
    assert targets, "plan must write at least one file"
    for forbidden in lw.FORBIDDEN_PATHS:
        assert forbidden not in targets

    # The printed plan mentions a backup step + the drop-in-only guarantee.
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        lw.print_plan(plan)
    text = buf.getvalue()
    assert "BACKUP" in text
    assert "Drop-in only: yes" in text


@pytest.mark.parametrize(
    "surface,expect_target,expect_format",
    [
        ("login", "/usr/share/backgrounds/linwallpaper/wallpaper.jpg", "JPEG"),
        ("splash", "/usr/share/plymouth/themes/linwallpaper/wallpaper.png", "PNG"),
        ("grub", "/boot/grub/linwallpaper-wallpaper.png", "PNG"),
    ],
)
def test_render_target_per_surface(surface, expect_target, expect_format, sample, tmp_path):
    plan = lw.build_plan(surface, sample, "fill", "1920x1080", tmp_path / "b")
    targets = {str(p) for p, _ in plan.all_target_files()}
    assert expect_target in targets


@pytest.mark.parametrize("fit", lw.FITS)
def test_render_bytes_exact_size_and_format(fit, sample):
    import io

    data = lw._render_bytes(sample, (1920, 1080), fit, "PNG")
    im = Image.open(io.BytesIO(data))
    assert im.size == (1920, 1080)
    assert im.format == "PNG"

    jpg = lw._render_bytes(sample, (800, 600), fit, "JPEG")
    im2 = Image.open(io.BytesIO(jpg))
    assert im2.size == (800, 600)
    assert im2.format == "JPEG"


def test_content_step_is_idempotent(tmp_path):
    dest = tmp_path / "out.bin"
    step = lw.ContentStep(dest, 0o644, "test", _producer=lambda: b"hello world")
    assert step.execute() == "written"
    assert dest.read_bytes() == b"hello world"
    # Second run with identical content must skip (the cmp-before-write rule).
    assert step.execute() == "skipped (identical)"


def test_ini_bytes_creates_section_and_preserves_existing(tmp_path):
    conf = tmp_path / "greeter.conf"
    conf.write_text("[Greeter]\ntheme-name=Foo\n")
    out = lw._ini_bytes(conf, "Greeter", [("background", "/x.jpg")]).decode()
    assert "theme-name=Foo" in out  # untouched key preserved
    assert "background=/x.jpg" in out


@pytest.mark.parametrize("surface", lw.SURFACES)
def test_dry_run_subprocess_makes_no_changes(surface, sample):
    res = subprocess.run(
        [sys.executable, str(HELPER), surface, "--image", sample, "--fit", "fill", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert res.returncode == 0, res.stderr
    out = res.stdout
    assert "DRY RUN" in out
    assert "BACKUP" in out
    assert "Drop-in only: yes" in out
    # None of the forbidden conffiles appear as a written target.
    assert "/etc/default/grub  (mode" not in out


def test_undo_with_no_manifest_is_safe(monkeypatch, tmp_path):
    # Point the backup root at an empty dir: undo must report nothing to do,
    # not crash. (geteuid is faked to 0 so we reach the manifest lookup.)
    monkeypatch.setattr(lw, "BACKUP_ROOT", tmp_path / "empty")
    monkeypatch.setattr(lw.os, "geteuid", lambda: 0)
    assert lw.undo() == 1
