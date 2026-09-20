"""Scan roots (``scanner/roots.py``): findmnt/user-dirs parsing, the mount table, and the three root
sources (contract §2.6; ruling R1-R4, 2026-09-19). Tests never touch the real system: mounts come from
injected JSON/runners, directories live under ``tmp_path``."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.scanner import roots as mod
from src.scanner.roots import (
    LOCAL_FILESYSTEMS,
    Mount,
    MountTable,
    RootKind,
    RootProposal,
    SystemSource,
    VolumeSource,
    XdgSource,
    default_sources,
    is_network_fstype,
    load_mounts,
    parse_findmnt,
    parse_user_dirs,
    propose_all,
)


def _leaf(target: int | str, **overrides: object) -> dict[str, object]:
    """A minimal findmnt entry. An int names a synthetic ``/d<i>``, for tests that need many distinct ones."""
    name = f"d{target}" if isinstance(target, int) else target
    path = name if name.startswith("/") else f"/{name}"
    node: dict[str, object] = {
        "target": path,
        "source": f"/dev/{path.strip('/').replace('/', '_') or 'root'}",
        "fstype": "ext4",
        "uuid": None,
        "label": None,
        "options": "rw",
    }
    node.update(overrides)
    return node


def _doc(*filesystems: object) -> str:
    return json.dumps({"filesystems": list(filesystems)})


def _mount(
    target: str,
    *,
    fstype: str = "ext4",
    uuid: str | None = None,
    label: str | None = None,
    network: bool = False,
    removable: bool = False,
    stable: bool = True,
    source: str = "/dev/x",
) -> Mount:
    return Mount(
        target=target,
        source=source,
        fstype=fstype,
        uuid=uuid,
        label=label,
        removable=removable,
        network=network,
        stable_inodes=stable,
    )


def _proposal(
    path: str, *, kind: RootKind = RootKind.XDG, default_on: bool = True, reason: str | None = None
) -> RootProposal:
    return RootProposal(path=path, kind=kind, volume_id=None, default_on=default_on, reason=reason)


# ── parse_findmnt ────────────────────────────────────────────────────────────────────────────────────────


def test_nested_children_are_flattened_depth_first() -> None:
    grandchild = _leaf("home/sub")
    home = _leaf("home", children=[grandchild])
    boot = _leaf("boot")
    root = _leaf("", children=[boot, home])
    data = _leaf("data")
    assert [m.target for m in parse_findmnt(_doc(root, data))] == [
        "/",
        "/boot",
        "/home",
        "/home/sub",
        "/data",
    ]


def test_network_fstype_is_flagged() -> None:
    [mount] = parse_findmnt(_doc(_leaf("mnt/nas", fstype="nfs4", source="server:/export")))
    assert mount.network is True
    assert mount.stable_inodes is True  # nfs4 is not in the unstable-inode set


def test_removable_is_true_beneath_media_and_run_media_only() -> None:
    doc = _doc(
        _leaf("media/user/USB", fstype="vfat"),
        _leaf("run/media/user/USB2"),
        _leaf("mnt/data"),
    )
    media, run_media, mnt = parse_findmnt(doc)
    assert media.removable is True
    assert media.stable_inodes is False  # vfat
    assert run_media.removable is True
    assert mnt.removable is False


def test_missing_uuid_and_label_become_none() -> None:
    [mount] = parse_findmnt(_doc(_leaf("mnt/x")))
    assert mount.uuid is None
    assert mount.label is None


@pytest.mark.parametrize(
    "text",
    [
        "",
        "not json {",
        "[]",
        "null",
        "42",
        '{"filesystems": "nope"}',
        '{"filesystems": [1, "x", null, {"target": 5}]}',
        '{"filesystems": [{"target": "relative", "fstype": "ext4"}]}',
        '{"filesystems": [{"target": "/a", "fstype": ""}]}',
        '{"filesystems": [{"fstype": "ext4"}]}',
    ],
)
def test_garbage_json_never_raises(text: str) -> None:
    assert parse_findmnt(text) == []


def test_deeply_nested_json_does_not_raise() -> None:
    text = "[" * 3000 + "]" * 3000
    assert parse_findmnt(text) == []


def test_findmnt_caps_total_mounts_at_max_mounts() -> None:
    entries = [_leaf(i) for i in range(mod._MAX_MOUNTS + 200)]
    mounts = parse_findmnt(_doc(*entries))
    assert len(mounts) == mod._MAX_MOUNTS


def test_findmnt_caps_recursion_at_max_depth() -> None:
    depth_beyond = 80
    node = _leaf(depth_beyond - 1)
    for i in range(depth_beyond - 2, -1, -1):
        node = _leaf(i, children=[node])
    mounts = parse_findmnt(_doc(node))
    targets = [m.target for m in mounts]
    assert targets == [f"/d{i}" for i in range(mod._MAX_DEPTH + 1)]
    assert f"/d{mod._MAX_DEPTH + 1}" not in targets


def test_children_not_a_list_is_ignored() -> None:
    [mount] = parse_findmnt(_doc(_leaf("a", children="oops")))
    assert mount.target == "/a"


def test_root_target_stays_the_slash_itself() -> None:
    [mount] = parse_findmnt(_doc(_leaf("")))
    assert mount.target == "/"


def test_trailing_slash_in_target_is_stripped() -> None:
    [mount] = parse_findmnt(_doc(_leaf("mnt/x/")))
    assert mount.target == "/mnt/x"


def test_target_with_lone_surrogate_is_skipped() -> None:
    # "\ud800" decodes to a lone surrogate codepoint: valid in a Python str, not encodable as UTF-8.
    text = (
        '{"filesystems": [{"target": "/\\ud800", "source": "s", "fstype": "ext4",'
        ' "uuid": null, "label": null, "options": ""}]}'
    )
    assert parse_findmnt(text) == []


def test_value_with_nul_character_is_treated_as_absent() -> None:
    [mount] = parse_findmnt(_doc(_leaf("mnt/x", uuid="U\x001")))
    assert mount.uuid is None


# ── is_network_fstype ────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("fstype", "options", "expected"),
    [
        ("nfs4", "", True),
        ("NFS", "", True),
        ("cifs", "", True),
        ("smb3", "", True),
        ("fuse.sshfs", "", True),
        ("fuse", "", True),
        ("9p", "", True),
        ("ext4", "", False),
        ("ext4", "rw,_netdev,relatime", True),
        ("btrfs", "rw,relatime", False),
        ("", "", False),
    ],
)
def test_is_network_fstype(fstype: str, options: str, expected: bool) -> None:
    assert is_network_fstype(fstype, options) is expected


# ── parse_user_dirs ──────────────────────────────────────────────────────────────────────────────────────


def test_quoted_path_is_read() -> None:
    assert parse_user_dirs('XDG_PICTURES_DIR="/home/u/Pics"\n', "/home/u") == "/home/u/Pics"


def test_home_prefix_is_expanded() -> None:
    assert parse_user_dirs('XDG_PICTURES_DIR="$HOME/Photos"\n', "/home/u") == "/home/u/Photos"


def test_disabled_or_equal_to_home_is_none() -> None:
    assert parse_user_dirs('XDG_PICTURES_DIR="$HOME"\n', "/home/u") is None
    assert parse_user_dirs('XDG_PICTURES_DIR="/home/u"\n', "/home/u") is None
    assert parse_user_dirs('XDG_PICTURES_DIR="/home/u/"\n', "/home/u") is None


def test_missing_file_falls_back_via_xdg_source(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "Pictures").mkdir(parents=True)
    source = XdgSource(home, MountTable())
    [proposal] = source.propose()
    assert proposal.path == str(home / "Pictures")


def test_bad_line_is_ignored_last_assignment_wins() -> None:
    text = (
        "garbage line\n"
        "XDG_PICTURES_DIR=/no/quotes\n"
        'XDG_PICTURES_DIR="/home/u/First"\n'
        'XDG_PICTURES_DIR="/home/u/Second"\n'
    )
    assert parse_user_dirs(text, "/home/u") == "/home/u/Second"


def test_relative_or_nul_value_resets_to_none() -> None:
    assert parse_user_dirs('XDG_PICTURES_DIR="relative/path"\n', "/home/u") is None
    assert parse_user_dirs('XDG_PICTURES_DIR="/home/u/Pics\x00x"\n', "/home/u") is None


def test_later_invalid_line_overrides_an_earlier_valid_one() -> None:
    text = 'XDG_PICTURES_DIR="/home/u/Good"\nXDG_PICTURES_DIR="relative"\n'
    assert parse_user_dirs(text, "/home/u") is None


# ── MountTable ───────────────────────────────────────────────────────────────────────────────────────────


def test_mount_for_ancestor_lookup() -> None:
    table = MountTable([_mount("/"), _mount("/home", uuid="H1")])
    assert table.mount_for("/home/user/pics").target == "/home"  # type: ignore[union-attr]
    assert table.mount_for("/etc/passwd").target == "/"  # type: ignore[union-attr]
    assert table.mount_for("relative") is None


def test_mount_for_over_mount_precedence() -> None:
    old = _mount("/mnt/x", uuid="OLD")
    new = _mount("/mnt/x", uuid="NEW")
    table = MountTable([old, new])
    assert len(table) == 2
    assert table.mount_for("/mnt/x").uuid == "NEW"  # type: ignore[union-attr]
    assert table.by_uuid("NEW") is new
    assert table.by_uuid("OLD") is old  # still findable by identity even though shadowed at its target
    assert table.by_uuid("MISSING") is None


def test_off_reason_network_text_and_none() -> None:
    table = MountTable([_mount("/mnt/nas", fstype="nfs4", network=True), _mount("/data")])
    assert table.off_reason("/mnt/nas/photos") == "network filesystem (nfs4)"
    assert table.off_reason("/data/x") is None
    assert table.off_reason("/nowhere") is None


def test_mount_for_a_posix_double_slash_path() -> None:
    # os.path.normpath keeps a genuine leading "//" (POSIX gives it implementation-defined meaning);
    # mount_for still finds the ancestor mount by stripping one of the two slashes before walking up.
    table = MountTable([_mount("/"), _mount("/srv")])
    assert table.mount_for("//srv/share").target == "/srv"


def test_empty_mount_table() -> None:
    table = MountTable()
    assert len(table) == 0
    assert table.mount_for("/") is None
    assert table.by_uuid("x") is None


def test_load_mounts_empty_on_no_output() -> None:
    assert len(load_mounts(lambda argv, timeout: None)) == 0


def test_load_mounts_parses_runner_output() -> None:
    calls: list[tuple[tuple[str, ...], float]] = []

    def run(argv: object, timeout: float) -> str | None:
        calls.append((tuple(argv), timeout))  # type: ignore[arg-type]
        return _doc(_leaf(0))

    table = load_mounts(run)
    assert len(table) == 1
    assert calls == [(mod.FINDMNT_ARGV, mod._FINDMNT_TIMEOUT)]


# ── XdgSource / SystemSource ─────────────────────────────────────────────────────────────────────────────


def test_xdg_missing_dirs_not_proposed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    assert XdgSource(home, MountTable()).propose() == []


def test_xdg_nonexistent_home_proposes_nothing(tmp_path: Path) -> None:
    home = tmp_path / "does-not-exist"
    assert XdgSource(home, MountTable()).propose() == []


def test_xdg_user_dirs_file_names_a_custom_pictures_folder(tmp_path: Path) -> None:
    home = tmp_path / "home"
    custom = home / "MyPics"
    custom.mkdir(parents=True)
    (home / ".config").mkdir()
    (home / ".config" / "user-dirs.dirs").write_text('XDG_PICTURES_DIR="$HOME/MyPics"\n')
    paths = [p.path for p in XdgSource(home, MountTable()).propose()]
    assert paths == [str(custom)]


def test_xdg_nested_wallpapers_folder_collapses_into_pictures(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "Pictures" / "wallpapers").mkdir(parents=True)
    (home / "Wallpapers").mkdir()
    paths = sorted(p.path for p in XdgSource(home, MountTable()).propose())
    assert paths == sorted([str(home / "Pictures"), str(home / "Wallpapers")])


def test_xdg_proposals_are_on_by_default_unless_networked(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "Pictures").mkdir(parents=True)
    mounts = MountTable([_mount(str(home / "Pictures"), fstype="nfs4", network=True)])
    [proposal] = XdgSource(home, mounts).propose()
    assert proposal.kind is RootKind.XDG
    assert proposal.default_on is False
    assert proposal.reason == "network filesystem (nfs4)"


def test_system_missing_dirs_not_proposed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    root = tmp_path / "root"
    home.mkdir()
    root.mkdir()
    assert SystemSource(home, root, MountTable()).propose() == []


def test_system_existing_dirs_proposed_with_mount_reason(tmp_path: Path) -> None:
    home = tmp_path / "home"
    root = tmp_path / "root"
    backgrounds = root / "usr" / "share" / "backgrounds"
    local = home / ".local" / "share" / "backgrounds"
    backgrounds.mkdir(parents=True)
    local.mkdir(parents=True)
    mounts = MountTable([_mount(str(backgrounds), fstype="nfs4", network=True)])
    proposals = {p.path: p for p in SystemSource(home, root, mounts).propose()}
    assert proposals[str(backgrounds)].default_on is False
    assert proposals[str(backgrounds)].reason == "network filesystem (nfs4)"
    assert proposals[str(local)].default_on is True
    assert proposals[str(local)].reason is None
    assert all(p.kind is RootKind.SYSTEM for p in proposals.values())


def test_system_nested_folder_collapses(tmp_path: Path) -> None:
    root = tmp_path / "root"
    backgrounds = root / "usr" / "share" / "backgrounds"
    backgrounds.mkdir(parents=True)
    home = backgrounds  # pathological but exercises _without_nested for SystemSource's own list
    (home / ".local" / "share" / "backgrounds").mkdir(parents=True)
    paths = [p.path for p in SystemSource(home, root, MountTable()).propose()]
    assert paths == [str(backgrounds)]


def test_system_source_with_nonexistent_root_and_home_proposes_nothing(tmp_path: Path) -> None:
    home = tmp_path / "no-home"
    root = tmp_path / "no-root"
    assert SystemSource(home, root, MountTable()).propose() == []


# ── VolumeSource ─────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("/data", True),
        ("/data/extra", False),
        ("/mnt/usb", True),
        ("/mnt", False),
        ("/mnt/usb/extra", False),
        ("/media/usb0", True),
        ("/media", False),
        ("/media/user/usb1", True),
        ("/media/user/usb1/extra", False),
        ("/run/media/user/usb2", True),
        ("/run/media/user", False),  # R1 regression: the 3-segment form is no longer a volume target
        ("/run/media", False),
        ("/run/other", False),
        ("/srv/data2", False),
    ],
)
def test_is_volume_target_shapes(target: str, expected: bool) -> None:
    # Pure string logic (no filesystem I/O): safe to probe directly against the real "/" prefix.
    source = VolumeSource(Path("/"), MountTable())
    assert source._is_volume_target(target) is expected


def test_is_volume_target_false_outside_a_non_root_prefix(tmp_path: Path) -> None:
    root = tmp_path / "root"
    source = VolumeSource(root, MountTable())
    assert source._is_volume_target("/data") is False


def test_volume_source_proposes_each_recognised_shape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    shapes = [
        root / "data",
        root / "mnt" / "usb",
        root / "media" / "usb0",
        root / "media" / "user" / "usb1",
        root / "run" / "media" / "user" / "usb2",
    ]
    for path in shapes:
        path.mkdir(parents=True)
    mounts = MountTable([_mount(str(p), uuid=f"U-{i}") for i, p in enumerate(shapes)])
    proposals = VolumeSource(root, mounts).propose()
    assert {p.path for p in proposals} == {str(p) for p in shapes}
    assert all(p.default_on is False for p in proposals)
    assert all(p.kind is RootKind.VOLUME for p in proposals)


def test_volume_source_three_segment_run_media_not_proposed(tmp_path: Path) -> None:
    root = tmp_path / "root"
    bad = root / "run" / "media" / "user"  # /run/media/<user>: the R1 regression
    bad.mkdir(parents=True)
    mounts = MountTable([_mount(str(bad))])
    assert VolumeSource(root, mounts).propose() == []


def test_volume_source_reason_text_network_vs_non_local(tmp_path: Path) -> None:
    root = tmp_path / "root"
    nas = root / "mnt" / "nas"
    exotic = root / "mnt" / "exotic"
    nas.mkdir(parents=True)
    exotic.mkdir(parents=True)
    mounts = MountTable([_mount(str(nas), fstype="nfs4", network=True), _mount(str(exotic), fstype="zfs")])
    reasons = {p.path: p.reason for p in VolumeSource(root, mounts).propose()}
    assert reasons[str(nas)] == "network filesystem (nfs4)"
    assert reasons[str(exotic)] == "not a local disk filesystem (zfs)"


def test_volume_source_local_filesystem_has_no_reason_but_stays_off(tmp_path: Path) -> None:
    root = tmp_path / "root"
    usb = root / "mnt" / "usb"
    usb.mkdir(parents=True)
    assert next(iter(LOCAL_FILESYSTEMS)) is not None  # sanity: the allow-list is not empty
    mounts = MountTable([_mount(str(usb), fstype="ext4")])
    [proposal] = VolumeSource(root, mounts).propose()
    assert proposal.reason is None
    assert proposal.default_on is False


def test_volume_source_over_mounted_target_only_the_visible_mount_is_proposed(tmp_path: Path) -> None:
    root = tmp_path / "root"
    usb = root / "mnt" / "usb"
    usb.mkdir(parents=True)
    mounts = MountTable(
        [_mount(str(usb), fstype="ext4", uuid="OLD"), _mount(str(usb), fstype="vfat", uuid="NEW")]
    )
    [proposal] = VolumeSource(root, mounts).propose()
    assert proposal.volume_id == "NEW"


def test_volume_source_not_there_any_more_is_skipped(tmp_path: Path) -> None:
    root = tmp_path / "root"
    gone = root / "mnt" / "gone"  # never created on disk
    mounts = MountTable([_mount(str(gone))])
    assert VolumeSource(root, mounts).propose() == []


# ── default_sources / propose_all ────────────────────────────────────────────────────────────────────────


def test_default_sources_in_display_order(tmp_path: Path) -> None:
    home = tmp_path / "home"
    root = tmp_path / "root"
    sources = default_sources(home, root, MountTable())
    assert [type(s) for s in sources] == [XdgSource, SystemSource, VolumeSource]


class _Boom:
    def propose(self) -> list[RootProposal]:
        raise RuntimeError("boom")


class _Gives:
    def __init__(self, proposals: list[RootProposal]) -> None:
        self._proposals = proposals

    def propose(self) -> list[RootProposal]:
        return list(self._proposals)


def test_propose_all_first_source_wins_for_a_path() -> None:
    first = _Gives([_proposal("/x", default_on=True)])
    second = _Gives([_proposal("/x", default_on=False, reason="dup")])
    result = propose_all([first, second])
    assert len(result) == 1
    assert result[0].default_on is True


def test_propose_all_swallows_a_raising_source_by_default() -> None:
    good = _Gives([_proposal("/x")])
    assert [p.path for p in propose_all([_Boom(), good])] == ["/x"]


def test_propose_all_reports_the_swallowed_source_and_exception_via_on_error() -> None:
    boom = _Boom()
    good = _Gives([_proposal("/x")])
    seen: list[tuple[object, BaseException]] = []
    result = propose_all([boom, good], on_error=lambda source, error: seen.append((source, error)))
    assert [p.path for p in result] == ["/x"]
    assert len(seen) == 1
    assert seen[0][0] is boom
    assert isinstance(seen[0][1], RuntimeError)
    assert str(seen[0][1]) == "boom"


# ── internal helpers (_usable / _is_dir) ─────────────────────────────────────────────────────────────────


def test_usable_rejects_an_unencodable_path(tmp_path: Path) -> None:
    bad = tmp_path / "img\udcff"
    assert mod._usable(bad) is None


@pytest.mark.skipif(
    hasattr(os, "getuid") and os.getuid() == 0, reason="root bypasses permission checks"
)
def test_usable_swallows_a_permission_error(tmp_path: Path) -> None:
    blocked = tmp_path / "blocked"
    blocked.mkdir(mode=0o000)
    try:
        assert mod._usable(blocked / "inner") is None
    finally:
        blocked.chmod(0o755)
