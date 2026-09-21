#!/usr/bin/env python3
"""LinWallpaper privileged apply engine — one surface, careful and reversible.

Runs AS ROOT (via pkexec or ``sudo``) to apply a wallpaper to a surface the
desktop session cannot touch: the login greeter, the Plymouth boot splash, or
the GRUB menu. It reproduces the proven, reversible approach of
``reference/apply-08-screen-wallpaper.sh``:

  * Back up every file it will touch to ``/var/backups/linwallpaper/<ts>/`` and
    record a JSON manifest (path, mode, sha256, prior update-alternatives
    selection) BEFORE writing anything.
  * Idempotent: it renders/derives the new content, compares it byte-for-byte
    with what is already there (``cmp``), and skips writes that would not change
    anything.
  * DROP-INS ONLY: it never edits a package conffile (``/etc/default/grub``,
    ``/etc/lightdm/lightdm.conf``, …). It writes its own files and drop-ins.
  * Reversible: on any error mid-apply it rolls back what it changed, and
    ``--undo`` restores the latest manifest to the prior state.
  * ``--dry-run`` prints the exact ordered plan (every file it would write with
    its mode, every command it would run, the backup path) and exits WITHOUT
    changing anything or needing root. This is the safe, verifiable path.

Interface:
    lw_privileged.py <surface> --image <path> --fit <fit> [--res WxH]
                     [--dry-run] [--undo]
    surface ∈ {login, splash, grub}

Standard-library + Pillow only, so it runs under the system ``python3`` as root
without the LinWallpaper package on ``PYTHONPATH``.
"""

from __future__ import annotations

import argparse
import configparser
import datetime
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --- constants --------------------------------------------------------------
ASSET_DIR = Path(__file__).resolve().parent / "assets"
BACKUP_ROOT = Path(os.environ.get("LW_BACKUP_ROOT", "/var/backups/linwallpaper"))

# login (slick-greeter + lightdm-gtk-greeter drop-in)
BG_DIR = Path("/usr/share/backgrounds/linwallpaper")
BG_JPG = BG_DIR / "wallpaper.jpg"
SLICK_CONF = Path("/etc/lightdm/slick-greeter.conf")
GTK_GREETER_DROPIN = Path(
    "/etc/lightdm/lightdm-gtk-greeter.conf.d/99-linwallpaper.conf"
)

# splash (Plymouth)
THEME_NAME = "linwallpaper"
THEME_DIR = Path("/usr/share/plymouth/themes/linwallpaper")
THEME_PLYMOUTH = THEME_DIR / "linwallpaper.plymouth"
THEME_SCRIPT = THEME_DIR / "linwallpaper.script"
THEME_WALL = THEME_DIR / "wallpaper.png"
DEFAULT_PLYMOUTH = Path("/usr/share/plymouth/themes/default.plymouth")
MINT_THEME = Path("/usr/share/plymouth/themes/mint-logo/mint-logo.plymouth")
THROBBER_DIR = Path("/usr/share/plymouth/themes/mint-logo")
THROBBER_PATTERN = "throbber-*.png"
THROBBER_GLOB = str(THROBBER_DIR / THROBBER_PATTERN)  # for human-readable plan output

# grub (drop-in only)
GRUB_IMG = Path("/boot/grub/linwallpaper-wallpaper.png")
GRUB_DROPIN = Path("/etc/default/grub.d/99-linwallpaper-background.cfg")

# Package conffiles we must NEVER edit (defence in depth: the plan is asserted
# against this list so a bug can never turn into an edited conffile).
FORBIDDEN_PATHS = {
    "/etc/default/grub",
    "/etc/lightdm/lightdm.conf",
    "/etc/lightdm/lightdm-gtk-greeter.conf",
    "/etc/grub.d/00_header",
}

SURFACES = ("login", "splash", "grub")
FITS = ("fill", "fit", "center", "stretch")
DEFAULT_RES = "1920x1080"
PAD = (0, 0, 0)


# --- rendering (Pillow) -----------------------------------------------------
def _render_bytes(image: str, size: tuple[int, int], fit: str, fmt: str) -> bytes:
    """Render ``image`` to exactly ``size`` using ``fit``; return encoded bytes.

    Deterministic for a given input, so a byte-compare against an existing file
    is a valid idempotency check.
    """
    from PIL import Image

    tw, th = size
    src = Image.open(image)
    src.load()
    if src.mode != "RGB":
        src = src.convert("RGB")

    if fit == "stretch":
        out = src.resize((tw, th), Image.LANCZOS)
    elif fit == "fit":
        scale = min(tw / src.width, th / src.height)
        nw, nh = max(1, round(src.width * scale)), max(1, round(src.height * scale))
        resized = src.resize((nw, nh), Image.LANCZOS)
        out = Image.new("RGB", (tw, th), PAD)
        out.paste(resized, ((tw - nw) // 2, (th - nh) // 2))
    elif fit == "center":
        out = Image.new("RGB", (tw, th), PAD)
        out.paste(src, ((tw - src.width) // 2, (th - src.height) // 2))
    else:  # fill (cover): scale up, centre-crop
        scale = max(tw / src.width, th / src.height)
        nw, nh = max(1, round(src.width * scale)), max(1, round(src.height * scale))
        resized = src.resize((nw, nh), Image.LANCZOS)
        left, top = (nw - tw) // 2, (nh - th) // 2
        out = resized.crop((left, top, left + tw, top + th))

    buf = io.BytesIO()
    if fmt == "JPEG":
        out.save(buf, "JPEG", quality=92)
    else:
        out.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _ini_bytes(path: Path, section: str, pairs: list[tuple[str, str]]) -> bytes:
    """Return what ``path`` would contain after setting ``pairs`` in ``section``.

    Reads the existing file (if any) so nothing else in it is disturbed; creates
    the section if missing. Pure — writes nothing.
    """
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.optionxform = str  # preserve key case
    if path.exists():
        cfg.read(path)
    if not cfg.has_section(section):
        cfg.add_section(section)
    for key, value in pairs:
        cfg.set(section, key, value)
    buf = io.StringIO()
    cfg.write(buf, space_around_delimiters=False)
    return buf.getvalue().encode()


# --- steps ------------------------------------------------------------------
@dataclass
class Step:
    """One ordered action. Subclasses describe and execute themselves."""

    def describe(self) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def target_files(self) -> list[tuple[Path, str]]:
        """Files this step writes, as (path, octal-mode). Backed up first."""
        return []

    def execute(self) -> str:
        """Do the work; return a short status ('written' / 'skipped')."""
        return ""


@dataclass
class MkdirStep(Step):
    path: Path
    mode: int = 0o755

    def describe(self) -> str:
        return f"MKDIR  {self.path}  (mode {self.mode:04o})"

    def execute(self) -> str:
        if self.path.is_dir():
            return "exists"
        self.path.mkdir(parents=True, exist_ok=True)
        self.path.chmod(self.mode)
        return "created"


@dataclass
class ContentStep(Step):
    """Write exact bytes to a file, idempotently (skip if identical)."""

    path: Path
    mode: int
    label: str
    _producer: object = None  # callable -> bytes

    def describe(self) -> str:
        return (
            f"WRITE  {self.path}  (mode {self.mode:04o}) — {self.label}"
            "  [idempotent: skip if identical]"
        )

    def target_files(self) -> list[tuple[Path, str]]:
        return [(self.path, f"{self.mode:04o}")]

    def execute(self) -> str:
        data = self._producer()  # type: ignore[operator]
        if self.path.exists() and self.path.read_bytes() == data:
            return "skipped (identical)"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".lw-tmp")
        tmp.write_bytes(data)
        tmp.chmod(self.mode)
        tmp.replace(self.path)
        return "written"


@dataclass
class CopyThrobberStep(Step):
    """Copy the boot throbber frames next to the theme (best-effort, idempotent)."""

    dest_dir: Path

    def describe(self) -> str:
        return (
            f"COPY   {THROBBER_GLOB} -> {self.dest_dir}/  (mode 0644)"
            "  [idempotent; skipped if source theme absent]"
        )

    def target_files(self) -> list[tuple[Path, str]]:
        out: list[tuple[Path, str]] = []
        for src in sorted(THROBBER_DIR.glob(THROBBER_PATTERN)):
            out.append((self.dest_dir / src.name, "0644"))
        return out

    def execute(self) -> str:
        frames = sorted(THROBBER_DIR.glob(THROBBER_PATTERN))
        if not frames:
            return "skipped (no throbber frames)"
        n = 0
        for src in frames:
            dst = self.dest_dir / src.name
            data = src.read_bytes()
            if dst.exists() and dst.read_bytes() == data:
                continue
            dst.write_bytes(data)
            dst.chmod(0o644)
            n += 1
        return f"copied {n} frame(s)"


@dataclass
class RunStep(Step):
    argv: list[str]
    note: str = ""

    def describe(self) -> str:
        extra = f"  — {self.note}" if self.note else ""
        return "RUN    " + " ".join(self.argv) + extra

    def execute(self) -> str:
        subprocess.run(self.argv, check=True)
        return "ran"


# --- plan -------------------------------------------------------------------
@dataclass
class Plan:
    surface: str
    image: str
    fit: str
    res: str
    backup_dir: Path
    steps: list[Step] = field(default_factory=list)
    prior_alternative: str | None = None
    undo_commands: list[list[str]] = field(default_factory=list)

    def all_target_files(self) -> list[tuple[Path, str]]:
        seen: dict[str, str] = {}
        for step in self.steps:
            for path, mode in step.target_files():
                seen[str(path)] = mode
        return [(Path(p), m) for p, m in seen.items()]

    def forbidden(self) -> list[str]:
        touched = {str(p) for p, _ in self.all_target_files()}
        return sorted(touched & FORBIDDEN_PATHS)


def build_plan(surface: str, image: str, fit: str, res: str, backup_dir: Path) -> Plan:
    w, h = (int(v) for v in res.split("x"))
    plan = Plan(surface=surface, image=image, fit=fit, res=res, backup_dir=backup_dir)

    if surface == "login":
        plan.steps.append(MkdirStep(BG_DIR, 0o755))
        plan.steps.append(
            ContentStep(
                BG_JPG, 0o644, f"render {w}x{h} fit={fit} (JPEG)",
                _producer=lambda: _render_bytes(image, (w, h), fit, "JPEG"),
            )
        )
        plan.steps.append(
            ContentStep(
                SLICK_CONF, 0o644,
                "slick-greeter [Greeter] background + draw-user-backgrounds=false"
                " (create file/section if missing)",
                _producer=lambda: _ini_bytes(
                    SLICK_CONF, "Greeter",
                    [("background", str(BG_JPG)), ("draw-user-backgrounds", "false")],
                ),
            )
        )
        plan.steps.append(
            ContentStep(
                GTK_GREETER_DROPIN, 0o644,
                "lightdm-gtk-greeter drop-in [greeter] background"
                " (create file/section if missing)",
                _producer=lambda: _ini_bytes(
                    GTK_GREETER_DROPIN, "greeter", [("background", str(BG_JPG))]
                ),
            )
        )

    elif surface == "splash":
        plan.steps.append(MkdirStep(THEME_DIR, 0o755))
        plan.steps.append(
            ContentStep(
                THEME_PLYMOUTH, 0o644, "Plymouth theme descriptor (bundled asset)",
                _producer=lambda: (ASSET_DIR / "plymouth" / "linwallpaper.plymouth").read_bytes(),
            )
        )
        plan.steps.append(
            ContentStep(
                THEME_SCRIPT, 0o644, "Plymouth theme script (bundled asset)",
                _producer=lambda: (ASSET_DIR / "plymouth" / "linwallpaper.script").read_bytes(),
            )
        )
        plan.steps.append(CopyThrobberStep(THEME_DIR))
        plan.steps.append(
            ContentStep(
                THEME_WALL, 0o644, f"render {w}x{h} fit={fit} (PNG)",
                _producer=lambda: _render_bytes(image, (w, h), fit, "PNG"),
            )
        )
        plan.prior_alternative = _current_alternative()
        plan.steps.append(
            RunStep(
                ["update-alternatives", "--install",
                 str(DEFAULT_PLYMOUTH), "default.plymouth", str(THEME_PLYMOUTH), "150"],
                note="register our theme",
            )
        )
        plan.steps.append(
            RunStep(
                ["update-alternatives", "--set", "default.plymouth", str(THEME_PLYMOUTH)],
                note="select our theme",
            )
        )
        plan.steps.append(
            RunStep(["update-initramfs", "-u", "-k", "all"], note="rebuild initramfs")
        )
        # undo: restore prior alternative (or remove ours), rebuild initramfs.
        if plan.prior_alternative:
            plan.undo_commands.append(
                ["update-alternatives", "--set", "default.plymouth", plan.prior_alternative]
            )
        plan.undo_commands.append(
            ["update-alternatives", "--remove", "default.plymouth", str(THEME_PLYMOUTH)]
        )
        plan.undo_commands.append(["update-initramfs", "-u", "-k", "all"])

    elif surface == "grub":
        plan.steps.append(
            ContentStep(
                GRUB_IMG, 0o644, f"render {w}x{h} fit={fit} (PNG)",
                _producer=lambda: _render_bytes(image, (w, h), fit, "PNG"),
            )
        )
        plan.steps.append(
            ContentStep(
                GRUB_DROPIN, 0o644, "GRUB background drop-in (bundled asset)",
                _producer=lambda: (ASSET_DIR / "grub.d" / "99-linwallpaper-background.cfg").read_bytes(),
            )
        )
        plan.steps.append(RunStep(["update-grub"], note="regenerate grub.cfg"))
        plan.undo_commands.append(["update-grub"])

    else:  # pragma: no cover - argparse restricts this
        raise ValueError(f"unknown surface: {surface}")

    return plan


def _current_alternative() -> str | None:
    """Best-effort: the target ``default.plymouth`` currently points at."""
    try:
        return str(DEFAULT_PLYMOUTH.resolve()) if DEFAULT_PLYMOUTH.exists() else None
    except OSError:
        return None


# --- dry run ----------------------------------------------------------------
def print_plan(plan: Plan) -> None:
    forbidden = plan.forbidden()
    print("LinWallpaper privileged apply — DRY RUN (no changes made, no root needed)")
    print(f"surface:     {plan.surface}")
    print(f"image:       {plan.image}")
    print(f"fit:         {plan.fit}")
    print(f"resolution:  {plan.res}")
    print(f"backup dir:  {plan.backup_dir}")
    print(f"manifest:    {plan.backup_dir / 'manifest.json'}")
    print()
    print("Ordered plan:")
    print(f"   1. BACKUP existing target files into {plan.backup_dir} and record the")
    print("      manifest (path, mode, sha256, prior update-alternatives selection)")
    print("      BEFORE writing anything.")
    for i, step in enumerate(plan.steps, start=2):
        print(f"   {i:>2}. {step.describe()}")
    print()
    print("Files this plan writes (all LinWallpaper-owned files or drop-ins):")
    for path, mode in plan.all_target_files():
        print(f"     - {path}  (mode {mode})")
    if plan.prior_alternative:
        print(f"Prior default.plymouth: {plan.prior_alternative}  (restored on --undo)")
    print(
        "Drop-in only: "
        + ("NO — REFUSING, plan touches a package conffile: " + ", ".join(forbidden)
           if forbidden else "yes — no package conffile is edited")
    )
    print("Reversible: yes — every write is backed up first; --undo restores the manifest.")


# --- apply ------------------------------------------------------------------
def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def write_backups(plan: Plan) -> dict:
    """Back up every existing target file and write the manifest. Runs first."""
    plan.backup_dir.mkdir(parents=True, exist_ok=True)
    plan.backup_dir.chmod(0o700)
    entries = []
    for path, mode in plan.all_target_files():
        entry = {"path": str(path), "mode": mode}
        if path.exists():
            backup_path = Path(str(plan.backup_dir) + str(path))
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup_path)
            entry.update(
                existed=True,
                backup=str(backup_path),
                sha256=_sha256(path),
                orig_mode=oct(path.stat().st_mode & 0o777),
            )
        else:
            entry["existed"] = False
        entries.append(entry)

    manifest = {
        "timestamp": plan.backup_dir.name,
        "surface": plan.surface,
        "image": plan.image,
        "fit": plan.fit,
        "backup_dir": str(plan.backup_dir),
        "prior_alternative": plan.prior_alternative,
        "undo_commands": plan.undo_commands,
        "entries": entries,
    }
    (plan.backup_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def rollback(manifest: dict) -> None:
    """Undo a partial/complete apply from a manifest: restore or remove files."""
    for entry in manifest["entries"]:
        path = Path(entry["path"])
        try:
            if entry.get("existed"):
                shutil.copy2(entry["backup"], path)
                path.chmod(int(entry["orig_mode"], 8))
            else:
                if path.exists():
                    path.unlink()
        except OSError as exc:
            print(f"    ! rollback of {path} failed: {exc}", file=sys.stderr)
    for argv in manifest.get("undo_commands", []):
        try:
            subprocess.run(argv, check=False)
        except OSError as exc:  # pragma: no cover - defensive
            print(f"    ! undo command {argv} failed: {exc}", file=sys.stderr)


def apply(plan: Plan) -> int:
    if os.geteuid() != 0:
        print("This must run as root (via pkexec or sudo). Aborting.", file=sys.stderr)
        return 2
    forbidden = plan.forbidden()
    if forbidden:
        print(
            "REFUSING: plan would touch a package conffile: " + ", ".join(forbidden),
            file=sys.stderr,
        )
        return 3

    print(f"==> Backing up existing files to {plan.backup_dir}")
    manifest = write_backups(plan)
    try:
        for step in plan.steps:
            status = step.execute()
            print(f"    {step.describe().split('  ')[0].strip()} -> {status}")
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"!! error mid-apply: {exc}\n!! rolling back", file=sys.stderr)
        rollback(manifest)
        return 1
    print(f"==> Done. Backup + manifest kept at {plan.backup_dir}")
    print("    Undo any time: lw_privileged.py <surface> --undo")
    return 0


# --- undo -------------------------------------------------------------------
def latest_manifest() -> Path | None:
    if not BACKUP_ROOT.exists():
        return None
    candidates = sorted(
        (d for d in BACKUP_ROOT.iterdir() if (d / "manifest.json").exists()),
        key=lambda d: d.name,
    )
    return (candidates[-1] / "manifest.json") if candidates else None


def undo() -> int:
    if os.geteuid() != 0:
        print("This must run as root (via pkexec or sudo). Aborting.", file=sys.stderr)
        return 2
    manifest_path = latest_manifest()
    if manifest_path is None:
        print("Nothing to undo: no manifest found.", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text())
    print(f"==> Undo from {manifest_path} (surface: {manifest.get('surface')})")
    rollback(manifest)
    print("==> Undo complete.")
    return 0


# --- cli --------------------------------------------------------------------
def _timestamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lw_privileged.py",
        description="Apply one wallpaper surface as root, reversibly.",
    )
    parser.add_argument("surface", choices=SURFACES)
    parser.add_argument("--image")
    parser.add_argument("--fit", choices=FITS, default="fill")
    parser.add_argument("--res", default=DEFAULT_RES)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--undo", action="store_true")
    args = parser.parse_args(argv)

    if args.undo:
        return undo()

    if not args.image:
        parser.error("--image is required (unless --undo)")
    if not args.dry_run and not Path(args.image).is_file():
        parser.error(f"image not found: {args.image}")

    backup_dir = BACKUP_ROOT / _timestamp()
    plan = build_plan(args.surface, args.image, args.fit, args.res, backup_dir)

    if args.dry_run:
        print_plan(plan)
        return 0
    return apply(plan)


if __name__ == "__main__":
    raise SystemExit(main())
