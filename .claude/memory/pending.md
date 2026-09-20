# Pending

Next actions, most important first. Keep short; move done items into the changelog.

## Done (this run)
- P4.1, P5a (roots/walker/probe/thumbs), **P5b (ingest + CLI)**, **P6-I (view models)**, **P6-J (Sources/Browse GUI)** — all closed, adversary-gated. The app scans, remembers, and is clickable (Scan button, scan-at-open, results grid); CLI has parity.

## Next phase
- **P7 — performance + acceptance** (the last M1 phase):
  - 10k-image fixture generator (a script, not committed), built on `tests/helpers/imagegen.py`.
  - Benchmarks in `docs/perf.md` vs concept §20 budgets: ≥300 files/s phase 1, ≥60 probes/s phase 2, 60 fps at 20k cards, thumb-from-cache <5 ms, <250 MB RSS. Add a `perf` marker to `pyproject.toml` (team-lead file), excluded from `make check` unless `PERF=1`.
  - Promote the cancel / `kill -9` convergence and nasty-file corpus to an M1 acceptance run; verify acceptance criteria 1–10.

## Follow-ups / smaller items
- Runtime window-icon from source (`set_default_icon_name`/resource) — optional; the installed `.desktop` + hicolor icon already give the menu/taskbar icon.
- Capture a screenshot of the user's real 43-image library in Browse (the committed screenshots use the smoke fixture).
- Full distribution packaging (deb/rpm/flatpak) — a later milestone; `install.sh` is desktop integration only.

## Deferred / out of scope (recorded)
- Per-virtual-desktop wallpapers: feasibility only — `docs/design/virtual-desktop-wallpapers.md` (daemon-free only on Xfce + KDE Activities; Q1–Q5 need product/team answers).
- No system tray / no autostart — architectural (no background process).
