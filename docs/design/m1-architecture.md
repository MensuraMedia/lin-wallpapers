# M1 — Catalogue: implementation contract

Status: **contract** for implementers and the adversary. Sources: `docs/milestones.md` (M1), `TECHNICAL-CONCEPT.md`
§5–§7, §13, §15.2, §17, §20. Where this file and those disagree, §5 below records why and this file wins until
the team lead rules otherwise. Signatures are binding; private helpers are the implementer's business.
Python 3.11, stdlib + Pillow (service side), PyGObject (GUI side only). No network. Writes only under XDG dirs.

## 1. Module map, ownership, dependency direction

| File | Phase · owner | Kind | Imports from `src` |
| --- | --- | --- | --- |
| `util/cancel.py`, `capability/reasons.py`, `config/config_paths.py` (+`catalogue_db()`, `thumbs_dir()`), `pyproject.toml`, `tests/helpers/imagegen.py` | P2 · scaffold | pure | — |
| `scanner/exclude.py` | P3 · impl-A | **pure** (no I/O, no clock, no `os.path.expanduser`) | — |
| `scanner/displays.py` | P3 · impl-B | pure parsers + sysfs read + subprocess (injected) | `capability.reasons` |
| `catalogue/model.py`, `db.py`, `schema.sql`, `migrations/{__init__,m0001_initial}.py`, `queries.py` | P4 · impl-C | SQLite | `scanner.exclude`, `scanner.displays` (records only), `config` |
| `catalogue/ideal.py` | P4 · impl-D | `evaluate/explain` pure; `rebuild` SQLite | `scanner.displays` (`Display`) |
| `scanner/roots.py` | P5a · impl-E | fs read + `findmnt` (injected runner) | — |
| `scanner/walker.py`, `scanner/probe.py` | P5a · impl-F | fs read, Pillow | `scanner.exclude`, `util.cancel` |
| `catalogue/thumbs.py` | P5a · impl-G | fs write (cache dir only), Pillow | `config`, `scanner.probe` (`ThumbSink` protocol only) |
| `catalogue/ingest.py` (writer thread + `ScanService`), `cli/linwp.py`, `cli/cmd_{scan,list,show,exclude,displays}.py` | P5b · impl-H | SQLite write, orchestration | everything above |
| `viewmodels/{services,scan_vm,sources_vm,browse_vm}.py` (gi-free), `viewmodels/gdk_displays.py` (the only VM importing `gi`, via `src.gtk_version`) | P6 · impl-I | — | services, `util.threads` |
| `pages/page_sources.py`, `pages/page_browse.py`, `ui/components/{image_grid,image_card,filter_bar,scan_banner,exclusions_panel,displays_strip}.py` | P6 · impl-J | GTK only | `viewmodels` only |

Direction (no cycles): `util, capability, config` ← `scanner.{exclude,displays}` ← `scanner.{roots,probe,walker}` ;
`scanner.*` ← `catalogue.{model,db,queries,ideal,thumbs}` ← `catalogue.ingest` ← `cli`, `viewmodels` ← `pages/ui`.
**`src.scanner` never imports `src.catalogue`** (P2 adds the import-linter contract; walker talks to the catalogue
through Protocols it defines itself). P2 also adds: `src.scanner.*` to the mypy-strict list; `PIL.*` to
`ignore_missing_imports` (Pillow 10.2 ships no `py.typed`); `[tool.setuptools.package-data] "src.catalogue" =
["schema.sql"]`; contract "gi-free view models" (`services, scan_vm, sources_vm, browse_vm` forbidden `gi`).
No file is owned by two implementers in the same phase; `pyproject.toml`, `conftest.py` and `linwp.py` are
touched only by the owner named above.

## 2. Public APIs

### 2.0 Shared (P2)
```python
# util/cancel.py
class Cancelled(Exception): ...
class CancelToken:   # wraps threading.Event: cancel() -> None; cancelled: bool (property); raise_if_cancelled() -> None
# capability/reasons.py  (minimal; M6.1 grows it)
class ReasonCode(StrEnum): DISPLAY_NOT_DETECTED; LOADER_MISSING; VOLUME_OFFLINE
@dataclass(frozen=True)
class Reason: code: ReasonCode; evidence: tuple[tuple[str, str], ...] = (); remedy: str = ""
```

### 2.1 `scanner/exclude.py` — pure
```python
class RuleKind(Enum): FOLDER = "folder"; FILE = "file"; PATTERN = "pattern"
@dataclass(frozen=True)
class Rule:
    id: int; kind: RuleKind
    value: str                      # FOLDER/FILE: absolute path ("~/" allowed), or volume-relative if volume_id
    group_id: int | None = None     # PATTERN: glob
    root: str | None = None         # absolute root path the rule is scoped to; None = everywhere
    volume_id: str | None = None
    device: int | None = None; inode: int | None = None      # FILE rules only
    enabled: bool = True
@dataclass(frozen=True)
class Group: id: int; key: str; name: str; builtin: bool; locked: bool; enabled: bool
@dataclass(frozen=True)
class BuiltinGroup:
    key: str; name: str; locked: bool
    rules: tuple[tuple[RuleKind, str], ...]; exceptions: tuple[str, ...] = ()   # exceptions become includes
BUILTIN_GROUPS: tuple[BuiltinGroup, ...]   # keys: system, snapshots, caches, code, games, ui_assets, app_data
@dataclass(frozen=True)
class RuleHit: rule_id: int; kind: RuleKind; group_id: int | None
class PatternErrorCode(StrEnum): EMPTY; MATCHES_EVERYTHING; TOO_LONG; TOO_MANY_GLOBSTARS; NUL; BAD_CLASS
class PatternError(ValueError): code: PatternErrorCode
def validate_rule(kind: RuleKind, value: str) -> None        # raises PatternError; FOLDER "/" is MATCHES_EVERYTHING
def compile_matcher(rules: Iterable[Rule], groups: Iterable[Group], *, includes: Iterable[str] = (),
                    home: str, mounts: Mapping[str, str] = {}) -> Matcher   # mounts: volume_id → mountpoint
class Matcher:
    inert_rule_ids: frozenset[int]                           # volume rules whose volume is not in `mounts`
    def match(self, path: str, is_dir: bool) -> RuleHit | None      # walker: ancestors already cleared
    def match_inode(self, device: int, inode: int) -> RuleHit | None # FILE rules, rename-proof; no stat needed
    def match_path(self, path: str) -> RuleHit | None  # catalogue rows: tests every ancestor as dir, then the file
```
Semantics (each line is a test case):
- Paths are absolute POSIX `str`, no trailing `/`, not resolved, **case-sensitive, no Unicode normalisation**.
- A disabled rule, a rule in a disabled group, or an inert volume rule never matches. Locked group ⇒ always enabled.
- Volume rule: effective value = `mounts[volume_id] + "/" + value`. `root`-scoped rule: only paths under `root`.
- **Precedence:** 1 FILE (exact path; or inode via `match_inode`) › 2 FOLDER › 3 PATTERN; first level that hits wins;
  within PATTERN the lowest rule id wins. The hit is what the walker records.
- **Includes** (enabled roots + builtin `exceptions` + nothing else). Let `I` = deepest include that is `path` or an
  ancestor. FOLDER: deepest rule `F` at/above `path` hits unless `I` is strictly deeper than `F` — a *locked* rule
  ignores `I`. PATTERN: a rule of a **builtin** group is suppressed beneath `I` iff the pattern matches `I` or an
  ancestor of `I` (precomputed at compile time); user patterns and FILE rules are never suppressed. So root
  `~/Games/pack` beats *Game libraries*, while `**/node_modules/**` still prunes inside a user root.
- **Globs:** `*` = any run without `/`; `?` = one char not `/`; `[abc] [a-z] [!abc]` = one char not `/`; `**` is
  special only as a whole segment = zero or more segments (`a**b` ≡ `a*b`). Leading `/` or `~/` = anchored to the
  filesystem root / `home`. No leading `/`: no `/` inside → matched against the **basename** at any depth; otherwise
  ≡ `**/` + pattern. With `root` set, matching is against the path relative to `root`. Trailing `/` = directories
  only. `X/**` matches everything beneath `X` **and the directory `X` itself** (so it is pruned, never entered). A
  pattern that matches a directory excludes its subtree.
- Matching is segment-wise (per-segment translation + DP over `**`); never one whole-path regex; limits: 1024
  chars, ≤ 4 `**`. Fast paths for `**/NAME/**` and basename-only patterns. Budget: ≥ 200k `match()`/s with builtins.
- Refused (`MATCHES_EVERYTHING`): after normalisation every segment is `*` or `**` (`*`, `**`, `/**`, `**/*`, `*/**`),
  or the pattern matches all of the probe paths `/a`, `/home/u/p.jpg`, `/mnt/d/e/f.png`.

### 2.2 `scanner/displays.py`
```python
class DisplaySource(StrEnum): GDK = "gdk"; DRM = "drm"; XRANDR = "xrandr"; DECLARED = "declared"
@dataclass(frozen=True)
class Display:
    name: str; width: int; height: int          # physical px AFTER rotation; both > 0
    scale: float = 1.0; primary: bool = False; source: DisplaySource = DisplaySource.DECLARED
@dataclass(frozen=True)
class ProbeAttempt: source: DisplaySource; ok: bool; detail: str       # evidence, one per probe tried
@dataclass(frozen=True)
class DisplayDetection:
    displays: tuple[Display, ...]; attempts: tuple[ProbeAttempt, ...]
    reason: Reason | None      # Reason(DISPLAY_NOT_DETECTED, evidence=attempts, remedy="--display WxH") iff displays == ()
class DisplayProbe(Protocol):
    source: DisplaySource
    def probe(self) -> tuple[Display, ...]: ...         # () = nothing found; raising is caught by detect()
Runner = Callable[[Sequence[str], float], str | None]   # argv, timeout → stdout; None if absent/failed/timeout
class DrmDisplayProbe:  def __init__(self, root: Path = Path("/")) -> None
class XrandrProbe:      def __init__(self, env: Mapping[str, str], run: Runner = default_runner) -> None
def parse_drm_connector(dirname: str, status: str, enabled: str | None, modes: str) -> Display | None  # pure
def parse_xrandr(text: str) -> tuple[Display, ...]                                                    # pure
def parse_declared(text: str) -> tuple[Display, ...]      # "3840x2160,1920x1080"; raises DisplaySpecError
def detect(probes: Sequence[DisplayProbe], declared: Sequence[Display] = ()) -> DisplayDetection
def service_probes(root: Path, env: Mapping[str, str]) -> list[DisplayProbe]   # [Drm, Xrandr if DISPLAY set]
```
- DRM: `<root>/sys/class/drm/card*-*/`; `status` stripped == `connected`; first line of `modes` matching
  `^(\d+)x(\d+)`; name = dirname minus `cardN-`; scale 1.0; if any connected connector has `enabled`=`enabled`, only
  those count; primary = first of (eDP|LVDS|DSI)*, else first by name. Unreadable/garbage files → skipped + attempt detail.
- xrandr: ` connected [primary] WxH+X+Y [rotation]` — geometry is already rotated; output without geometry skipped;
  if a `*` mode exists and differs from geometry (scaled framebuffer) use the mode, swapped for left/right.
- declared: `\d{3,5}x\d{3,5}` (also `×`), 320 ≤ each ≤ 16384, names `declared-1…`, max 8, duplicates collapse.
- `detect`: first probe returning non-empty wins (exceptions → failed attempt); declared always appended; a declared
  display equal in size to a detected one is dropped; exactly one `primary` (first detected if none flagged).
- GDK: `viewmodels/gdk_displays.py::GdkDisplayProbe` (imports `Gdk` from `src.gtk_version`; `viewmodels` is outside
  the no-`gi` contract; `pages/ui` may not import `scanner`). Size = geometry × `scale_factor`; name = connector
  (GTK4) / model / `monitor-N`. GUI chain: `[GdkDisplayProbe(), *service_probes(...)]`. Also owns `monitors-changed`.

### 2.3 `catalogue/ideal.py`
```python
DEFAULT_THRESHOLD_PCT = 15; MAX_THRESHOLD_PCT = 40; NEAR_CROP_PCT = 25; NEAR_COVER_PCT = 90
class Verdict(StrEnum): IDEAL = "ideal"; NEAR = "near"; NO = "no"
class Test(StrEnum): COVERS; CROP; ORIENTATION; INTEGRITY
@dataclass(frozen=True)
class ImageDims: width: int; height: int; has_alpha: bool = False; is_animated: bool = False; decodable: bool = True
@dataclass(frozen=True)
class IdealVerdict: verdict: Verdict; exact: bool; crop_loss: float; coverage: float; failed: tuple[Test, ...]
def evaluate(image: ImageDims, display: Display, threshold_pct: int = DEFAULT_THRESHOLD_PCT) -> IdealVerdict
def explain(image: ImageDims, display: Display, v: IdealVerdict) -> str
def rebuild(conn: sqlite3.Connection, threshold_pct: int, image_ids: Sequence[int] | None = None) -> int
def set_pin(conn, image_id: int, pinned: Literal["in", "out"] | None) -> None
```
Definitions (w,h = image after EXIF rotation; W,H = display). All decisions in **integer arithmetic** so Python and
SQL agree bit-for-bit; the REAL columns are for display only.
- `a = w*H`, `b = W*h`. Fill mode scales by `max(W/w, H/h)` and centre-crops; the kept fraction of the image area is
  `min(a,b)/max(a,b)` ⇒ `crop_loss = 1 − min(a,b)/max(a,b)` (size-independent; 16:10 on 16:9 = 0.100, 3:2 = 0.156, 4:3 = 0.250).
- COVERS: `w ≥ W and h ≥ H`. `coverage = min(1, w/W, h/H)` (linear; `1 − coverage` = "N % too small").
- CROP(t): `100*min(a,b) ≥ (100−t)*max(a,b)`. ORIENTATION fails iff one is landscape (`w>h`) and the other portrait.
- INTEGRITY: `decodable and not is_animated and not has_alpha`. `exact = (w == W and h == H)`.
- IDEAL ⇔ all four pass. NEAR ⇔ not IDEAL ∧ INTEGRITY ∧ ORIENTATION ∧ `10w ≥ 9W ∧ 10h ≥ 9H` ∧ CROP(25); `failed`
  names COVERS and/or CROP. Otherwise NO. `threshold_pct` outside 0..40 → `ValueError`.
- Excluded/missing are **not** part of the verdict: they are filtered when the segment is queried (D7).
```sql
-- rebuild: DELETE FROM ideal_image [WHERE image_id IN ids]; then (":t" bound, never formatted)
INSERT INTO ideal_image(image_id, display_id, verdict, exact, crop_loss, coverage)
SELECT i.id, d.id,
  CASE WHEN i.width >= d.width AND i.height >= d.height
        AND 100*min(i.width*d.height, d.width*i.height) >= (100-:t)*max(i.width*d.height, d.width*i.height)
       THEN 'ideal' ELSE 'near' END,
  i.width = d.width AND i.height = d.height,
  1.0 - CAST(min(i.width*d.height, d.width*i.height) AS REAL) / max(i.width*d.height, d.width*i.height),
  min(1.0, CAST(i.width AS REAL)/d.width, CAST(i.height AS REAL)/d.height)
FROM image i JOIN display d ON (d.connected = 1 OR d.source = 'declared')
WHERE i.probe_status = 'ok' AND i.has_alpha = 0 AND i.is_animated = 0 AND i.width > 0 AND i.height > 0
  AND NOT ((i.width > i.height AND d.width < d.height) OR (i.width < i.height AND d.width > d.height))
  AND 10*i.width >= 9*d.width AND 10*i.height >= 9*d.height
  AND 100*min(i.width*d.height, d.width*i.height) >= 75*max(i.width*d.height, d.width*i.height);
```
Segment membership at query time = (`verdict='ideal'` for ≥ 1 target display ∪ pin `in`) − pin `out`, joined to
`image` with `missing = 0 AND excluded_by IS NULL`. *Every display* = ideal row count equals target-display count.

### 2.4 `catalogue/db.py`, `migrations/`, `model.py`
```python
LATEST_SCHEMA = 1
class CatalogueError(Exception): ...
class SchemaTooNewError(CatalogueError): found: int; supported: int     # DB is never modified
class CatalogueBusyError(CatalogueError): ...      # busy_timeout expired
class CatalogueCorruptError(CatalogueError): ...   # file is never auto-deleted
class ScanInProgressError(CatalogueError): pid: int | None
def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection
def open_catalogue(path: Path | None = None) -> sqlite3.Connection     # mkdir 0700, connect, migrate, seed_builtins, recover
def migrate(conn) -> int                                               # → new user_version
def seed_builtins(conn, groups: Sequence[BuiltinGroup]) -> None        # idempotent upsert by group.key/(kind,value); keeps `enabled`
def recover(conn) -> int                                               # scans with finished IS NULL → 'interrupted'
def scan_lock(db_path: Path) -> ContextManager[None]                   # fcntl.flock(<db>.scanlock, LOCK_EX|LOCK_NB)
def load_rules(conn) -> tuple[list[Rule], list[Group]]
def add_rule(conn, kind, value, *, group: str | None, root: str | None, volume_id=None, device=None, inode=None) -> int
def remove_rule(conn, rule_id: int) -> None;  def set_rule_enabled(conn, rule_id, on: bool) -> None
def set_group_enabled(conn, name_or_key: str, on: bool) -> None        # locked group → CatalogueError
def apply_exclusions(conn, matcher: Matcher) -> FlagDelta              # recompute image.excluded_by for ALL rows
def preview_rule(conn, matcher_with_candidate: Matcher, rule_id: int) -> RulePreview   # images, folders, first 5 paths; read-only
def save_display_snapshot(conn, detection: DisplayDetection, now: int) -> tuple[list[int], bool]  # target ids, changed?
def get_setting(conn, key: str, default: T) -> T;  def set_setting(conn, key: str, value: object) -> None   # JSON
class ChangeKind(StrEnum): IMAGES_UPSERTED; IMAGES_FLAGGED; IDEAL_REBUILT; DISPLAYS_CHANGED; ROOTS_CHANGED; RULES_CHANGED
@dataclass(frozen=True)
class Change: kind: ChangeKind; image_ids: tuple[int, ...] = (); scan_id: int | None = None
class ChangeFeed:  def subscribe(self, cb: Callable[[Change], None]) -> Callable[[], None]; def emit(self, c: Change) -> None
```
Connection policy: `isolation_level=None`, explicit `BEGIN IMMEDIATE` for writes; `journal_mode=WAL`,
`synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000`, `row_factory=sqlite3.Row`; read connections add
`query_only=ON` and are **one per thread**, never shared. Exactly one write connection per process, owned by the
writer thread (§3). Migrations: `MIGRATIONS: tuple[Migration(version:int, name:str, apply:Callable[[Connection],None])]`;
each runs in one transaction that also sets `user_version`; before migrating a DB with `user_version ≥ 1` a copy is
made with the sqlite backup API to `catalogue.db.bak-v<n>`; `user_version > LATEST_SCHEMA` → `SchemaTooNewError`.
`m0001_initial` executes `schema.sql` (frozen once released; later changes are new migrations only).
Settings keys (JSON in `setting`): `scan.min_file_bytes`=204800, `scan.max_file_bytes`=268435456,
`scan.min_long_edge`=1280, `ideal.threshold_pct`=15, `thumbs.budget_bytes`=536870912, `scan.network_optin`=[],
`first_run_done`=false. `model.py`: frozen `ImageRow`, `RootRow`, `VolumeRow`, `DisplayRow`, `ScanRow`, `RuleRow`,
`FlagDelta(flagged:int, cleared:int)`, `RulePreview`, `Page[T](rows, total, offset)` — 1:1 with the columns below.

```sql
CREATE TABLE setting(key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
CREATE TABLE volume(                       -- concept forgot it: UUID memory, online state, "scan this drive?" answer
  volume_id TEXT PRIMARY KEY, label TEXT, fstype TEXT, last_mount TEXT, removable INTEGER NOT NULL DEFAULT 0,
  network INTEGER NOT NULL DEFAULT 0, stable_inodes INTEGER NOT NULL DEFAULT 1,
  scan_answer TEXT CHECK (scan_answer IN ('yes','no')), online INTEGER NOT NULL DEFAULT 0, last_seen INTEGER
) WITHOUT ROWID;
CREATE TABLE root(
  id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, kind TEXT NOT NULL CHECK (kind IN ('xdg','system','volume','user')),
  enabled INTEGER NOT NULL DEFAULT 1, volume_id TEXT, last_scan INTEGER, last_scan_id INTEGER
);
CREATE TABLE exclusion_group(
  id INTEGER PRIMARY KEY, key TEXT UNIQUE, name TEXT NOT NULL UNIQUE,      -- key: stable id of a builtin, NULL for user groups
  builtin INTEGER NOT NULL DEFAULT 0, locked INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE exclusion(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('folder','file','pattern')), value TEXT NOT NULL,
  volume_id TEXT, device INTEGER, inode INTEGER,
  root_id INTEGER REFERENCES root(id) ON DELETE CASCADE,
  group_id INTEGER REFERENCES exclusion_group(id) ON DELETE SET NULL,
  builtin INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1, created INTEGER, note TEXT
);
CREATE UNIQUE INDEX exclusion_identity ON exclusion(kind, value, ifnull(volume_id,''), ifnull(root_id,0)); -- NULLs are distinct in UNIQUE()
CREATE TABLE image(
  id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, dir TEXT NOT NULL, name TEXT NOT NULL,
  root_id INTEGER REFERENCES root(id) ON DELETE SET NULL, volume_id TEXT,
  device INTEGER, inode INTEGER, mtime_ns INTEGER, size INTEGER,
  width INTEGER, height INTEGER,               -- AFTER EXIF rotation
  exif_orientation INTEGER, format TEXT, has_alpha INTEGER NOT NULL DEFAULT 0,
  is_animated INTEGER NOT NULL DEFAULT 0, has_icc INTEGER NOT NULL DEFAULT 0, aspect REAL, megapixels REAL,
  probe_status TEXT NOT NULL DEFAULT 'ok' CHECK (probe_status IN ('ok','truncated','zero_byte','unsupported','over_budget','error')),
  probe_error TEXT,
  score INTEGER, badges TEXT, palette TEXT, dhash INTEGER,                 -- M2, stay NULL
  thumb_key TEXT, thumb_status TEXT CHECK (thumb_status IN ('ok','failed','too_large')),
  first_seen INTEGER, last_seen INTEGER, seen_scan INTEGER, missing INTEGER NOT NULL DEFAULT 0,
  excluded_by INTEGER REFERENCES exclusion(id) ON DELETE SET NULL
);                                            -- M3 adds fit_mode/focal point in its own table, not here
CREATE INDEX image_inode ON image(device, inode);   CREATE INDEX image_dir ON image(dir);
CREATE INDEX image_volume ON image(volume_id);      CREATE INDEX image_root ON image(root_id, seen_scan);
CREATE INDEX image_name ON image(name COLLATE NOCASE);  CREATE INDEX image_first_seen ON image(first_seen);
CREATE INDEX image_size ON image(size);             CREATE INDEX image_mp ON image(megapixels);
CREATE INDEX image_excluded ON image(excluded_by) WHERE excluded_by IS NOT NULL;
CREATE TABLE display(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL, scale REAL NOT NULL DEFAULT 1.0,
  is_primary INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL CHECK (source IN ('gdk','drm','xrandr','declared')),
  connected INTEGER NOT NULL DEFAULT 1, first_seen INTEGER, last_seen INTEGER, UNIQUE(name, width, height)
);
CREATE TABLE scan(
  id INTEGER PRIMARY KEY, started INTEGER NOT NULL, finished INTEGER, pid INTEGER, root_ids TEXT, display_set TEXT,
  threshold_pct INTEGER, found INTEGER DEFAULT 0, probed INTEGER DEFAULT 0, unchanged INTEGER DEFAULT 0,
  ideal INTEGER DEFAULT 0, skipped INTEGER DEFAULT 0, issues TEXT,          -- JSON {issue kind: count}
  reason TEXT,                                                              -- e.g. DISPLAY_NOT_DETECTED + evidence JSON
  result TEXT NOT NULL DEFAULT 'running' CHECK (result IN ('running','ok','cancelled','interrupted','error'))
);
CREATE TABLE scan_skip(scan_id INTEGER NOT NULL REFERENCES scan(id) ON DELETE CASCADE, rule_id INTEGER NOT NULL,
  dirs INTEGER NOT NULL DEFAULT 0, files INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(scan_id, rule_id)) WITHOUT ROWID;
CREATE TABLE scan_issue(id INTEGER PRIMARY KEY, scan_id INTEGER NOT NULL REFERENCES scan(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, path TEXT NOT NULL, detail TEXT);                     -- first 500 per kind per scan; totals in scan.issues
CREATE TABLE ideal_image(
  image_id INTEGER NOT NULL REFERENCES image(id) ON DELETE CASCADE,
  display_id INTEGER NOT NULL REFERENCES display(id) ON DELETE CASCADE,
  verdict TEXT NOT NULL CHECK (verdict IN ('ideal','near')), exact INTEGER NOT NULL, crop_loss REAL NOT NULL, coverage REAL NOT NULL,
  PRIMARY KEY (image_id, display_id)) WITHOUT ROWID;
CREATE INDEX ideal_by_display ON ideal_image(display_id, verdict);
CREATE TABLE ideal_pin(image_id INTEGER PRIMARY KEY REFERENCES image(id) ON DELETE CASCADE,
  pinned TEXT NOT NULL CHECK (pinned IN ('in','out')));
```
Deferred to the milestone that first uses them (D9): `collection`, `collection_item`, `tag`, `image_tag`, `apply_event`.

### 2.5 `catalogue/queries.py` — parameterised only
```python
class Segment(StrEnum): ALL; IDEAL; NEAR_MISS
class Sort(StrEnum): NAME; DATE_ADDED; SIZE; RESOLUTION          # SCORE arrives in M2 → UnsupportedSort until then
class Orientation(StrEnum): LANDSCAPE; PORTRAIT; SQUARE
class AspectBucket(StrEnum): R16_9; R16_10; R3_2; R4_3; R21_9; R1_1; OTHER     # |aspect − target| ≤ 0.03
@dataclass(frozen=True)
class QuerySpec:
    segment: Segment = Segment.ALL; display_id: int | None = None; every_display: bool = False; exact: bool | None = None
    search: str = ""; min_width: int | None = None; min_height: int | None = None; min_long_edge: int | None = None
    aspect: AspectBucket | None = None; orientation: Orientation | None = None; formats: tuple[str, ...] = ()
    root_id: int | None = None; dir_prefix: str | None = None
    missing: bool | None = None          # None = both (missing rows are dimmed, not hidden); True/False = only/none
    include_excluded: bool = False; include_unusable: bool = False         # probe_status != 'ok'
    sort: Sort = Sort.NAME; descending: bool = False; limit: int = 200; offset: int = 0
@dataclass(frozen=True)
class CompiledQuery: sql: str; params: tuple[object, ...]
def build(spec: QuerySpec) -> CompiledQuery;   def build_count(spec: QuerySpec) -> CompiledQuery
def fetch_page(conn, spec: QuerySpec) -> Page[ImageRow]
def get_image(conn, id_or_path: int | str) -> ImageRow | None
def verdicts_for(conn, image_id: int) -> list[tuple[DisplayRow, IdealVerdict]]      # `linwp show`
def segment_counts(conn) -> dict[str, int]                   # all, ideal, near, exact, every, per display id
```
Rules: every value is a `?` parameter; SQL text is assembled only from module-level constant fragments chosen by
enum (`ORDER BY` from a `dict[Sort, str]`); `limit` clamped 1..1000; search = `LIKE ? ESCAPE '\'` on `name` and
`dir` with `% _ \` escaped; ties broken by `id`. Test: no f-string/`%`/`.format` reaches `execute` (AST check of the module).

### 2.6 `scanner/roots.py`
```python
class RootKind(StrEnum): XDG; SYSTEM; VOLUME; USER
@dataclass(frozen=True)
class Mount: target: str; source: str; fstype: str; uuid: str | None; label: str | None; removable: bool; network: bool; stable_inodes: bool
@dataclass(frozen=True)
class RootProposal: path: str; kind: RootKind; volume_id: str | None; default_on: bool; reason: str | None  # e.g. "network filesystem (nfs)"
class ScanSource(Protocol):  def propose(self) -> list[RootProposal]: ...
def parse_findmnt(json_text: str) -> list[Mount]                               # pure; findmnt --json -o TARGET,SOURCE,FSTYPE,UUID,LABEL,OPTIONS
def parse_user_dirs(text: str, home: str) -> str | None                        # pure; ~/.config/user-dirs.dirs → PICTURES
class MountTable:  def __init__(self, mounts): ...;  def mount_for(self, path: str) -> Mount | None; def by_uuid(self, u) -> Mount | None
def load_mounts(run: Runner = default_runner) -> MountTable
def default_sources(home: Path, root: Path, mounts: MountTable) -> list[ScanSource]   # Xdg, System, Volumes; only existing dirs proposed
```
Local fs allow-list `ext4 btrfs xfs vfat exfat ntfs3 ntfs fuseblk f2fs`; network = `nfs* cifs smb3 sshfs fuse.*`
(proposed with `default_on=False` + reason, never silently dropped); `stable_inodes=False` for `vfat exfat ntfs* fuseblk`.

### 2.7 `scanner/walker.py`, `scanner/probe.py`
```python
# walker.py
FileKey = tuple[int, int, int, int]                       # device, inode, mtime_ns, size
class IssueKind(StrEnum): PERMISSION_DENIED; BROKEN_SYMLINK; VANISHED; IO_ERROR; UNENCODABLE_NAME; SYMLINK_LOOP; NOT_REGULAR; OTHER_FILESYSTEM
@dataclass(frozen=True)
class ScanIssue: kind: IssueKind; path: str; detail: str = ""
@dataclass(frozen=True)
class Candidate: path: str; root: str; key: FileKey; moved_from_id: int | None = None
@dataclass(frozen=True)
class WalkOptions: extensions: frozenset[str] = DEFAULT_EXTENSIONS; min_file_bytes: int = 204_800; max_file_bytes: int = 268_435_456
class KnownFiles(Protocol):                                # in-memory snapshot, loaded by ingest before the walk
    def key_for(self, path: str) -> FileKey | None: ...
    def by_inode(self, device: int, inode: int) -> tuple[int, str, FileKey] | None: ...   # id, old path, key
class FileSystem(Protocol):                                # OsFileSystem default; tests inject a counting double
    def scandir(self, path: str) -> ContextManager[Iterator[os.DirEntry[str]]]: ...
    def stat(self, path: str, *, follow_symlinks: bool = True) -> os.stat_result: ...
    def lexists(self, path: str) -> bool: ...
class WalkListener(Protocol):
    def on_dir(self, path: str, candidates: int) -> None: ...
    def on_skip(self, hit: RuleHit, is_dir: bool) -> None: ...
    def on_unchanged(self, path: str) -> None: ...          # ingest bumps seen_scan without opening the file
    def on_issue(self, issue: ScanIssue) -> None: ...
def walk(root: str, matcher: Matcher, known: KnownFiles, out: "queue.Queue[Candidate | None]", listener: WalkListener,
         cancel: CancelToken, options: WalkOptions = WalkOptions(), fs: FileSystem = OsFileSystem(),
         stable_inodes: bool = True) -> WalkResult       # WalkResult(complete: bool, failed_dirs: tuple[str, ...])
# probe.py
class ProbeStatus(StrEnum): OK; TRUNCATED; ZERO_BYTE; UNSUPPORTED; OVER_BUDGET; ERROR
@dataclass(frozen=True)
class DecodeBudget: max_pixels: int = 100_000_000; max_jpeg_pixels: int = 400_000_000; max_seconds: float = 5.0
@dataclass(frozen=True)
class ProbeResult:
    candidate: Candidate; key: FileKey                     # key re-read with fstat on the opened fd
    status: ProbeStatus; error: str = ""; width: int = 0; height: int = 0; exif_orientation: int = 1
    format: str = ""; has_alpha: bool = False; is_animated: bool = False; has_icc: bool = False
    thumb_key: str | None = None; thumb_status: str | None = None; seconds: float = 0.0
class ThumbSink(Protocol):   def store(self, image: "PIL.Image.Image", key: str, cancel: CancelToken) -> str: ...  # → 'ok'|'failed'
def content_key(fd: int, size: int) -> str               # blake2b-128 hex of size ‖ first 256 KiB ‖ last 64 KiB
def probe_file(c: Candidate, budget: DecodeBudget, thumbs: ThumbSink | None, cancel: CancelToken) -> ProbeResult  # never raises
def supported_formats() -> dict[str, bool]               # by Pillow feature detection; drives LOADER_MISSING once per format
```
Walk rules, in this order per `DirEntry` (`is_dir/is_file(follow_symlinks=False)` use `d_type`, no `stat`):
name not UTF-8-encodable → issue, skip · `matcher.match(path, is_dir)` → `on_skip`, **no stat, no descent** ·
`matcher.match_inode(dir_device, entry.inode())` · dir: descend unless other `st_dev` (mount boundary →
`OTHER_FILESYSTEM`; mounts are their own roots) or `(dev, ino)` already visited (`SYMLINK_LOOP`); dir symlinks followed
only on the same device · file: extension filter, then one `stat`; not `S_ISREG` → `NOT_REGULAR`; size bounds;
`(dev, ino)` already seen this scan → skipped (hardlink/bind) · `known.key_for(path) == key` → `on_unchanged` ·
else, if `stable_inodes` and `known.by_inode` gives a row with equal mtime/size whose old path no longer
`lexists` → `Candidate(moved_from_id=…)` (ingest updates `path`, no re-probe); else new `Candidate`.
`out.put` blocks (0.2 s timeout loop polling `cancel`) — that is the back-pressure. `None` = end of walk.
A directory that raises is recorded in `failed_dirs`; nothing beneath it may be marked missing.
Probe rules: `os.open(O_RDONLY|O_NONBLOCK|O_CLOEXEC)` → `fstat` must be regular (a FIFO named `x.jpg` must not hang) ·
size 0 → `ZERO_BYTE` · `Image.open` (header only; `Image.MAX_IMAGE_PIXELS = None`, our budget replaces Pillow's) ·
pixels over budget → `OVER_BUDGET` with dimensions recorded, **no decode** · else `draft()` for JPEG, `load()`,
→ `OSError` = `TRUNCATED` · thumbnail via `thumbs.store` · `max_seconds` is cooperative (checked between steps; the
pixel and byte caps are the hard guard — a thread cannot be killed, D12). `LOAD_TRUNCATED_IMAGES` stays False.

### 2.8 `catalogue/thumbs.py`
```python
class ThumbSize(IntEnum): NORMAL = 256; LARGE = 512
class ThumbCache:                                          # implements probe.ThumbSink
    def __init__(self, base: Path | None = None, budget_bytes: int = 536_870_912) -> None   # base = cache_dir()/"thumbnails"
    def path_for(self, key: str, size: ThumbSize) -> Path  # <base>/{normal,large}/<key[:2]>/<key>.jpg
    def store(self, image, key: str, cancel: CancelToken) -> str          # NORMAL only during a scan
    def read(self, key: str, size: ThumbSize = ThumbSize.NORMAL) -> bytes | None   # touches mtime at most once a day (LRU clock)
    def ensure_large(self, source: Path, key: str) -> bytes | None        # lazy 512, on demand
    def usage(self) -> int;  def evict(self) -> int;  def clear(self) -> int       # evict: oldest mtime first, down to 90 % of budget
```
JPEG q85, long edge = size, never upscaled, EXIF-transposed, alpha flattened on mid-grey, ICC dropped after
conversion to sRGB when cheap; written to `*.tmp` + `os.replace` (atomic), dirs 0700. Key exists → `store` is a no-op.
Keys are validated `^[0-9a-f]{32}$` before touching the filesystem. `evict()` runs at scan end, never mid-scan.

### 2.9 `catalogue/ingest.py`, CLI, view models
```python
class CatalogueWriter:                                     # the ONE writer thread
    def __init__(self, db_path: Path, feed: ChangeFeed) -> None
    def submit(self, fn: Callable[[sqlite3.Connection], T]) -> Future[T]   # runs fn inside BEGIN IMMEDIATE … COMMIT
    def close(self, timeout: float = 5.0) -> None
@dataclass(frozen=True)
class ScanProgress: scan_id: int; dirs: int; found: int; unchanged: int; probed: int; ideal: int; excluded: int; issues: int; walk_done: bool; current_dir: str
@dataclass(frozen=True)
class ScanSummary: scan_id: int; result: str; progress: ScanProgress; detection: DisplayDetection; seconds: float
class ScanListener(Protocol):  def on_progress(self, p: ScanProgress) -> None: ...   # ≤ 10 Hz, called on a worker thread
class ScanService:
    def __init__(self, db_path, writer: CatalogueWriter, thumbs: ThumbCache, probes: Sequence[DisplayProbe], mounts: Callable[[], MountTable]) -> None
    def scan(self, root_ids: Sequence[int] | None, declared: Sequence[Display], listener: ScanListener, cancel: CancelToken) -> ScanSummary
    def refresh_displays(self, declared: Sequence[Display] = ()) -> DisplayDetection   # snapshot + ideal.rebuild, opens no image
```
`scan()` order: `scan_lock` → mounts/volumes (online flags, path healing by `volume_id`) → `detect()` → snapshot +
`scan` row → rebuild ideal if the display set changed → compile matcher → per root: walker thread → bounded
`Queue(512)` → N = `min(4, cpu)` probe loops on a **scan-private** `ThreadPoolExecutor` → `Queue(256)` → writer
batches (≤ 200 rows or 250 ms) = upsert + `ideal.rebuild(ids)` + `seen_scan`, then `feed.emit` → after a *complete,
uncancelled* root walk: `missing = 1` for that root's rows with `seen_scan < id`, `excluded_by IS NULL`, not under a
`failed_dir`; `missing = 0` for everything seen → `thumbs.evict()` → finish `scan` row.
CLI (`cmd_*.py`, `linwp.py` keeps parser + dispatch, `immediate_scheduler`): `scan [--add PATH] [--display …]`,
`list` (QuerySpec flags), `show <id|path>`, `exclude add|remove|list|test|group enable|disable NAME`, `displays`.
`--json` = one object `{"ok":…, …}`; text output escapes control characters in paths (`\n` → `\\n`). SIGINT →
`cancel.cancel()` → exit 130; catalogue errors → exit 1 with the class name in JSON; `DISPLAY_NOT_DETECTED` → exit 0,
`"reason"` in JSON, remedy on stderr. `exclude test` always exits 0; JSON `{"scanned": bool, "rule": …}`.
View models (gi-free, constructor takes `services` and `scheduler: Scheduler`; observers are plain callbacks):
`AppServices` (composition root, built in `main.py`), `ScanVM` (start/cancel/progress, one per app),
`SourcesVM` (roots, volumes, rules/groups, preview, test-a-path, displays strip), `BrowseVM` (`QuerySpec` state,
paged window, selection, segment counts, `load_thumb(id, cb: Callable[[bytes | ThumbPlaceholder], None])` — widgets
get bytes, never paths). VMs expose their own frozen DTOs; `pages/ui` never see `catalogue` types.

## 3. Threading model
- **UI thread:** widgets + VM state only. Every DB read runs through `threads.run_in_worker` on a per-thread
  read connection; results return via the injected scheduler (`glib_scheduler` / `immediate_scheduler`).
- **Writer thread** (`lwp-writer`, one per process): owns the only write connection; everything that mutates
  (scan batches, rules, pins, settings, displays) goes through `CatalogueWriter.submit`. Short transactions only.
- **Scan:** 1 walker thread + N probe threads in a scan-private pool (the shared 4-thread pool must stay free for
  queries/thumbnail reads). Both queues are bounded; a slow writer stalls probes, which stall the walker.
- **To the UI:** writer commits → `ChangeFeed.emit` (writer thread) → VM coalesces (≥ 100 ms) → `scheduler(cb)`.
  Progress likewise, ≤ 10 Hz. Widgets never see a worker thread. Another *process* writing (CLI while the GUI is
  open) is noticed by comparing `PRAGMA data_version` when a page is shown — no polling.
- **Cancellation:** one `CancelToken` per scan, polled at every dirent, queue put/get and probe step. On cancel:
  walker stops, queues drain without probing, the open batch commits, `scan.result='cancelled'`, **no missing
  marking**. App shutdown = cancel + `writer.close()` + `threads.shutdown()`; no thread outlives the window.
- **kill -9:** WAL keeps every committed batch; the in-flight batch is lost whole. The `flock` dies with the
  process. Next `open_catalogue` → `recover()` marks the scan `interrupted`. Thumbnails are written before their row
  commits, so a row never points at a missing thumb; orphan thumbs age out by LRU. Rescan converges because skip
  decisions use committed `(device, inode, mtime_ns, size)` only and missing-marking needs a complete walk.
- A second scanner (GUI + `linwp scan`) gets `ScanInProgressError`; plain writes from two processes serialise on
  `BEGIN IMMEDIATE` + `busy_timeout`, surfacing `CatalogueBusyError` rather than hanging.

## 4. Build order and gates (every phase ends with `make check` green and adds no unused public stub)
| Phase | Work (parallel lanes) | Test files · key cases |
| --- | --- | --- |
| P1 | this contract | — |
| P2 | scaffold (§1 row 1); no behaviour | `test_cancel.py`, `test_reasons.py`, `test_paths.py` (XDG overrides stay under tmp `$HOME`); `imagegen` makes JPEG/PNG/WebP/GIF, EXIF-rotated, CMYK, 16-bit, truncated, zero-byte |
| P3-A | `exclude.py` | `test_exclude_glob.py`: every §2.1 semantics line; `**` zero segments; `X/**` prunes `X`; basename vs anchored; classes, `[!…]`, `BAD_CLASS`; unicode, NFC≠NFD, space, **newline**, `*`-in-filename literal via class; case-sensitivity; refusal table; 1024/4-`**` limits; pathological `*a*a*a*…` on a 255-char name < 5 ms. `test_exclude_precedence.py`: file › folder › pattern; include deeper than folder; include vs builtin pattern; include vs **locked**; user pattern not suppressed; group off/on; root-scoped; volume rule mounted / remounted elsewhere / inert; `match_inode` after rename; `match_path` ancestor pruning; builtin table sanity (each builtin validates, `system` locked); 200k matches/s |
| P3-B | `displays.py` + fake roots `tests/fakeroot/drm-{one-panel,laptop-external,hidpi,disabled-output,none,garbage}` | `test_displays_drm.py`: each fixture; empty `modes`; status `unknown`; non-UTF-8 bytes; missing `/sys`. `test_displays_parse.py`: xrandr normal/rotated left/scaled framebuffer/disconnected/garbage/empty; declared ok, `×`, whitespace, `0x0`, `99999x1`, 9 entries, junk. `test_displays_chain.py`: first non-empty wins; raising probe; runner timeout/absent binary; declared dedupe; single primary; `DISPLAY_NOT_DETECTED` shape with evidence |
| P4-C | `model, db, schema.sql, migrations, queries` | `test_migrations.py`: fresh → v1; idempotent reopen; **newer `user_version` → `SchemaTooNewError`, file bytes unchanged**; failing migration rolls back; backup file made; not-a-database → `CatalogueCorruptError`, file kept. `test_db.py`: pragmas; FK on; **locked DB (second connection holds `BEGIN IMMEDIATE`) → `CatalogueBusyError` within timeout**; `scan_lock` contention; `recover()`; seed idempotent + keeps user toggles; exclusion identity with NULLs; `apply_exclusions` flag/clear both ways without touching other columns; removing a rule re-evaluates overlapping rules. `test_queries.py`: each filter alone + combined; **injection strings in every text field** (`'; DROP TABLE image;--`, `%`, `_`, `\`); AST no-format check; sort stability; paging; missing/excluded/unusable defaults; 20k rows < 100 ms |
| P4-D | `ideal.py` | `test_ideal_evaluate.py` table: exact; larger; 16:10 & 3:2 & 4:3 on 16:9; 1:1; portrait on landscape and on rotated display; one pixel too small; alpha; animated; undecodable; threshold 0 and 40; boundary equality (4:3 at 25 %); zero/negative dims; `explain` strings. `test_ideal_sql.py`: **Python ≡ SQL on a 2k random grid**; incremental = full; pins in/out survive rebuild; excluded/missing filtered at query; display set change; 20k rows × 2 displays < 200 ms; **`builtins.open`/`Image.open` patched to raise — never called** |
| P5a-E/F/G | `roots` · `walker+probe` · `thumbs` | `test_roots.py`: findmnt JSON fixtures (nested children, network, removable, no UUID), user-dirs parsing, missing dirs not proposed. `test_walker.py` (tmp trees + `CountingFs`): **excluded dir never `scandir`ed/`stat`ed**; unchanged → zero opens; mtime/size change → candidate; move detection; hardlink once; **symlink loop, symlink to parent, cross-device**; broken symlink; chmod 000 dir → `failed_dirs`; **file vanishing between scandir and stat**; unicode, newline, surrogate-escaped names; FIFO named `.jpg`; cancel while blocked on a full queue. `test_probe.py`: nasty corpus — truncated JPEG/PNG, zero-byte, CMYK, 16-bit, EXIF 6/8 swap, animated GIF/WebP, palette+transparency, text file named `.jpg`, **header claiming 40000×40000 → `OVER_BUDGET`, no decode, < 50 ms**, > `max_file_bytes`, file replaced during probe (fstat key), vanish before open; never raises. `test_thumbs.py`: key stable across move/rename, differs on content change; layout; atomic write (no `*.tmp` left after simulated failure); no upscale; LRU order + 90 % target; bad key rejected; cache dir under tmp XDG only |
| P5b-H | `ingest` + CLI | `test_ingest.py`: end-to-end on a generated tree; rescan → probes = 0; **cancel mid-scan → consistent DB, rescan completes**; **`kill -9` of a subprocess scan → reopen, `interrupted`, rescan converges to the same row set**; missing marking only after a complete walk and never under a failed dir; volume offline → `missing`, remount elsewhere heals without duplicates; no display → scan ok + reason stored; second scanner → `ScanInProgressError`. `test_cli.py` (update M0 expectations): `scan/list/show/displays/exclude *` text + `--json`; newline path escaped; `exclude test` names the rule; `--display` junk → exit 2; `list --ideal --display NAME`; SIGINT → 130 |
| P6-I/J | view models · pages/components | `test_*_vm.py` with `immediate_scheduler`, no display: filter chips ↔ `QuerySpec`; debounce; feed coalescing; exclude → row leaves, undo → returns; pattern preview counts; refused pattern surfaces its code; segment default flips once ideal has members; `DISPLAY_NOT_DETECTED` empty state text; first run scans nothing before consent. `test_gdk_displays.py` (smoke marker). Smoke: scan a fixture root, grid fills, filter narrows, no GTK warnings, no thread left after close |
| P7 | adversary + perf: 10k fixture generator, `docs/perf.md`, acceptance 1–10 | budget assertions marked `perf`, excluded from `make check` unless `PERF=1` |

P3-A ∥ P3-B; P4-C ∥ P4-D (D codes against `schema.sql`, which C lands first — day-one commit); P5a lanes ∥; P6-J follows I's DTOs.

## 5. Decisions (D) and open questions (Q)
- **D1 Pillow only in the service layer.** "GdkPixbuf first" (M1.3) contradicts the no-`gi` contract on `scanner`.
  `probe_file` is Pillow; AVIF/HEIF/JXL report `LOADER_MISSING` (Pillow 10.2 here has none). An injected GUI-side prober is deferred.
- **D2 GDK probe lives in `viewmodels/gdk_displays.py`**, the single gi-importing VM module, guarded by a new contract.
- **D3 Integer crop/cover arithmetic**, threshold in whole percent — Python and SQL cannot drift on boundaries.
- **D4 Near misses are rows** (`ideal_image.verdict='near'`) — one rebuild, one index, trivially fast counts.
- **D5 `mtime_ns`, not `mtime`** — second resolution misses same-second rewrites.
- **D6 Content key = blake2b(size ‖ head 256 KiB ‖ tail 64 KiB)** — full hashing of a 200 GB library would dominate the scan.
- **D7 Excluded/missing filtered at query time, not baked into `ideal_image`** — exclusion toggles need no rebuild.
- **D8 `apply_exclusions` recomputes all rows in Python** (SQLite `GLOB` lets `*` cross `/`); ≤ 300 ms at 40k rows.
- **D9 Unused §7 tables deferred** (collections, tags, apply_event) — the migration runner gets a real second migration.
- **D10 Service settings live in the `setting` table**, not GSettings (needs `gi`; CLI must share them).
- **D11 The walk never crosses a mount boundary**; each mount is its own root — stops a `~/nas` mount hanging a scan.
- **D12 The seconds budget is cooperative**; byte and pixel caps are the hard limits. Subprocess decoders: not in M1.
- **D13 Thumbnails sharded by `key[:2]`**, 512 px generated lazily — 40k files in one directory and double decode cost avoided.
- **D14 `volume` table, `scan_skip`, `scan_issue`, `image.{dir,name,root_id,seen_scan,probe_status,…}` added** — required by M1.1/M1.6 but absent from §7.
- **D15 Non-UTF-8 filenames are skipped with `UNENCODABLE_NAME`** — SQLite TEXT cannot hold surrogates; reported, never silent.
- **D16 Grid is a sliding window of ≤ 600 cards** over paged queries; a 20,000-child `Gtk.FlowBox` cannot hit 60 fps.
- **Defer out of the first slice** (none touches the three user-requested features): udisks2 D-Bus toast (poll mounts at
  scan/Sources refresh instead); `wlr-randr`/`kscreen-doctor` parsers; rule export/import; moving rules between groups
  (create group + `--group` stay); drag-and-drop; Space quick-preview; "applied but excluded" marking (no apply until
  M4); Collections page beyond a read-only list of the built-in segments; eager 512 px thumbnails; FTS search.

Open — need a ruling:
- **Q1** §6.1 says a 3:2 photo passes at 15 %, but its fill-crop loss on 16:9 is 15.6 %. Raise the default to 16 %, or fix the prose? *Rec: default 16.*
- **Q2** "covers ≥ 90 % of the pixels" vs the example "1600 × 900 — 17 % too small" (linear 83 %, area 69 % — a near miss under neither). *Rec: linear coverage ≥ 90 %; the example becomes a plain "no".*
- **Q3** Is *Ideal for this desktop* "ideal for **any** target display" (rec.) or "for the primary"? Do declared displays count in *every display*? *Rec: any; yes.*
- **Q4** DRM sysfs knows neither rotation nor scale, and reports the *preferred*, not current, mode; M1.8 asks for a "rotated output" DRM fixture that cannot exist. *Rec: rotation tests move to xrandr/GDK; `linwp` in a session with `DISPLAY` still tries DRM first per spec — or should xrandr lead there?*
- **Q5** GDK geometry × integer `scale_factor` over-reports under Wayland fractional scaling. *Rec: when a DRM connector of the same name disagrees, trust DRM's size with GDK's orientation; confirm.*
- **Q6** 200 KB minimum drops many good 1080p WebP/AVIF/JPEG files. *Rec: 64 KiB; builtin groups + the 1280 px long-edge view filter handle icons.*
- **Q7** Images under `scan.min_long_edge` are stored (so rescans skip them) and hidden by a default view filter, not dropped. OK?
- **Q8** Includes beat only *builtin-group* rules, and only where the rule hits the include point itself (so `node_modules` stays pruned inside a user root); a deeper user folder rule still wins. Matches the intent of §5.1(2)?
- **Q9** Case-sensitive matching even on vfat/exfat/ntfs, and no Unicode normalisation. Acceptable for v1?
- **Q10** `Image.MAX_IMAGE_PIXELS = None` is process-global (our budget replaces it). Acceptable, given `imaging/` will share the process from M3?

---

## Rulings (team lead, 2026-09-18) — binding on implementers

| # | Ruling |
| --- | --- |
| Q1 | Default crop-loss threshold is **16 %** (so 3:2 on 16:9, 15.6 %, passes as the concept intends). Setting range stays 0–40 %. Concept §6.1 and milestones M1.5a updated. |
| Q2 | Near miss = **linear** coverage ≥ 90 % on both axes (`10·w ≥ 9·W and 10·h ≥ 9·H`), or crop loss ≤ 25 %. The concept's 1600 × 900 example was wrong and is replaced by 1760 × 990. |
| Q3 | "Ideal for this desktop" = ideal for **any** target display; *every display* / per-output are sub-segments. Declared displays count as targets. |
| Q4 | `linwp` inside a session (`DISPLAY` or `WAYLAND_DISPLAY` set): **xrandr first** (current mode + rotation), DRM sysfs second. No display server: DRM only. DRM never claims rotation or scale; rotation tests live with the xrandr parser and the GDK probe. |
| Q5 | Same connector, GDK and DRM disagree → DRM's pixel size with GDK's orientation. Record both in `attempts`. |
| Q6 | Phase-1 minimum file size is **64 KiB** (setting). |
| Q7 | Confirmed: images under the long-edge minimum are **stored** and hidden by a default, removable view filter — never dropped, never invisible without a chip saying so. |
| Q8 | Confirmed as proposed: an include overrides only builtin-group rules, only at the include point; deeper user rules still win; `node_modules` stays pruned inside a user root. |
| Q9 | Accepted for v1: case-sensitive, no Unicode normalisation. Recorded as a known limitation in the Sources help text. |
| Q10 | **Do not** set `Image.MAX_IMAGE_PIXELS = None`. Read dimensions from the lazily-opened header, enforce our pixel budget before `load()`, and treat Pillow's own `DecompressionBombError`/`Warning` as the error-as-data result `too_large`. No process-global Pillow state is modified. |
| Deferrals | All seven proposed deferrals accepted for the first M1 slice (udisks2 toast, wlr-randr/kscreen-doctor parsers, rule export/import and regrouping, drag-and-drop and Space preview, unused §7 tables, eager 512 px thumbnails and FTS, "applied but excluded" marking). They stay in `docs/milestones.md` as open M1 items. |
| Q10a | Amendment: Pillow raises `DecompressionBombError` inside `Image.open()` above ≈ 179 MP, before `.size` is readable. That case is recorded as `probe_status = too_large` with **NULL width/height** (no hand-rolled header parsing); between the app's pixel budget and that limit the header dimensions *are* recorded and the file is `over_budget` without a decode. The P5a test expectation for the 40000 × 40000 header is `too_large`, dimensions NULL. Never key on Pillow mode strings for bit depth (16-bit grey opens as `I`). |
| T1 | `src/util/threads.py` no longer imports `gi`: `run_in_worker(..., scheduler=…)` takes a **required** scheduler. GUI code passes `src.util.glib_loop.glib_scheduler`; the CLI, services and tests pass `threads.immediate_scheduler`. Service layers may import `src.util.threads` and `src.util.cancel`, never `src.util.glib_loop`. |
| Q2a | Clarification of Q2 (the "or" was loose): an image is a **near miss** when it is not ideal, passes integrity and orientation, and *each* dimension test either passes or fails narrowly — linear coverage ≥ 90 % on both axes **and** crop loss ≤ 25 %. 1760 × 990 on 1920 × 1080 is near; 1600 × 900 and a 64 × 36 icon are a plain "no". As implemented in `catalogue/ideal.py`. |
| P4-1 | `display.connected = 1` means "in the current target set" for detected **and** declared displays; `save_display_snapshot` sets it. A one-off `--display` therefore does not become permanent. Rows are never deleted, so display ids stay stable. Supersedes the `OR source = 'declared'` join in §2.3/§2.4. |
| P4-2 | The rebuild `WHERE` in §2.3 was wrong for thresholds above 25 % (it applied the near-miss crop bound to every row). Correct form, as implemented: a row is written when it *covers and passes the chosen threshold* **or** satisfies the near-miss bounds. The Python-vs-SQL property test is the authority. |
| P4-3 | Accepted additions to the `catalogue.db` API: `transaction()`, `ReadConnections`, `CatalogueUnavailableError`, `run_migrations`; `image.probe_status` gains `too_large`; `display.width/height` are bounded 1…1,000,000. P5 rules: one `db.transaction` per writer job, never `executescript`, connections only through `db`. |
| P3-1 | Accepted: an include at the **same** path as an unlocked builtin folder rule wins (so `~/.config` or `/usr/share/icons` can be added as a root). Locked groups are never overridden. |

## Rulings (team lead, 2026-09-19) — P5–P7 planning round

Sources: architect P5–P7 plan, code-reviewer of `roots.py`, adversary of P3/P4 (verdict **PASS WITH FIXES**, 0 S1/S2, 4 S3 test gaps).

| # | Ruling |
| --- | --- |
| Q11 | `ProbeStatus` gains **`TOO_LARGE`**. Above ≈179 MP Pillow raises `DecompressionBombError` inside `Image.open()` before `.size` is readable → record `probe_status='too_large'` with **NULL width/height** (no header hand-parsing). Between the app pixel budget and that limit, header dims *are* recorded and the file is `over_budget` with no decode. Schema already allows `too_large` (P4-3). Ratifies Q10a. |
| Q12 | `WalkOptions.min_file_bytes` default is **65536** (Q6); the §2.7 literal `204_800` is stale. `scan.min_long_edge` is a default, removable **view filter** (Q7), never a walker/probe drop. |
| Q13 | P5 is split: **P5a** = `roots` (E) ∥ `walker`+`probe` (F) ∥ `thumbs` (G); **P5b** = `catalogue/ingest.py` (writer thread + `ScanService`) + `cli/**`, owned by impl-H. `ingest.py` was absent from the board's P5 owned set — added. |
| Q14 | P6 composition-root files — `src/pages/__init__.py`, `src/ui/content_area.py` (pages are built with no args today), and the app entry/`main.py` — are owned by **impl-J** (they build `AppServices` and inject VMs into pages). impl-I owns `viewmodels/**` only and never touches `content_area.py`. |
| Q15 | Move detection: ingest loads a **whole-catalogue** inode index for `by_inode` (a moved file is never re-probed or duplicated across roots), but `key_for` and missing-marking are **restricted to the root being walked**. |
| Q16 | Thumbnailing uses Pillow **`draft()`/reduced-scale decode** so a merely-large (non-bomb) image is not fully decoded just to shrink it — protects the ≥ 60 probes/s budget. Dimensions and all `image`-row metadata come from the **header**, never the reduced pixels; `ThumbSink.store` must not assume full resolution (it already never upscales). |
| Q17 | `linwp scan --add PATH` registers a permanent, enabled **`RootKind.USER`** root, then scans — mirroring the GUI "Add folder"; symmetric with `--display` staying one-off (P4-1). |
| R1 | Bug in `scanner/roots.py` `_is_volume_target`: it accepts 3-segment `/run/media/<user>`; the contract and M1.1 list only 4-segment `/run/media/*/*`. Fix to require `parts[:2] == ["run","media"] and len(parts) == 4`; covered by a new `test_roots.py` case. |
| R2–R4 | `roots.py` notes: (R2) `Mount.removable` uses root-independent `/media`,`/run/media` — document that findmnt targets are always real absolute paths, or thread `root`; (R3) `_NETWORK_EXACT`'s broader fstype list is accepted as an improvement — add a docstring note on the user-facing reason string; (R4) `propose_all` must record the source/exception it swallows, not fail silently. All land in P5a lane E. Stale §1 cell noted: `roots.py` legally imports `displays.Runner` (direction is fine per §1 prose + import-linter). |
| S3-gaps | The four adversary mutation survivors become **P4.1** (a small closing task): (1) `queries.py` every-display `EXISTS(display connected)` guard — test that the segment and `segment_counts["every"]` are 0 with no display connected; (2) `exclude.py` multi-segment literal case-sensitivity (`**/Foo/Bar/**` must not match `/x/foo/bar/y`); (3) `db.run_migrations` too-new guard called directly; (4) `recover()` fast-path (optional). No code bug — regression coverage only. |
