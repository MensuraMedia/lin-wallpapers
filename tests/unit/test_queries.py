"""``catalogue/queries.py``: every filter, the default view, paging, sorting — and SQL injection is inert."""

from __future__ import annotations

import ast
import random
import sqlite3
import time
from dataclasses import fields, replace
from pathlib import Path

import pytest

from src.catalogue import db, ideal, queries
from src.catalogue.queries import AspectBucket, Orientation, QuerySpec, Segment, Sort
from tests.unit.test_catalogue_support import FHD, UHD, add_image, open_db, set_displays

INJECTIONS = [
    "'; DROP TABLE image;--",
    '"; DROP TABLE image;--',
    "x' OR '1'='1",
    "x') OR 1=1 --",
    "%",
    "_",
    "\\",
    "%' ESCAPE '%",
    "1; DELETE FROM image",
    "name COLLATE NOCASE ASC; DROP TABLE image",
    "\x00'; DROP TABLE image;--",
    "';\nDROP TABLE image;\n--",
    "‘’＇ʼ; DROP TABLE image",
]


def names(conn: sqlite3.Connection, spec: QuerySpec | None = None, **changes: object) -> list[str]:
    spec = replace(spec or QuerySpec(), **changes)  # type: ignore[arg-type]
    return [row.name for row in queries.fetch_page(conn, spec).rows]


@pytest.fixture
def library(tmp_path: Path) -> sqlite3.Connection:
    conn = open_db(tmp_path)
    conn.execute(
        "INSERT INTO root(id, path, kind) VALUES (1, '/photos', 'user'), (2, '/usr/share/backgrounds', 'xdg')"
    )
    add_image(conn, "/photos/Alps.jpg", 3840, 2160, root_id=1, size=900, first_seen=10)
    add_image(conn, "/photos/beach.PNG", 2560, 1600, root_id=1, size=800, first_seen=20, format="PNG")
    add_image(
        conn, "/photos/trips/canyon.webp", 3000, 2000, root_id=1, size=700, first_seen=30, format="WEBP"
    )
    add_image(conn, "/photos/trips2/dune.jpg", 1600, 1200, root_id=1, size=600, first_seen=40)
    add_image(conn, "/photos/Trips/everest.jpg", 3440, 1440, root_id=1, size=500, first_seen=50)
    add_image(conn, "/usr/share/backgrounds/fjord.jpg", 1080, 1920, root_id=2, size=400, first_seen=60)
    add_image(conn, "/usr/share/backgrounds/grid.jpg", 2000, 2000, root_id=2, size=300, first_seen=70)
    add_image(conn, "/photos/icon.jpg", 640, 360, root_id=1, size=100, first_seen=80)
    add_image(conn, "/photos/gone.jpg", 1920, 1080, root_id=1, size=200, first_seen=90, missing=1)
    add_image(
        conn, "/photos/broken.jpg", None, None, root_id=1, size=250, first_seen=95, probe_status="truncated"
    )
    rule = db.add_rule(conn, db.RuleKind.FILE, "/photos/hidden.jpg", group=None, root=None)
    add_image(conn, "/photos/hidden.jpg", 1920, 1080, root_id=1, size=150, first_seen=99, excluded_by=rule)
    return conn


ALL_DEFAULT = [
    "Alps.jpg",
    "beach.PNG",
    "canyon.webp",
    "dune.jpg",
    "everest.jpg",
    "fjord.jpg",
    "gone.jpg",
    "grid.jpg",
    "icon.jpg",
]


# ── defaults ─────────────────────────────────────────────────────────────────────────────────────────────


def test_default_view_hides_excluded_and_unusable_but_shows_missing(library: sqlite3.Connection) -> None:
    page = queries.fetch_page(library, QuerySpec())
    assert [r.name for r in page.rows] == ALL_DEFAULT  # NOCASE name order
    assert (page.total, page.offset) == (9, 0)
    gone = next(r for r in page.rows if r.name == "gone.jpg")
    assert gone.missing is True  # dimmed by the UI, not hidden
    assert "hidden.jpg" in names(library, include_excluded=True)
    assert "broken.jpg" in names(library, include_unusable=True)
    assert names(library, missing=True) == ["gone.jpg"]
    assert "gone.jpg" not in names(library, missing=False)


def test_small_images_are_stored_but_hidden_by_the_default_removable_filter(
    library: sqlite3.Connection,
) -> None:  # Q7
    spec = queries.default_spec(library)
    assert spec.min_long_edge == 1280
    assert "icon.jpg" not in names(library, spec)
    assert "icon.jpg" in names(library, replace(spec, min_long_edge=None))  # the chip is removable
    assert queries.get_image(library, "/photos/icon.jpg") is not None  # stored regardless
    assert "broken.jpg" in names(library, spec, include_unusable=True)  # unknown size is not "small"
    db.set_setting(library, "scan.min_long_edge", 2000)
    assert queries.default_spec(library).min_long_edge == 2000
    db.set_setting(library, "scan.min_long_edge", 0)
    assert queries.default_spec(library).min_long_edge is None


# ── each filter ──────────────────────────────────────────────────────────────────────────────────────────


def test_search_matches_name_and_dir_case_insensitively_all_terms(library: sqlite3.Connection) -> None:
    assert names(library, search="ALPS") == ["Alps.jpg"]
    assert names(library, search="backgrounds") == ["fjord.jpg", "grid.jpg"]
    assert names(library, search="trips jpg") == ["dune.jpg", "everest.jpg"]
    assert names(library, search="   ") == ALL_DEFAULT
    assert names(library, search="nothing-like-this") == []


def test_like_wildcards_in_search_are_literal(library: sqlite3.Connection) -> None:
    add_image(library, "/photos/100%_done\\final.jpg", 1920, 1080)
    assert names(library, search="%") == ["100%_done\\final.jpg"]
    assert names(library, search="_") == ["100%_done\\final.jpg"]
    assert names(library, search="\\") == ["100%_done\\final.jpg"]
    assert names(library, search="0%_d") == ["100%_done\\final.jpg"]
    assert names(library, search="A_ps") == []  # "_" is not "any character"
    assert names(library, search="A%s") == []
    assert queries.like_escape("50%_\\") == "50\\%\\_\\\\"


def test_dimension_filters(library: sqlite3.Connection) -> None:
    assert names(library, min_width=3440) == ["Alps.jpg", "everest.jpg"]
    assert names(library, min_height=1920) == ["Alps.jpg", "canyon.webp", "fjord.jpg", "grid.jpg"]
    assert names(library, min_long_edge=3000) == ["Alps.jpg", "canyon.webp", "everest.jpg"]


def test_aspect_buckets(library: sqlite3.Connection) -> None:
    assert names(library, aspect=AspectBucket.R16_9) == ["Alps.jpg", "gone.jpg", "icon.jpg"]
    assert names(library, aspect=AspectBucket.R16_10) == ["beach.PNG"]
    assert names(library, aspect=AspectBucket.R3_2) == ["canyon.webp"]
    assert names(library, aspect=AspectBucket.R4_3) == ["dune.jpg"]
    assert names(library, aspect=AspectBucket.R21_9) == []  # 3440×1440 is 2.39, outside 2.33 ± 0.03
    assert names(library, aspect=AspectBucket.R1_1) == ["grid.jpg"]
    assert names(library, aspect=AspectBucket.OTHER) == ["everest.jpg", "fjord.jpg"]
    assert names(library, aspect=AspectBucket.OTHER, include_unusable=True) == ["everest.jpg", "fjord.jpg"]


def test_orientation_format_root_and_dir_prefix(library: sqlite3.Connection) -> None:
    assert names(library, orientation=Orientation.PORTRAIT) == ["fjord.jpg"]
    assert names(library, orientation=Orientation.SQUARE) == ["grid.jpg"]
    assert len(names(library, orientation=Orientation.LANDSCAPE)) == 7
    assert names(library, formats=("png", "webp")) == ["beach.PNG", "canyon.webp"]
    assert names(library, root_id=2) == ["fjord.jpg", "grid.jpg"]
    assert names(library, root_id=404) == []
    # a prefix is a directory boundary, case-sensitive: not "/photos/trips2", not "/photos/Trips"
    assert names(library, dir_prefix="/photos/trips") == ["canyon.webp"]
    assert names(library, dir_prefix="/photos/trips/") == ["canyon.webp"]
    assert names(library, dir_prefix="/usr/share") == ["fjord.jpg", "grid.jpg"]
    assert names(library, dir_prefix="/") == ALL_DEFAULT
    assert names(library, dir_prefix="/photos/%") == []


def test_filters_combine(library: sqlite3.Connection) -> None:
    spec = QuerySpec(
        search="photos", min_width=2000, orientation=Orientation.LANDSCAPE, formats=("JPEG",), root_id=1
    )
    assert names(library, spec) == ["Alps.jpg", "everest.jpg"]
    assert names(library, spec, aspect=AspectBucket.R16_9, missing=False, dir_prefix="/photos") == [
        "Alps.jpg"
    ]


def test_segment_combines_with_filters(library: sqlite3.Connection) -> None:
    set_displays(library, FHD, UHD)
    ideal.rebuild(library, 16)
    assert names(library, segment=Segment.IDEAL) == ["Alps.jpg", "beach.PNG", "canyon.webp"]
    assert names(library, segment=Segment.IDEAL, formats=("PNG",)) == ["beach.PNG"]
    assert names(library, segment=Segment.IDEAL, every_display=True) == ["Alps.jpg"]
    assert "gone.jpg" not in names(library, segment=Segment.IDEAL, missing=True)  # exact size, but missing
    assert "hidden.jpg" not in names(library, segment=Segment.IDEAL, include_excluded=True)


def test_every_display_is_empty_when_no_display_is_connected(library: sqlite3.Connection) -> None:
    """§2.5/§2.3: `every` needs >=1 connected display; a `0 = 0` count-equality trap must not pass here."""
    # No set_displays() call: the `display` table has no rows at all, so `connected = 1` matches nothing.
    assert names(library, segment=Segment.IDEAL, every_display=True) == []
    page = queries.fetch_page(library, QuerySpec(segment=Segment.IDEAL, every_display=True))
    assert page.total == 0
    assert queries.segment_counts(library)["every"] == 0


# ── sorting and paging ───────────────────────────────────────────────────────────────────────────────────


def test_every_sort_key_both_directions(library: sqlite3.Connection) -> None:
    assert names(library, sort=Sort.NAME, descending=True) == ALL_DEFAULT[::-1]
    by_date = names(library, sort=Sort.DATE_ADDED)
    assert by_date[0] == "Alps.jpg" and by_date == names(library, sort=Sort.DATE_ADDED, descending=True)[::-1]
    assert names(library, sort=Sort.SIZE, descending=True)[:2] == ["Alps.jpg", "beach.PNG"]
    assert names(library, sort=Sort.RESOLUTION)[0] == "icon.jpg"
    assert names(library, sort=Sort.RESOLUTION, descending=True)[0] == "Alps.jpg"


def test_ties_are_broken_by_id_so_paging_is_stable(tmp_path: Path) -> None:
    conn = open_db(tmp_path)
    ids = [add_image(conn, f"/d{n}/same.jpg", 1920, 1080, size=5, first_seen=5) for n in range(25)]
    for sort in Sort:
        seen: list[int] = []
        for offset in range(0, 25, 7):
            page = queries.fetch_page(conn, QuerySpec(sort=sort, limit=7, offset=offset))
            assert (page.total, page.offset) == (25, offset)
            seen += [row.id for row in page.rows]
        assert seen == ids
        reverse = queries.fetch_page(conn, QuerySpec(sort=sort, descending=True, limit=25))
        assert [row.id for row in reverse.rows] == ids[::-1]


def test_limit_is_clamped_and_offset_floored(library: sqlite3.Connection) -> None:
    assert queries.build(QuerySpec(limit=10**9)).params[-2:] == (1000, 0)
    assert queries.build(QuerySpec(limit=0, offset=-5)).params[-2:] == (1, 0)
    assert queries.build(QuerySpec(limit=-3)).params[-2:] == (1, 0)
    assert len(queries.fetch_page(library, QuerySpec(limit=0)).rows) == 1
    assert queries.fetch_page(library, QuerySpec(offset=10_000)).rows == ()


def test_get_image_by_id_and_path(library: sqlite3.Connection) -> None:
    by_path = queries.get_image(library, "/photos/Alps.jpg")
    assert by_path is not None and queries.get_image(library, by_path.id) == by_path
    assert (by_path.dir, by_path.name, by_path.width, by_path.has_alpha, by_path.missing) == (
        "/photos",
        "Alps.jpg",
        3840,
        False,
        False,
    )
    assert queries.get_image(library, "/photos/alps.jpg") is None  # paths are case-sensitive
    assert queries.get_image(library, 10**12) is None
    assert queries.get_image(library, "1") is None  # a str is always a path, never an id


# ── injection ────────────────────────────────────────────────────────────────────────────────────────────


def _intact(conn: sqlite3.Connection, expected: int) -> None:
    assert conn.execute("SELECT count(*) FROM image").fetchone()[0] == expected
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


@pytest.mark.parametrize("attack", INJECTIONS)
def test_injection_through_every_text_input_is_inert(library: sqlite3.Connection, attack: str) -> None:
    total = library.execute("SELECT count(*) FROM image").fetchone()[0]
    for spec in (
        QuerySpec(search=attack),
        QuerySpec(dir_prefix=attack),
        QuerySpec(formats=(attack,)),
        QuerySpec(formats=("JPEG", attack), search=attack, dir_prefix=attack, segment=Segment.IDEAL),
    ):
        compiled = queries.build(spec)
        benign = replace(
            spec,
            search="benign" if spec.search else "",
            dir_prefix=None if spec.dir_prefix is None else "/benign",
            formats=tuple("PNG" for _ in spec.formats),
        )
        if len(attack.split()) == 1:
            assert compiled.sql == queries.build(benign).sql  # the text never depends on the value
        assert "DROP" not in compiled.sql and "DELETE" not in compiled.sql
        assert compiled.sql.count("?") == len(compiled.params)
        page = queries.fetch_page(library, spec)
        assert page.rows == () and page.total == 0  # no row contains these strings: nothing matches
        queries.segment_counts(library, spec)
    assert queries.get_image(library, attack) is None
    _intact(library, total)


@pytest.mark.parametrize("attack", INJECTIONS)
def test_a_file_really_named_like_an_attack_is_found_literally(
    library: sqlite3.Connection, attack: str
) -> None:
    if "\x00" in attack:
        pytest.skip("a POSIX file name cannot contain NUL")
    safe_name = attack.replace("/", "∕") + ".jpg"
    path = "/photos/odd/" + safe_name
    image_id = add_image(library, path, 1920, 1080)
    term = attack.replace("/", "∕")
    if term.split() == [term]:  # search splits on whitespace; multi-word attacks are tested above
        assert [r.id for r in queries.fetch_page(library, QuerySpec(search=term)).rows] == [image_id]
    found = queries.get_image(library, path)
    assert found is not None and found.name == safe_name
    _intact(library, 12)


@pytest.mark.parametrize("attack", INJECTIONS)
def test_sort_keys_and_enums_come_only_from_the_allow_list(library: sqlite3.Connection, attack: str) -> None:
    with pytest.raises(queries.UnsupportedSort):
        queries.build(QuerySpec(sort=attack))  # type: ignore[arg-type]
    with pytest.raises(queries.UnsupportedSort):
        queries.build_count(QuerySpec(sort=attack))  # type: ignore[arg-type]
    for bad in (
        QuerySpec(segment=attack),  # type: ignore[arg-type]
        QuerySpec(aspect=attack),  # type: ignore[arg-type]
        QuerySpec(orientation=attack),  # type: ignore[arg-type]
    ):
        with pytest.raises(ValueError):
            queries.fetch_page(library, bad)
    _intact(library, 11)


def test_score_sort_is_unsupported_until_m2() -> None:
    with pytest.raises(queries.UnsupportedSort):
        queries.build(QuerySpec(sort="score"))  # type: ignore[arg-type]
    assert queries.build(QuerySpec(sort="name")).sql == queries.build(QuerySpec(sort=Sort.NAME)).sql  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field", ["display_id", "min_width", "min_height", "min_long_edge", "root_id", "limit", "offset"]
)
@pytest.mark.parametrize("attack", ["1 OR 1=1", "1; DROP TABLE image", 1.5, True, b"1"])
def test_numeric_inputs_must_be_ints(library: sqlite3.Connection, field: str, attack: object) -> None:
    spec = replace(QuerySpec(segment=Segment.IDEAL), **{field: attack})  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        queries.fetch_page(library, spec)
    _intact(library, 11)


@pytest.mark.parametrize("field", ["search", "dir_prefix"])
def test_text_inputs_must_be_str(library: sqlite3.Connection, field: str) -> None:
    with pytest.raises(TypeError):
        queries.build(replace(QuerySpec(), **{field: 5}))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        queries.build(QuerySpec(formats=(b"JPEG",)))  # type: ignore[arg-type]


def test_sql_text_is_independent_of_every_value() -> None:
    """Specs that differ only in VALUES compile to byte-identical SQL: the text is chosen by shape alone."""
    one = QuerySpec(
        segment=Segment.IDEAL,
        display_id=1,
        exact=True,
        search="a b",
        min_width=1,
        min_height=2,
        min_long_edge=3,
        aspect=AspectBucket.R16_9,
        orientation=Orientation.LANDSCAPE,
        formats=("a",),
        root_id=4,
        dir_prefix="/x",
        limit=5,
        offset=6,
    )
    two = replace(
        one,
        display_id=99,
        exact=False,
        search="';DROP-- %_",
        min_width=10,
        min_height=20,
        min_long_edge=30,
        aspect=AspectBucket.R4_3,
        formats=("x'", "y", "z"),
        root_id=40,
        dir_prefix="/y'--",
        limit=50,
        offset=60,
    )
    assert queries.build(one).sql == queries.build(two).sql
    assert queries.build_count(one).sql == queries.build_count(two).sql
    assert len(queries.build(one).params) == len(queries.build(two).params)
    assert {f.name for f in fields(QuerySpec)} >= {"segment", "sort", "search", "formats", "dir_prefix"}


def test_search_is_bounded() -> None:
    compiled = queries.build(QuerySpec(search=" ".join(["x" * 5000] * 50)))
    assert compiled.sql.count("LIKE") == 2 * queries.MAX_SEARCH_TERMS
    assert max(len(p) for p in compiled.params if isinstance(p, str)) == queries.MAX_TERM_CHARS + 2


def test_queries_module_never_formats_strings() -> None:
    """Contract §2.5: no f-string, no ``%`` formatting and no ``.format`` anywhere in ``queries.py``."""
    tree = ast.parse(Path(queries.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        assert not isinstance(node, ast.JoinedStr), f"f-string at line {node.lineno}"
        if isinstance(node, ast.BinOp):
            assert not isinstance(node.op, ast.Mod), f"% formatting at line {node.lineno}"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {"format", "format_map", "executescript"}, f"line {node.lineno}"
    # every SQL fragment is a module-level constant; functions only pick and concatenate them
    for function in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        for node in ast.walk(function):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value == ast.get_docstring(function, clean=False):
                    continue
                upper = node.value.upper()
                assert not any(word in upper for word in ("SELECT ", "ORDER BY", " FROM ", "LIKE ")), (
                    function.name,
                    node.value,
                )


# ── speed ────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_page_of_20k_rows_is_fast(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rng = random.Random(7)
    conn = open_db(tmp_path)
    set_displays(conn, FHD)
    with db.transaction(conn):
        for n in range(20_000):
            name = f"photo-{rng.randrange(10**6):06d}-{n}.jpg"
            width, height = rng.choice([1280, 1920, 2560, 3840]), rng.choice([800, 1080, 1440, 2160])
            add_image(conn, f"/lib/{n % 211}/{name}", width, height, size=rng.randrange(10**7), first_seen=n)
    ideal.rebuild(conn, 16)
    timings: dict[str, float] = {}
    for label, spec in {
        "all/name": QuerySpec(),
        "ideal/name": QuerySpec(segment=Segment.IDEAL),
        "search+filters/size": QuerySpec(search="photo-1", min_width=1920, sort=Sort.SIZE, descending=True),
        "deep page": QuerySpec(offset=15_000),
    }.items():
        started = time.perf_counter()
        page = queries.fetch_page(conn, spec)
        timings[label] = (time.perf_counter() - started) * 1000
        assert page.total > 0 and page.rows
    with capsys.disabled():
        print(
            "\n[perf] fetch_page over 20,000 rows (budget 100 ms): "
            + ", ".join(f"{k} {v:.1f} ms" for k, v in timings.items())
        )
    assert max(timings.values()) < 1000  # generous for slow machines; the real numbers are printed above
