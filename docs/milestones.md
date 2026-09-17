# Milestones

Delivery plan for Lin Wallpapers. Each milestone is a working, demonstrable state of the app — never a
half-integrated layer. Written per the universal instruction set: `/plan-first` before a milestone,
`/build-test` before each commit, `/session-end` at the end of a session, `changelog.md` updated as work
happens.

| | Milestone | Outcome |
| --- | --- | --- |
| **M0** | **Foundation** | The app opens, navigates and is themed; no features yet. Specified below. |
| **M1** | **Catalogue** | Finds the images and shows them: scanner, SQLite catalogue, thumbnails, Sources and Browse. Specified below. |
| **M2** | **Judgement** | Decides which images actually work as wallpapers: scoring, badges, duplicates, Image page. Specified below. |
| **M3** | **Previews** | Shows the result before it happens: transform pipeline, Cairo compositor for all five screens, capability probes. Specified below. |
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

M2 turns the catalogue into judgement — specified below.

---

# M2 — Judgement

**Goal:** the catalogue stops being a file list and starts being an opinion. Every image gets a suitability
score that can be read back as sentences, badges that explain themselves, a palette, and duplicate
clustering — so "show me what actually works as a wallpaper on this machine" is one filter, not an afternoon
of scrolling.

**Demo at the end of M2:** Browse opens sorted by score; the top row is genuinely the right images for this
laptop's 1920 × 1080 panel; `Text-safe` narrows to images with a calm area where the login prompt sits;
`Hide duplicates` collapses three copies of the same photo into one card; opening an image shows *why* it
scored 91, component by component.

### In scope
The per-image analysis pass (palette, luminance, contrast, detail distribution), the weighted scorer and its
explanations, badges, perceptual-hash duplicate clustering, the score/badge/duplicate filters and the default
sort, and the Image page with metadata, palette, badges and the score breakdown.

### Not in scope
The transform pipeline and the crop/fit control, the surface previews, and the surface tiles' real state —
all M3. **Scope correction to the original roadmap:** the fit control belongs with the transform that
implements it, so M2's Image page shows a plain scaled preview and M3 adds the crop frame, fit modes and
focal point. Nothing is applied, and nothing is written outside `$HOME`.

---

## M2.1 — The analysis pass

- [ ] `scanner/analyze.py` — one worker pass over a downscaled decode (long edge 256), so analysis costs one
      decode per image and never touches full resolution twice
- [ ] **Palette:** k-means (k = 5) in CIELAB on the downscale, stored with population shares; plus mean
      luminance, contrast range (P5–P95) and a dark/light classification
- [ ] **Detail distribution:** edge density per cell on a 6 × 4 grid (Sobel on the downscale), stored as a
      compact array — the basis of "text-safe", and reusable later for focal-point suggestions
- [ ] **Text-safe regions:** the cells that matter per surface (centre band for the lock clock, centre for the
      greeter prompt, lower third for the splash spinner, centre box for the boot menu) evaluated for low
      edge density *and* sufficient contrast against white text
- [ ] **Perceptual hash:** 64-bit dHash on the 9 × 8 luma downscale, stored as an integer
- [ ] Runs in the same bounded worker pool as M1, as a second pass so a scan still fills the grid quickly;
      analysis results stream into the cards as they land
- [ ] Incremental: only rows whose `mtime`/`size` changed, or whose `analysis_version` is older, are re-analyzed

## M2.2 — The scorer

- [ ] `scanner/score.py` — the weighted model from [TECHNICAL-CONCEPT.md §6](../TECHNICAL-CONCEPT.md):
      resolution vs. the *actual* connected outputs (35), aspect match (20), detail distribution (15),
      color coherence (10), format and integrity (10), not-a-wallpaper penalties (10)
- [ ] **Display-aware:** outputs come from `Gdk.Monitor`; the machine's geometry is part of the score input,
      and a display change (dock, external monitor, resolution change) invalidates and recomputes scores
      in the background — with the old score shown until the new one lands, never a blank
- [ ] **Deterministic and versioned:** `scorer_version` stored per row; bumping the version triggers a
      recompute pass, and the same inputs always produce the same number (a property test asserts it)
- [ ] **Explanations are data, not prose glued on afterwards:** each component returns
      `(points, max, reason)`, so the UI, the CLI and the tooltips read the same structure
- [ ] Penalties are explicit and listable: alpha channel, animation, icon/sprite geometry, upscale required,
      EXIF rotation needed, path heuristics (`icons/`, `emoji/`, `textures/`, `sprites/`)
- [ ] Score never hides anything: it orders the grid and feeds filters; only the filter bar removes rows

## M2.3 — Badges

- [ ] `4K`, `native`, `text-safe`, `dark`, `light`, `duplicate`, `upscaled`, `portrait`, `animated`,
      `truncated` — each derived from stored analysis, never recomputed in the view
- [ ] Every badge carries a one-sentence explanation shown on hover/focus ("Text-safe: the centre band has
      low detail and enough contrast for white text")
- [ ] Badges are typed (`BadgeKind` enum), rendered by one component, and available to the CLI as `--badge`

## M2.4 — Duplicates

- [ ] `catalogue/dupes.py` — clustering by Hamming distance (≤ 6 by default) with size/megapixel bucketing to
      keep comparisons cheap; BK-tree or banded index rather than an O(n²) sweep
- [ ] A cluster elects a **representative**: highest resolution, then largest file, then first seen; the rest
      carry `duplicate_of`
- [ ] Browse collapses a cluster into one card with a "3 copies" chip; the Image page lists every path with
      its size and folder, and lets the user change which copy is the representative
- [ ] Never deletes anything. "Show duplicates" and "Reveal in Files" only — the app is not a deduper
- [ ] Re-encoded and resized copies are found (a 4K JPEG and its 1080p PNG re-save cluster together); visually
      distinct images with similar histograms must not (asserted in tests)

## M2.5 — Browse becomes opinionated

- [ ] Default sort changes to **Score, descending**; the other sorts stay
- [ ] The score ring on each card fills in (the slot reserved in M1), with the number and the accent arc
- [ ] New filters: minimum score, `Text-safe`, `Dark`/`Light`, `Hide duplicates`, `Native or better`
- [ ] "Suitable for every screen" becomes a real saved query: score ≥ 70, native or better, text-safe
- [ ] The empty-result state names which chip excluded everything (an M1 promise, now with more chips to blame)
- [ ] Analysis progress is its own quiet line in the scan banner ("1,240 analysed of 1,864"), cancellable,
      and never blocks browsing

## M2.6 — Image page

- [ ] Large preview: the image scaled to fit, with true dimensions and format shown — no crop frame yet (M3)
- [ ] Score card: the ring, the total, and the breakdown bars with the stored `reason` for each component
- [ ] Metadata grid: resolution, aspect, megapixels, file size, format, alpha, EXIF orientation, ICC, path,
      volume, first seen, last seen
- [ ] Palette strip with copyable hex values; dark/light classification stated
- [ ] Badge row with the explanations; duplicate list when the image belongs to a cluster
- [ ] The five surface tiles are present but honest: "not yet — M3 previews, M4/M5 apply"
- [ ] `linwp show <id|path>` prints the same score breakdown, badges and duplicate list, `--json` included

## M2.7 — Calibration and tests

- [ ] A labelled corpus (~60 images: real wallpapers, phone photos, screenshots, icons, textures, scans)
      with expected badges and score bands, committed as metadata + generators rather than binaries
- [ ] Property tests: determinism (same input → same score), monotonicity (a larger copy of the same image
      never scores lower), and bounds (0 ≤ score ≤ 100, components never exceed their max)
- [ ] Duplicate tests: re-encode, resize, crop-by-2 %, and a "similar but different" negative set
- [ ] Display-change test: a fake monitor set at 1920 × 1080 vs 3840 × 2160 reorders the same catalogue as expected
- [ ] Performance: analysis ≥ 25 images/s on the reference laptop (4 workers), and a full re-score of 20,000
      rows (no re-decode, stored features only) in under 2 s
- [ ] `docs/perf.md` extended with the analysis and re-score numbers

### Deferred out of M2 (on purpose)
Learning from what the user actually applies, ML aesthetic scoring, and per-surface *separate* scores. The
`Scorer` interface (§17.2) is in place so either can arrive later without touching the catalogue.

---

## M2 acceptance criteria

1. Every catalogued image has a score, badges and a palette, or a recorded reason why analysis failed.
2. The score is explainable end to end: the UI tooltip, the Image page breakdown and `linwp show --json`
   report the same components, points and reasons.
3. Determinism and versioning hold: re-running analysis produces identical numbers; bumping `scorer_version`
   triggers a background recompute without blocking the UI.
4. Changing the display configuration re-scores in the background and reorders Browse accordingly.
5. `Hide duplicates` collapses re-encoded and resized copies of the same photo; the negative set stays separate.
6. "Suitable for every screen" returns a list a person would agree with on the reference machine — reviewed
   by hand against the labelled corpus, with misses recorded in `docs/perf.md` rather than quietly tuned away.
7. No image is ever hidden by scoring alone; only filters remove rows, and each is removable as a chip.
8. M1's budgets still hold: scanning, scrolling and filtering are no slower with analysis running.
9. Layering holds — no `gi` in `scanner`/`catalogue`, and the CLI reproduces every Browse query.
10. Still nothing in the background, and nothing written outside `$HOME`, `~/.cache` and `~/.local/share`.

## M2 risks

| Risk | Mitigation |
| --- | --- |
| "Suitability" is subjective and the score feels wrong | Weights are published, every component explains itself, the labelled corpus is the check, and the score only *sorts* — it never hides |
| Tuning becomes endless | One calibration pass against the corpus, recorded; further tuning needs a new `scorer_version` and a documented reason |
| Analysis makes the first scan feel slow | Second pass, after the grid is already usable, cancellable, at lower priority |
| dHash false positives collapse distinct images | Conservative threshold plus size bucketing, a negative test set, and collapsing is a filter the user can switch off |
| Score churn confuses ("it was 91 yesterday") | Scores change only when the image, the scorer version or the displays change — and the Image page says which |
| k-means on large images costs CPU | All analysis runs on the 256 px downscale, one decode per image |

## After M2

M3 makes the result visible — specified below.

---

# M3 — Previews

**Goal:** see it before it happens. Four of the five screens are otherwise only visible by logging out or
rebooting, so M3 builds the transform that will be installed and renders every screen from *that same
transform* — plus the capability probes that say what this machine can actually do.

**Demo at the end of M3:** pick an image, drag the crop to taste, and see the desktop, lock screen, login
screen, boot splash and boot menu side by side with that exact crop; the Screens page says what was detected
on this machine — "slick-greeter", "Plymouth with initramfs-tools", "GRUB 2 at /boot/grub/grub.cfg" — and
explains anything it cannot do. Nothing has been applied, and nothing outside `$HOME` has been written.

### In scope
The transform pipeline and its format profiles, the fit/focal-point control, the read-only capability probes
and each provider's `detect()` / `capabilities()` / `current()`, the Cairo preview compositor for all five
surfaces, the Screens page, the Preview page, and `linwp preview`.

### Not in scope
Any write outside `$HOME`: no greeter config, no theme installation, no initramfs, no GRUB. The helper, the
apply planner, backups and undo are M4/M5. "Run the real splash" needs root and arrives with M5. Apply
buttons exist on the Screens page but are disabled, with a tooltip naming the milestone.

---

## M3.1 — The transform pipeline

- [ ] `imaging/transform.py` — one entry point, `transform(image, geometry, mode, profile) -> bytes`, used by
      **both** previews and (from M4) applies. This is the base script's `render()` generalised
      ([reference/README.md](../reference/README.md), step 2)
- [ ] Modes: `fill` (zoom + centre crop, the default and what the base script does), `fit` (letterbox with a
      palette-derived matte from M2's palette), `center`, `stretch`, `tile`
- [ ] Order of operations fixed and documented: EXIF orientation → ICC to sRGB → scale (Lanczos) → crop at the
      focal point → flatten alpha → encode
- [ ] Focal point: normalised `(fx, fy)` biasing the crop, defaulting to centre; stored per image
- [ ] Format profiles: original file (desktop), JPEG q92 stripped of metadata (greeter), PNG without alpha
      (splash), 8-bit PNG ≤ 256 colours (boot menu), JPEG q85 (thumbnails)
- [ ] **Deterministic:** same input + options → byte-identical output (property test), so "is the installed
      file still the one I chose?" is a hash comparison in M4
- [ ] Render cache keyed by `(image content hash, geometry, mode, focal point, profile)` so dragging the crop
      re-renders at preview size only, and the apply reuses what the preview already produced
- [ ] Decode budget and downscale-on-load (`GdkPixbuf` scaling loader) so a 40 megapixel source is cheap

## M3.2 — Capability probes (read-only)

- [ ] `apply/environment.py` — the machine model: session type, desktop, greeter, splash system, initramfs
      generator, boot manager, outputs, writability of `/boot` and `/usr/share`, polkit agent present
- [ ] `detect()` for every v1 provider in the §4.2 matrix: `desktop_{cinnamon,gnome,mate,xfce,plasma}`,
      `lock_*`, `greeter_{slick,lightdm_gtk,gdm,sddm,lightdm_generic}`, `splash_plymouth`,
      `bootmenu_{grub,none}` — each returning confidence **and evidence strings**
- [ ] `capabilities()` and `current()` per provider — what it can do, and what is set right now (the greeter's
      configured background, the resolved `default.plymouth`, `GRUB_BACKGROUND`, the desktop's `picture-uri`)
- [ ] Everything here is **read-only**: no provider may write in M3, and a test asserts it (see M3.7)
- [ ] Results cached for the session with an explicit "Re-probe" action; a display change invalidates geometry
- [ ] `linwp doctor` prints the machine model and every provider's verdict (`--json`); the apply-side parts of
      doctor land in M5

## M3.3 — The preview compositor

- [ ] `preview/compositor.py` — renders a surface preview from the transform output plus a `PreviewSpec`
      supplied by the provider, so a new provider brings its own chrome instead of patching the compositor
- [ ] `preview/surfaces/desktop.py` — panel, a few desktop icons, a window frame, clock; panel position and
      icon size taken from the desktop's own settings where readable
- [ ] `preview/surfaces/lock.py` — clock, date and unlock field at the detected desktop's real positions
- [ ] `preview/surfaces/login.py` — the greeter's layout: avatar, user name, password field, session and power
      buttons, top bar; slick-greeter and lightdm-gtk-greeter differ and each provider says so
- [ ] `preview/surfaces/splash.py` — **pixel-exact geometry**: the same cover-scaling maths and spinner
      placement (75 % of screen height) as the theme the app will generate, animated at the theme's frame rate
- [ ] `preview/surfaces/bootmenu.py` — the quantized 8-bit PNG with the menu box, entry list and GRUB's font
      metrics over it, so colour banding is visible *before* it is installed
- [ ] All chrome drawn with Cairo through `ui/compat.py`'s canvas wrapper (GTK 4 ready); `prefers-reduced-motion`
      honoured; every preview renders in < 120 ms at card size
- [ ] One code path for card-size and full-size previews — no separate "big preview" renderer

## M3.4 — Fit control and focal point

- [ ] Image page gains the crop frame over the preview, the fit-mode segmented control, and drag-to-reposition
      (a `Gtk.GestureDrag` through `compat`)
- [ ] Live re-render while dragging, debounced to one frame, using the preview-size render cache
- [ ] Per-image options persisted in the catalogue (`fit_mode`, `focal_x`, `focal_y`), defaulting to
      `fill` + centre; "Reset crop" restores them
- [ ] The crop shown is the crop that will be installed — the same call, the same options, verified by a test
      that compares the preview's transform hash with the one a (dry-run) apply plan would use

## M3.5 — Screens page

- [ ] The five surface cards, each with: a live mini preview, the provider name and mechanism, the probe
      verdict (`applied` / `follows desktop` / `needs authorization` / `unavailable: <reason>`), what is
      currently set, and the owning component when unsupported
- [ ] "Preview" opens the full-size preview; "Apply" and "Revert" are visible but disabled with a tooltip
      naming their milestone (M4 for desktop/lock, M5 for the three privileged screens)
- [ ] The "what was detected" panel from the mockup, listing evidence per component, with "Copy doctor report"
- [ ] The sync switch is rendered but disabled until M6, labelled as such
- [ ] Preconditions that will matter later are already shown, because they are read-only: free space on
      `/boot`, `/boot` writability, number of installed kernels, polkit agent present

## M3.6 — Preview page

- [ ] All five previews in one view at the mockup's layout, each labelled with when it would take effect
- [ ] Click to enlarge a single screen; switch the source image without leaving the page
- [ ] The explainer panel stating that previews are built from the same transform as the apply, with the
      per-surface format profiles listed
- [ ] `linwp preview <image> --surface splash --out /tmp/splash.png` renders the same composition headlessly

## M3.7 — Tests

- [ ] **Transform golden tests:** byte-identical output for each mode and profile against committed hashes
      (small generated sources, not photographs), on the reference platform
- [ ] **Read-only test:** the whole M3 surface (probes, previews, `linwp preview`) runs under a wrapper that
      fails the test if any path outside `$HOME`/`XDG_*` is opened for writing
- [ ] **Probe tests** against the `tests/fakeroot/<distro-shape>/` trees from M0/M1: Mint Cinnamon,
      Ubuntu GNOME, Debian Xfce, Kubuntu, MX — each asserting the selected providers and the evidence
- [ ] **Compositor tests:** structural (regions, positions, sizes from the `PreviewSpec`) plus a perceptual
      hash against a stored reference render, tolerant of font differences
- [ ] Performance: preview render < 120 ms, crop drag at 60 fps, first transform of a 4K source < 400 ms
- [ ] `docs/perf.md` extended; `docs/preview-fidelity.md` records what each mock does and does not reproduce

### Deferred out of M3 (on purpose)
The live splash check (`plymouthd` + `plymouth --show-splash`) needs root and lands in M5 alongside the real
apply; screenshot-based previews of the actual greeter stay a later idea (§17.2).

---

## M3 acceptance criteria

1. Every preview is produced by the same `transform()` call the apply will use — proven by a hash comparison
   test, not by inspection.
2. All five previews render for the reference machine, and each states when it would take effect.
3. The Screens page reports the real machine: provider names, mechanisms, current values and evidence; every
   unsupported surface names the component that owns it and why.
4. The same probes, run against each of the five fake-root distribution shapes, select the right providers.
5. Fit mode and focal point persist per image, and the crop shown equals the crop that would be installed.
6. Nothing outside `$HOME` is written during any M3 operation — enforced by the read-only test wrapper.
7. Budgets: preview < 120 ms, crop drag 60 fps, `linwp preview` produces the same PNG as the GUI.
8. The boot-menu preview shows the quantized image, so banding is visible before installation.
9. Apply/Revert/sync controls are present but disabled, each naming its milestone — no dead buttons.
10. Layering holds: `imaging`, `preview` and the probe code import no GTK; only the compositor's canvas
    wrapper does, through `compat`.

## M3 risks

| Risk | Mitigation |
| --- | --- |
| A mock preview differs from the real screen and the user feels misled | Splash geometry is pixel-exact and shares the theme's maths; the others are labelled "layout mock"; `docs/preview-fidelity.md` states the limits; the real splash check arrives in M5 |
| Font and theme differences make greeter/menu mocks drift | Structural tests with perceptual-hash tolerance, not pixel equality; chrome positions come from the provider's `PreviewSpec` |
| GRUB quantization surprises after install | The boot-menu preview renders the actual 8-bit quantized PNG, not the source image |
| Probes mis-detect an unusual setup (two greeters installed, GDM on Wayland) | Confidence + evidence, a visible "Re-probe", `linwp doctor --json` as the bug-report format, and `greeter_lightdm_generic` as the honest fallback |
| Re-rendering on every drag frame stalls the UI | Preview-size renders through the cache, debounced to one frame, work off the UI thread |
| A read-only milestone quietly gains a write | The read-only test wrapper fails the build if any write outside `$HOME` is attempted |

## After M3

M4 makes it real where it is safe to: the apply planner, backups, verification, rollback and History/undo,
with the desktop and lock screen applied end to end on Cinnamon, GNOME, MATE, Xfce and Plasma — still with
no root, still nothing enabled in the background.
