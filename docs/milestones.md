# Milestones

Delivery plan for Lin Wallpapers. Each milestone is a working, demonstrable state of the app — never a
half-integrated layer. Written per the universal instruction set: `/plan-first` before a milestone,
`/build-test` before each commit, `/session-end` at the end of a session, `changelog.md` updated as work
happens.

| | Milestone | Outcome |
| --- | --- | --- |
| **M0** | **Foundation** | The app opens, navigates and is themed; no features yet. Specified below. |
| **M1** | **Catalogue** | Finds the images and shows them: scanner, SQLite catalogue, thumbnails, Sources and Browse. Specified below. |
| M2 | Judgement | Suitability scoring, badges, duplicates, Image page |
| M3 | Previews | Transform pipeline, Cairo preview compositor, Screens page with capability probes |
| M4 | Apply (user space) | Planner, backups, verification, rollback, History/undo; desktop + lock on Cinnamon, GNOME, MATE, Xfce, Plasma |
| M5 | Apply (privileged) | One-shot `pkexec` helper + polkit actions; login screen, boot splash, boot menu — the base script, end to end; `linwp` CLI and `doctor` |
| M6 | Breadth + release | GDM/SDDM providers, dracut back end, five distribution fake roots, sync mode, collections, `.deb`, first release |
| M7 | More surfaces | LXQt/Pantheon/Budgie, per-monitor and Wayland refinements, online scan sources |
| M8 | GTK 4 | Flip `gtk_version.py`, `Gtk.GridView` grid, drop the compatibility shims |

**Standing rules for every milestone** (from [TECHNICAL-CONCEPT.md §17](../TECHNICAL-CONCEPT.md) and
[reference/README.md](../reference/README.md)):

- Nothing runs in the background. No daemon, no unit enabled at boot, no login hook; the app writes ordinary
  OS configuration and exits. Sync mode (M6) is opt-in, off by default, and a user-session autostart entry.
- Providers, not conditionals: no code branches on a distribution name outside `detect()`.
- Services never import GTK; widgets never touch the filesystem; the CLI can do whatever the GUI can.
- Every privileged step is planned before it is performed, backed up before it is written, verified before
  it is committed, and reversible afterwards.

---

# M0 — Foundation

**Goal:** a launchable, navigable, correctly themed application shell with the project's standards,
layering and tooling in place — so that every later milestone is filling in modules rather than arguing
about structure.

**Demo at the end of M0:** `./run.sh` opens a 1280 × 800 window in the yellow/gray theme; the sidebar
switches between eight empty pages; `linwp --version` works; `pytest`, `ruff`, `mypy` and the GTK 4
portability lint all pass; closing the window leaves no process behind.

### In scope
Repository scaffold, the app shell derived from the starter template, design tokens, empty pages and
routes, the layering and compatibility rules made mechanical (lint + import rules), the test harness
skeleton, and the CLI entry point.

### Not in scope
Scanning, the catalogue, thumbnails, scoring, previews, the transform pipeline, any apply provider, the
helper, packaging. Pages are empty placeholders that state what will live there.

---

## M0.1 — Repository and universal scaffold

- [ ] `universal-agents/setup.sh ~/projects/lin-wallpapers "Lin Wallpapers" "GTK wallpaper manager for every screen"`, then `universal-permissions/setup.sh`
- [ ] `.claude/` — `settings.json` (hooks), `settings.local.json` (permissions), `board.md`, `agents/`, `skills/`, `roles/`, `commands/` (`plan-first`, `build-test`, `session-end`)
- [ ] `.claude/rules/` — universal `memory-rules.md`, `security.md`, `token-hygiene.md`; project rules:
      `python-gtk.md` (main-thread-only UI, no blocking I/O in callbacks, `GLib.idle_add` from workers),
      `privileged-helper.md` (allow-listed operations, polkit, no shell with user input, never touch a package conffile),
      `boot-safety.md` (validate before install, verify the initramfs, always have a rollback path)
- [ ] `.claude/memory/` — `MEMORY.md`, `decisions.md` seeded with the concept's decisions (base script as the engine; providers not conditionals; no daemon; GTK 3 now, GTK 4 rules from day one), `pending.md`, `sessions/`, `changes/`
- [ ] `.claude/hooks/` — session-start, security gate, post-edit lint with the Python section enabled (`ruff`); `chmod +x`
- [ ] `CLAUDE.md` from the v2026.04 template with the real build/test/lint/run commands
- [ ] `.claudeignore`, `.gitignore` (already present), first `changelog.md` entry

## M0.2 — App shell from the starter template

- [ ] Vendor the starter structure: `src/main.py`, `src/config/{config_theme,config_layout,config_themes}.py`, `src/ui/{dashboard_window,sidebar,content_area}.py`, `src/pages/page_base.py`, `src/modules/manager_navigation.py`, `src/utils/manager_theme.py`, `resources/css/style.css`, `run.sh`
- [ ] Record the derivation in `NOTICE` (already noted) and keep the template's conventions: 150 px sidebar, `nav_items` tuples, `register_page("<route>", page)`, `BasePage.build_content()`
- [ ] Replace `Gtk.main()` with `Gtk.Application` + `Gio.SimpleAction`; single instance; app ID `io.mensuramedia.LinWallpapers`
- [ ] `src/gtk_version.py` — the single `gi.require_version('Gtk', os.environ.get('LWP_GTK', '3.0'))` gate
- [ ] `src/ui/compat.py` — `append()`, `set_child()`, `show()`, `CanvasArea` (wraps the `draw` signal, exposes `on_draw(cr, w, h)`), gesture helpers
- [ ] `run.sh` creates the venv, installs requirements, launches; `shellcheck`-clean

## M0.3 — Design tokens and theme

- [ ] `resources/css/tokens.css` — `@define-color` for the palette from `ui-kit-yellow-gray-yello.jpg`:
      `bg-base #1E2233`, `bg-surface #252A3E`, `bg-raised #2B3044`, `stroke rgba(255,255,255,.08)`,
      `text #F2F3F7`, `text-dim #8A8E9E`, `accent #FFC700`, `accent-2 #FFB500`, `on-accent #1A1400`,
      `ok #4ADE80`, `warn #FFB500`, `danger #EF4444`
- [ ] `resources/css/style.css` — component classes only (cards, chips, pills, sidebar, score ring); no
      `override_*`, no `-gtk-gradient`, no hard-coded hex outside `tokens.css`
- [ ] GResource bundle (`resources/lin-wallpapers.gresource.xml`) built by `run.sh` and the packaging later
- [ ] The starter's theme applicator kept, with the Lin Wallpapers theme as the default entry in `config_themes.py`
- [ ] 8 px spacing grid and 12/16 px radii expressed as layout constants in `config_layout.py`

## M0.4 — Pages, routes and the empty states

- [ ] Eight `BasePage` subclasses registered as routes, matching the mockups: `browse`, `image`, `screens`,
      `preview`, `sources`, `collections`, `history`, `settings` (+ `about`)
- [ ] Sidebar: logo block, route buttons with symbolic icons, and the footer slot that will later show
      "this machine" (empty in M0)
- [ ] Each page renders a titled placeholder naming the milestone that fills it — no lorem ipsum, no fake data
- [ ] Window: 1280 × 800 default, 960 × 640 minimum; state (size, last route) remembered in `GSettings`
- [ ] Keyboard: `Ctrl+1…8` route switching, `F5` reserved for rescan, focus-visible styling

## M0.5 — Layering made mechanical

- [ ] Package skeletons with docstrings and `__all__`: `viewmodels/`, `scanner/`, `catalogue/`, `imaging/`, `preview/`, `apply/` (+ `apply/providers/`, `apply/registry.py`), `helper/`, `sync/`, `cli/`, `util/`
- [ ] `apply/registry.py` — the provider registry and the `SurfaceProvider` Protocol from the concept (§17.1), with no implementations yet
- [ ] `tools/gtk4_lint.py` — fails on banned GTK 3-only calls (`pack_start`, `add`, `show_all`, `Gtk.Menu`, `Gtk.StatusIcon`, `button-press-event`, `Gdk.Screen`, `override_*`) outside `ui/compat.py`
- [ ] `import-linter` contracts: `ui`/`pages` may not import `scanner`/`catalogue`/`apply`; `scanner`/`catalogue`/`imaging`/`apply`/`helper` may not import `gi`
- [ ] `util/threads.py` — the worker-to-UI pattern (`run_in_worker(fn, on_done)` → `GLib.idle_add`), so no later module invents its own

## M0.6 — CLI entry point

- [ ] `src/cli/linwp.py` with the argument surface stubbed: `scan`, `list`, `show`, `preview`, `plan`, `apply`, `undo`, `history`, `sync`, `doctor`, plus `--json` and the exit-code table
- [ ] Implemented in M0: `--version`, `--help`; every other subcommand exits 3 ("not implemented yet") with a one-line message naming its milestone
- [ ] Console-script entry point so `linwp` works from the venv

## M0.7 — Tests, tooling and the fake root

- [ ] `pytest` + `pytest-cov`; `tests/unit/` with the first real tests: the `SurfaceProvider` Protocol shape, the registry, `compat` helpers, token parsing
- [ ] `tests/fakeroot/` skeleton — a synthetic `/etc`, `/usr/share`, `/boot` tree plus the fixture that points a provider at it (empty of providers in M0, used from M4)
- [ ] `xvfb-run` smoke test: the app starts, switches every route, and exits cleanly with no GTK criticals
- [ ] `ruff`, `mypy` (strict on `src/apply`, `src/catalogue`, `src/imaging`, `src/helper`), `shellcheck` for `run.sh`
- [ ] A single `make check` / `/build-test` path that runs: `bash -n`/shellcheck → ruff → mypy → gtk4_lint → import-linter → pytest → the smoke test

## M0.8 — Documentation and memory

- [ ] `README.md` development section updated with the real commands once they exist
- [ ] `docs/` — this file kept current; the concept's §13 layout reconciled with what was actually created
- [ ] First session log in `.claude/memory/sessions/`, first change manifest in `.claude/memory/changes/`
- [ ] `changelog.md` entries as work happens, not after

---

## M0 acceptance criteria

The milestone is done when all of these hold on a clean checkout:

1. `./run.sh` launches the app on Mint 22.2 (GTK 3.24, PyGObject 3.48) with no console warnings.
2. All eight routes switch, keep independent scroll state, and show their placeholder.
3. The window matches the mockups' theme: every color resolves to a token; no hex outside `tokens.css`.
4. `linwp --version` prints the version; every unimplemented subcommand exits 3 with its milestone named.
5. `/build-test` passes end to end: shellcheck, ruff, mypy, `tools/gtk4_lint.py`, import-linter, pytest, `xvfb-run` smoke test.
6. `LWP_GTK=4.0 python3 -c "import src.gtk_version"` selects GTK 4 through the single gate (the app is not expected to *run* on GTK 4 until M8 — this only proves the gate is the only place the version is chosen).
7. **Nothing runs in the background:** after closing the app, `pgrep -af lin-wallpapers` is empty;
   `systemctl list-unit-files | grep lin-wallpapers` is empty; nothing was added to `~/.config/autostart`.
8. Nothing outside `$HOME` has been written by anything in M0 — no `sudo`, no `pkexec`, no `/etc` access.
9. `.claude/` scaffold present and hooks firing (SessionStart injects pending items; post-edit lint runs `ruff`).
10. `decisions.md` records: the base script as the engine, providers over conditionals, no daemon, GTK 3 with
    GTK 4 rules, yellow/gray tokens.

## M0 risks

| Risk | Mitigation |
| --- | --- |
| The starter template's structure drifts from the concept's layout (§13) | Reconcile once, in M0.8, and record the deviation in `decisions.md` rather than leaving two layouts |
| GTK 3 habits leak into pages and make M8 expensive | `tools/gtk4_lint.py` and `compat.py` land in M0, before any page logic exists |
| Empty pages invite fake data "just to see it" | Placeholders state the milestone that fills them; no fixtures in `src/` |
| Scaffolding sprawls into features | M0 has no scanner, no provider implementations, no helper — the acceptance list above is the boundary |

## After M0

M1 begins with `/plan-first` on the scanner and catalogue — specified below.

---

# M1 — Catalogue

**Goal:** the app finds the images that are already on the machine and shows them. After M1 the Browse page
is full of real thumbnails from real files, and the scan is fast, cancellable, incremental and honest about
what it skipped.

**Demo at the end of M1:** first run offers the proposed scan roots; one click fills the grid while the scan
is still running; filtering to `≥ 1920 × 1080` and `16:9` narrows thousands of images instantly; unplugging
the external drive dims its images instead of losing them; `linwp scan` and `linwp list --min-width 1920`
do the same work with no GUI.

### In scope
Scan roots and the exclusion policy, the two-phase walk, image probing, the SQLite catalogue, the thumbnail
cache, the Sources page, and the Browse page bound to real rows (search, filter, sort, selection).

### Not in scope
Suitability scoring, badges and duplicate detection (M2 — the columns exist and stay `NULL`); the Image
detail page beyond a click target; previews; transforms; anything that writes outside `$HOME`. **M1 still
touches nothing but the catalogue, the thumbnail cache and its own settings.**

---

## M1.1 — Roots: where images come from

- [ ] `scanner/roots.py` with the `ScanSource` provider interface (concept §17.2) and the v1 sources:
      XDG picture dirs (`xdg-user-dir PICTURES`, `~/Wallpapers`, `~/Pictures/wallpapers`), system wallpaper
      dirs (`/usr/share/backgrounds`, `/usr/share/wallpapers`, `~/.local/share/backgrounds`), mounted local
      volumes via `findmnt` (ext4/btrfs/xfs/vfat/exfat/ntfs3), and user-added folders
- [ ] Network filesystems (`nfs`, `cifs`, `sshfs`, `fuse.*`) excluded by default, opt-in per mount, with the
      reason shown in the UI — never a silent skip
- [ ] Removable media: udisks2 mount events over D-Bus → "Scan this drive?" toast, answer remembered per
      volume UUID; `volume_id` stored with every row so a remount at another path heals instead of duplicating
- [ ] `scanner/exclude.py` — pseudo-filesystems, `/timeshift`, `.snapshots`, `.Trash*`, `~/.cache`,
      `.thumbnails`, VCS/build dirs, `node_modules`, Steam/Proton library trees, plus user ignore globs;
      applied **before** `stat`, and each exclusion is explainable ("skipped: Steam library")
- [ ] Loop protection: symlinks not followed across filesystem boundaries; `(device, inode)` identity stops
      bind mounts and hardlinks from being counted twice

## M1.2 — The walk

- [ ] `scanner/walker.py` — phase 1 `os.scandir` by extension and size (≥ 200 KB default), phase 2 probe;
      phase 1 reports progress per directory, phase 2 drives the progress bar
- [ ] Worker pool with a **bounded** queue (`concurrent.futures`), cancellable mid-scan, and back-pressure so
      the catalogue writer is never the bottleneck
- [ ] Results stream to the UI in batches via `util/threads.py` → `GLib.idle_add`; the grid fills as the scan runs
- [ ] Incremental rescan: `(device, inode, mtime, size)` unchanged → skipped without opening the file
- [ ] Per-root scan state (`root.last_scan`) so "Scan now" on one folder never re-walks everything
- [ ] Errors are data, not exceptions: unreadable file, permission denied, broken symlink and I/O error are
      counted, surfaced in the Sources page and never abort the scan

## M1.3 — Probing an image

- [ ] `scanner/probe.py` — dimensions, format, alpha, megapixels, aspect, EXIF orientation (applied to the
      recorded geometry), ICC presence; GdkPixbuf first, Pillow as the fallback for what it can't open
- [ ] Format support: JPEG, PNG, WebP, AVIF, HEIF, JXL where the platform's loaders provide them; a missing
      loader is reported once per format, not per file
- [ ] Integrity: truncated and zero-byte files flagged, never crash the worker; animated GIF/WebP recorded
      as such; SVG deliberately out of scope for v1
- [ ] Hard limits: a decode budget (pixels and seconds) so a 40,000 × 40,000 px file cannot stall a worker

## M1.4 — The catalogue

- [ ] `catalogue/db.py` + `schema.sql` — the schema from concept §7 (WAL, `~/.local/share/lin-wallpapers/catalogue.db`),
      with `score`, `badges`, `palette` and `dhash` present but unpopulated until M2
- [ ] Migration runner (`user_version` pragma) from the first release, so M2 adding columns is routine
- [ ] `catalogue/queries.py` — the query builder behind the filter bar: search, min width/height, aspect
      bucket, orientation, format, source/root, `missing`; sorted by name, date, size or resolution; paged
- [ ] Upserts keyed on `path`, with `(device, inode)` used to detect a *moved* file rather than a new one
- [ ] `missing=1` marking when a file or its volume disappears — rows are never deleted by a scan; a
      "Forget missing images" action exists in Settings
- [ ] A change feed (`GObject` signal or callback) so the Browse grid updates without re-querying everything
- [ ] `linwp scan` / `linwp list` / `linwp show` implemented against the same services — the CLI proves the
      layering (no GTK below the view models)

## M1.5 — Thumbnails

- [ ] `catalogue/thumbs.py` — freedesktop-style cache at `~/.cache/lin-wallpapers/thumbnails/{normal,large}/`,
      keyed by a content hash so moving a file doesn't regenerate it
- [ ] Sizes 256 and 512 on the long edge, JPEG q85; generated in workers, never on the UI thread
- [ ] Cache budget in Settings (default 512 MB) with LRU eviction; "Clear cache" and "Rebuild catalogue"
- [ ] Missing/failed thumbnail → a typed placeholder (with the reason), never a blank card
- [ ] Reuse of the desktop's existing thumbnails is explicitly **not** done (different keying, stale risk)

## M1.6 — Sources page

- [ ] Root list: path, kind (XDG / system / volume / user), enabled switch, image count, last scan, and the
      live progress row while scanning
- [ ] Add folder (chooser + drag-and-drop onto the page), remove, rescan one, rescan all, cancel
- [ ] Volumes: online/offline state by UUID, "scan this drive" memory, and the count of images currently offline
- [ ] The skipped list, with reasons: network mount, excluded path, unreadable, unsupported format
- [ ] Exclusions editor (glob list) with an immediate "this would skip N images" count

## M1.7 — Browse page

- [ ] `ui/components/image_grid.py` — `Gtk.FlowBox` in a `Gtk.ScrolledWindow` with child recycling behind
      one component, so M8 can swap it for `Gtk.GridView` without touching pages
- [ ] Card: thumbnail with a 1 px inner stroke, filename, resolution chip; the score ring's slot is reserved
      and empty until M2
- [ ] Filter bar: search (debounced, matches name and folder), min resolution, aspect, orientation, format,
      source; each active filter is a removable chip, and an empty result lists the chips that caused it
- [ ] Sort: name, date added, file size, resolution (score arrives in M2)
- [ ] Selection, `Space` quick-preview (full-window image, no surface mock-ups yet), double-click → Image page
- [ ] Empty states from concept §15: first run ("Find wallpapers" hero with the proposed roots), scanning
      banner with counts and cancel, no-results, offline-drive card
- [ ] Keyboard: `/` focuses search, arrows move the selection, `Enter` opens, `Ctrl+1…8` still switch routes

## M1.8 — Performance and tests

- [ ] Generated fixture library (10,000 small images across shapes and formats) built by a script, not committed
- [ ] Benchmarks recorded in `docs/perf.md` against the concept's budgets (§20): ≥ 300 files/s in phase 1,
      ≥ 60 probes/s in phase 2, 60 fps scrolling at 20,000 cards, thumbnail from cache < 5 ms, < 250 MB RSS
- [ ] Unit tests: exclusion policy, root discovery against a fake mount table, incremental-rescan decisions,
      query builder SQL, thumbnail keying, migration runner
- [ ] Nasty-file corpus: truncated JPEG, zero-byte, CMYK, 16-bit PNG, EXIF-rotated, animated GIF, unicode and
      newline filenames, permission-denied, symlink loop, a file that disappears mid-scan
- [ ] `xvfb-run` smoke test extended: scan a fixture root, assert the grid fills and filters narrow it
- [ ] Cancellation test: cancel mid-scan → workers stop, the DB is consistent, a rescan resumes correctly

### Deferred out of M1 (on purpose)
`inotify` live watches on chosen folders, and scanning online sources, both land with sync mode in M6. M1
rescans on demand only.

---

## M1 acceptance criteria

1. First run proposes roots and scans **nothing** until the user agrees.
2. A full scan of the reference machine (`~/Pictures`, `/data`, `/usr/share/backgrounds`) completes with a
   live-filling grid, an accurate count, and a skipped list that explains every omission.
3. A rescan with no changes touches no image file (verified by count of probes = 0) and finishes in seconds.
4. Filters and sort return in < 100 ms on a 20,000-row catalogue; scrolling stays at 60 fps.
5. Unplugging a scanned drive dims its images, disables nothing else, and reconnecting restores them by UUID
   with no duplicate rows.
6. The catalogue survives a kill -9 mid-scan (WAL), and `linwp scan` after it converges to the same state.
7. `linwp scan|list|show` produce the same results as the GUI, with `--json` output.
8. Budgets in `docs/perf.md` met on the reference laptop, or the miss documented with the reason.
9. Layering holds: import-linter still passes (no `gi` in `scanner`/`catalogue`), and `pytest` covers the
   scanner and catalogue without a display.
10. Still nothing in the background and nothing written outside `$HOME`, `~/.cache` and `~/.local/share`.

## M1 risks

| Risk | Mitigation |
| --- | --- |
| A huge or pathological tree (Steam textures, photo archives) makes the first scan feel broken | Exclusions by default, phase-1 filtering before `stat`, live counts, cancel at any moment |
| Decoding large images blows memory | Decode budget per file, bounded worker queue, thumbnails written straight to disk |
| The thumbnail cache grows without limit | Size budget + LRU eviction, visible in Settings |
| SQLite contention between workers and the UI | One writer thread, WAL, short transactions, batched inserts |
| "Scan everything" reads a network mount and hangs | Network filesystems opt-in, per-mount, with the reason shown |
| Scoring creeps in early | The score columns stay `NULL` in M1; the card's ring slot stays empty until M2 |

## After M1

M2 turns the catalogue into judgement: the weighted suitability score (§6), badges that explain themselves,
perceptual-hash duplicate clustering, and the Image page with metadata, palette and the fit control.
