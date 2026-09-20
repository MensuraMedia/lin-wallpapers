"""Scan roots: where a walk may *start* (TECHNICAL-CONCEPT §5, milestones M1.1, contract §2.6).

Three sources propose roots — XDG picture folders, system wallpaper folders, mounted volumes — and each
proposal says whether it is on by default and, when it is not, **why**. A network filesystem is proposed
switched off with its reason; it is never dropped silently. Exclusions are not decided here (``exclude.py``).

Everything that touches the system is injected: the mount table comes from ``findmnt`` through a ``Runner``
(or straight from JSON text), the home directory and the filesystem root are parameters, and no environment
variable is read. No udisks2, no inotify (accepted deferrals): mounts are read when a scan starts.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from src.scanner.displays import Runner, default_runner

__all__ = [
    "FINDMNT_ARGV",
    "LOCAL_FILESYSTEMS",
    "Mount",
    "MountTable",
    "RootKind",
    "RootProposal",
    "ScanSource",
    "SystemSource",
    "VolumeSource",
    "XdgSource",
    "default_sources",
    "is_network_fstype",
    "load_mounts",
    "parse_findmnt",
    "parse_user_dirs",
    "propose_all",
]

FINDMNT_ARGV: tuple[str, ...] = ("findmnt", "--json", "-o", "TARGET,SOURCE,FSTYPE,UUID,LABEL,OPTIONS")
_FINDMNT_TIMEOUT = 5.0
_MAX_MOUNTS = 4096
_MAX_DEPTH = 64

LOCAL_FILESYSTEMS = frozenset({"ext4", "btrfs", "xfs", "vfat", "exfat", "ntfs3", "ntfs", "fuseblk", "f2fs"})
_UNSTABLE_INODES = frozenset({"vfat", "msdos", "exfat", "ntfs", "ntfs3", "fuseblk"})
# Beyond the contract's literal list (nfs*, cifs, smb3, sshfs, fuse.*): smbfs, fuse (the bare fstype, as
# opposed to a fuse.* helper), 9p, ceph, glusterfs, afs, davfs, ncpfs and lustre are treated as network too
# (ruling R3) — every one of them behaves like a network mount (latency, drops, no stable inode guarantees),
# so a root there is proposed off by default with a "network filesystem (<fstype>)" reason, never dropped.
_NETWORK_EXACT = frozenset(
    {"cifs", "smb3", "smbfs", "sshfs", "fuse", "9p", "ceph", "glusterfs", "afs", "davfs", "ncpfs", "lustre"}
)
_REMOVABLE_PARENTS = ("/media", "/run/media")


class RootKind(StrEnum):
    XDG = "xdg"
    SYSTEM = "system"
    VOLUME = "volume"
    USER = "user"


@dataclass(frozen=True)
class Mount:
    target: str
    source: str
    fstype: str
    uuid: str | None
    label: str | None
    removable: bool  # heuristic: mounted beneath /media or /run/media (findmnt does not report RM)
    network: bool
    stable_inodes: bool

    # ``removable`` (ruling R2): ``target`` comes straight from ``findmnt``, which always reports the real,
    # absolute mount point of this machine — never something relative to the injected scan ``root`` (that
    # ``root`` only bounds where *sources* look for existing directories, e.g. in tests). So testing
    # ``target`` against the real ``/media``/``/run/media`` prefixes is intentional, not a root-independence
    # bug, and needs no ``root`` parameter threaded through.


@dataclass(frozen=True)
class RootProposal:
    path: str
    kind: RootKind
    volume_id: str | None
    default_on: bool
    reason: str | None  # why it is off by default, e.g. "network filesystem (nfs4)"


class ScanSource(Protocol):
    def propose(self) -> list[RootProposal]: ...


# ── pure parsers ─────────────────────────────────────────────────────────────────────────────────────────


def is_network_fstype(fstype: str, options: str = "") -> bool:
    """``nfs*``, ``cifs``, ``smb3``, ``sshfs``, every ``fuse.*`` helper, or anything mounted ``_netdev``."""
    kind = fstype.strip().lower()
    if kind.startswith("nfs") or kind.startswith("fuse.") or kind in _NETWORK_EXACT:
        return True
    return "_netdev" in options.split(",")


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value and "\x00" not in value else None


def _clean_target(target: str) -> str | None:
    if not target.startswith("/"):
        return None
    try:
        target.encode("utf-8")
    except UnicodeEncodeError:
        return None
    stripped = target.rstrip("/")
    return stripped or "/"


def _is_beneath(path: str, parent: str) -> bool:
    return path.startswith(parent.rstrip("/") + "/")


def _mount_from(node: dict[str, object]) -> Mount | None:
    raw_target = _text(node.get("target"))
    fstype = _text(node.get("fstype"))
    if raw_target is None or fstype is None:
        return None
    target = _clean_target(raw_target)
    if target is None:
        return None
    options = _text(node.get("options")) or ""
    kind = fstype.strip().lower()
    return Mount(
        target=target,
        source=_text(node.get("source")) or "",
        fstype=kind,
        uuid=_text(node.get("uuid")),
        label=_text(node.get("label")),
        removable=any(_is_beneath(target, parent) for parent in _REMOVABLE_PARENTS),
        network=is_network_fstype(kind, options),
        stable_inodes=kind not in _UNSTABLE_INODES,
    )


def parse_findmnt(json_text: str) -> list[Mount]:
    """``findmnt --json -o TARGET,SOURCE,FSTYPE,UUID,LABEL,OPTIONS`` → mounts, in mount order.

    Nested ``children`` are flattened depth-first. Garbage in, empty list out: malformed JSON, a wrong shape
    or an entry without a usable target or type is skipped, never raised.
    """
    try:
        document = json.loads(json_text)
    except (ValueError, RecursionError):
        return []
    if not isinstance(document, dict):
        return []
    top = document.get("filesystems")
    if not isinstance(top, list):
        return []
    mounts: list[Mount] = []
    stack: list[tuple[object, int]] = [(node, 0) for node in reversed(top)]
    while stack and len(mounts) < _MAX_MOUNTS:
        node, depth = stack.pop()
        if not isinstance(node, dict):
            continue
        mount = _mount_from(node)
        if mount is not None:
            mounts.append(mount)
        children = node.get("children")
        if isinstance(children, list) and depth < _MAX_DEPTH:
            stack.extend((child, depth + 1) for child in reversed(children))
    return mounts


_USER_DIR_LINE = re.compile(r'^\s*XDG_PICTURES_DIR\s*=\s*"(.*)"\s*$')


def parse_user_dirs(text: str, home: str) -> str | None:
    """The PICTURES folder named by ``~/.config/user-dirs.dirs``; ``None`` when absent or disabled.

    The format allows exactly ``"$HOME/relative"`` and ``"/absolute"``. A value equal to the home directory
    itself means "disabled" (xdg-user-dirs). The last assignment wins, as it does in the shell.
    """
    home = home.rstrip("/") or "/"
    found: str | None = None
    for line in text.splitlines():
        matched = _USER_DIR_LINE.match(line)
        if matched is None:
            continue
        value = re.sub(r"\\(.)", r"\1", matched.group(1))
        if value == "$HOME" or value.startswith("$HOME/"):
            value = home + value[len("$HOME") :]
        if not value.startswith("/") or "\x00" in value:
            found = None
            continue
        value = os.path.normpath(value)
        found = None if value == home else value
    return found


# ── mount table ──────────────────────────────────────────────────────────────────────────────────────────


class MountTable:
    """The mounts of one moment. Later entries win for the same target (an over-mount hides what is below)."""

    def __init__(self, mounts: Iterable[Mount] = ()) -> None:
        self._mounts: tuple[Mount, ...] = tuple(mounts)
        self._by_target: dict[str, Mount] = {mount.target: mount for mount in self._mounts}

    @property
    def mounts(self) -> tuple[Mount, ...]:
        return self._mounts

    def __len__(self) -> int:
        return len(self._mounts)

    def mount_for(self, path: str) -> Mount | None:
        """The mount holding ``path`` (longest target that is ``path`` or an ancestor); lexical, no I/O."""
        if not path.startswith("/"):
            return None
        probe = os.path.normpath(path)
        if probe.startswith("//"):
            probe = probe[1:]
        while True:
            mount = self._by_target.get(probe)
            if mount is not None:
                return mount
            if probe == "/":
                return None
            probe = probe.rsplit("/", 1)[0] or "/"

    def by_uuid(self, uuid: str) -> Mount | None:
        """The (last) mount of a volume: how a drive remounted elsewhere is found again."""
        found: Mount | None = None
        for mount in self._mounts:
            if mount.uuid == uuid:
                found = mount
        return found

    def off_reason(self, path: str) -> str | None:
        """Why a root at ``path`` must not be scanned by default; ``None`` when nothing speaks against it."""
        mount = self.mount_for(path)
        if mount is not None and mount.network:
            return f"network filesystem ({mount.fstype})"
        return None


def load_mounts(run: Runner = default_runner) -> MountTable:
    """Ask ``findmnt``. No binary, a failure or a timeout gives an empty table — volumes are then simply
    not proposed, and the walker still never crosses a mount boundary (it compares ``st_dev``)."""
    text = run(FINDMNT_ARGV, _FINDMNT_TIMEOUT)
    return MountTable(parse_findmnt(text) if text else ())


# ── sources ──────────────────────────────────────────────────────────────────────────────────────────────


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _usable(path: Path) -> str | None:
    text = str(path)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return None
    return text if _is_dir(path) else None


def _proposal(path: str, kind: RootKind, mounts: MountTable, default_on: bool) -> RootProposal:
    mount = mounts.mount_for(path)
    reason = mounts.off_reason(path)
    return RootProposal(
        path=path,
        kind=kind,
        volume_id=mount.uuid if mount is not None else None,
        default_on=default_on and reason is None,
        reason=reason,
    )


def _without_nested(paths: Sequence[str]) -> list[str]:
    """Drop duplicates and folders that lie inside another proposed folder (that walk reaches them anyway)."""
    kept: list[str] = []
    for path in paths:
        if path in kept or any(_is_beneath(path, other) for other in paths if other != path):
            continue
        kept.append(path)
    return kept


class XdgSource:
    """``XDG_PICTURES_DIR`` (from ``<home>/.config/user-dirs.dirs``, else ``~/Pictures``), ``~/Wallpapers``,
    ``~/Pictures/wallpapers`` — existing directories only."""

    def __init__(self, home: Path, mounts: MountTable) -> None:
        self._home = home
        self._mounts = mounts

    def _pictures(self) -> Path:
        try:
            raw = (self._home / ".config" / "user-dirs.dirs").read_bytes()[:65536]
        except OSError:
            return self._home / "Pictures"
        named = parse_user_dirs(raw.decode("utf-8", errors="replace"), str(self._home))
        return Path(named) if named is not None else self._home / "Pictures"

    def propose(self) -> list[RootProposal]:
        wanted = [self._pictures(), self._home / "Wallpapers", self._home / "Pictures" / "wallpapers"]
        existing = [text for text in (_usable(path) for path in wanted) if text is not None]
        return [_proposal(path, RootKind.XDG, self._mounts, True) for path in _without_nested(existing)]


class SystemSource:
    """``/usr/share/backgrounds``, ``/usr/share/wallpapers`` (beneath ``root``) and
    ``~/.local/share/backgrounds``."""

    def __init__(self, home: Path, root: Path, mounts: MountTable) -> None:
        self._home = home
        self._root = root
        self._mounts = mounts

    def propose(self) -> list[RootProposal]:
        wanted = [
            self._root / "usr" / "share" / "backgrounds",
            self._root / "usr" / "share" / "wallpapers",
            self._home / ".local" / "share" / "backgrounds",
        ]
        existing = [text for text in (_usable(path) for path in wanted) if text is not None]
        return [_proposal(path, RootKind.SYSTEM, self._mounts, True) for path in _without_nested(existing)]


class VolumeSource:
    """Mounted volumes at ``/data``, ``/mnt/*``, ``/media/*``, ``/media/*/*``, ``/run/media/*/*``
    (beneath ``root``). Always off by default — the user is asked per volume; the reason names what
    speaks against it."""

    def __init__(self, root: Path, mounts: MountTable) -> None:
        self._root = str(root).rstrip("/")
        self._mounts = mounts

    def _is_volume_target(self, target: str) -> bool:
        prefix = self._root
        if prefix and not _is_beneath(target, prefix):
            return False
        relative = target[len(prefix) :]
        parts = relative.strip("/").split("/")
        if parts == ["data"]:
            return True
        if parts[0] == "mnt":
            return len(parts) == 2
        if parts[0] == "media":
            return len(parts) in (2, 3)
        # Only the 4-segment form (/run/media/<user>/<volume>) is a volume target — udisks2's autofs layout.
        # The 3-segment /run/media/<user> is the per-user parent directory it manages, never a mounted
        # volume itself; a bare mount there would be surprising and is not proposed (ruling R1).
        return parts[:2] == ["run", "media"] and len(parts) == 4

    def propose(self) -> list[RootProposal]:
        proposals: dict[str, RootProposal] = {}
        for mount in self._mounts.mounts:
            if not self._is_volume_target(mount.target):
                continue
            if self._mounts.mount_for(mount.target) != mount or _usable(Path(mount.target)) is None:
                continue  # over-mounted, or not there (any more)
            if mount.network:
                reason: str | None = f"network filesystem ({mount.fstype})"
            elif mount.fstype not in LOCAL_FILESYSTEMS:
                reason = f"not a local disk filesystem ({mount.fstype})"
            else:
                reason = None
            proposals[mount.target] = RootProposal(mount.target, RootKind.VOLUME, mount.uuid, False, reason)
        return [proposals[target] for target in sorted(proposals)]


def default_sources(home: Path, root: Path, mounts: MountTable) -> list[ScanSource]:
    """The v1 sources, in display order. ``root`` is the filesystem root (``/``; a fake root in tests)."""
    return [XdgSource(home, mounts), SystemSource(home, root, mounts), VolumeSource(root, mounts)]


def propose_all(
    sources: Iterable[ScanSource], *, on_error: Callable[[ScanSource, Exception], None] | None = None
) -> list[RootProposal]:
    """Every proposal once (first source wins for a path). A source that raises proposes nothing — that
    never crashes a scan — but the source and the exception are not simply dropped (ruling R4): pass
    ``on_error`` to be told which source and what went wrong, so a real bug is not indistinguishable from
    "no roots proposed"."""
    seen: dict[str, RootProposal] = {}
    for source in sources:
        try:
            proposals = source.propose()
        except Exception as error:  # one bad source must not stop the others (R4: never silently, though)
            if on_error is not None:
                on_error(source, error)
            continue
        for proposal in proposals:
            seen.setdefault(proposal.path, proposal)
    return list(seen.values())
