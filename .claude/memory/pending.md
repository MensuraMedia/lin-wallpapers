# Pending

Next actions, most important first. Keep short; move done items into the changelog.

## Next phase
- **P5b — ingest + CLI** (serialises after P5a; owner impl-H):
  - `catalogue/ingest.py`: the single `CatalogueWriter` thread + `ScanService.scan()` pipeline
    (scan_lock → mounts/volume healing → detect → snapshot + scan row → ideal.rebuild on display-set
    change → matcher → per-root walker thread → bounded Queue(512) → N probe loops (scan-private pool) →
    Queue(256) → writer batches → missing-marking only after a complete walk → thumbs.evict → finish row).
  - `cli/{context,cmd_scan,cmd_list,cmd_show,cmd_exclude,cmd_displays}.py` + rewire `cli/linwp.py`.
  - Adversary asks: bound the `flock`/`ScanInProgressError` test with a fast timeout (a blocking-flock
    regression currently deadlocks the suite rather than failing cleanly).
  - Integration: assert `ThumbCache` conforms to `probe.ThumbSink` (lane G deliberately did not import it).
  - Apply ruling Q15 (whole-catalogue inode index; per-root key_for/missing) in ingest.

## Then
- **P6** — view models (impl-I: DTOs first) → Sources/Browse pages + components (impl-J owns the
  composition-root files too: `pages/__init__.py`, `ui/content_area.py`, app entry). See ruling Q14.
- **P7** — 10k fixture generator, nasty corpus, cancel/kill-9, `docs/perf.md`, M1 acceptance run. Add the
  `perf` marker to `pyproject.toml` (team-lead file).

## Deferred / out of scope (recorded, not forgotten)
- Per-virtual-desktop wallpapers: feasibility only — see `docs/design/virtual-desktop-wallpapers.md`.
  Feasible daemon-free only on Xfce (xfconf) and KDE Activities; Q1–Q5 there need product/team answers.
- Runtime wiring of the window icon from source (`set_default_icon_name`/resource) — optional; the
  installed `.desktop` + hicolor icon already give the menu/taskbar icon. Left out to keep the gate green.
- Full distribution packaging (deb/rpm/flatpak) — a later milestone; `install.sh` is desktop integration only.
