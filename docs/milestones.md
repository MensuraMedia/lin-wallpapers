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
| **M4** | **Apply (user space)** | The transaction engine, proven where no root is needed: desktop + lock on five desktops, with undo. Specified below. |
| **M5** | **Apply (privileged)** | The base script, end to end, through a one-shot helper: login screen, boot splash, boot menu. Specified below. |
| **M6** | **Breadth, explanation, release** | Works and explains itself everywhere: more providers, capability states and the activity log, sync mode, packaging, v1.0. Specified below. |
| M7 | More surfaces | LXQt/Pantheon/Budgie, per-monitor and Wayland refinements, online scan sources |
| M8 | GTK 4 | Flip `gtk_version.py`, `Gtk.GridView` grid, drop the compatibility shims |

**Standing rules for every milestone** (from [TECHNICAL-CONCEPT.md §17](../TECHNICAL-CONCEPT.md) and
[reference/README.md](../reference/README.md)):

- Nothing runs in the background. No daemon, no unit enabled at boot, no login hook; the app writes ordinary
  OS configuration and exits. Sync mode (M6) is opt-in, off by default, and a user-session autostart entry.
- Providers, not conditionals: no code branches on a distribution name outside `detect()`.
- Services never import GTK; widgets never touch the filesystem; the CLI can do whatever the GUI can.
- **Never hide a feature.** What this machine cannot do stays in the interface, greyed out, labelled
  "Unsupported in {distribution} {version}" with a plain-language reason, a "Why?" popover carrying the
  reason code and evidence, and a matching line in the activity log
  ([TECHNICAL-CONCEPT.md §15.1–15.3](../TECHNICAL-CONCEPT.md)). Every milestone that adds a feature adds its
  reason codes and its greyed-out state in the same commit.
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

M4 makes it real where it is safe to — specified below.

---

# M4 — Apply (user space)

**Goal:** build the whole apply transaction — plan, precheck, backup, write, verify, commit or roll back,
undo — and prove it on the two surfaces that need no privileges. When M5 adds root, it adds *providers*, not
a new mechanism.

**Demo at the end of M4:** choose an image, press Apply, see the exact steps first, watch the desktop change,
and press Undo to get the previous wallpaper back — on Cinnamon, and against fake backends for GNOME, MATE,
Xfce and Plasma. The History page lists every apply with its result and backup, and `linwp apply --surface
desktop,lock` does the same from a terminal.

### In scope
The plan model and planner, the executor with its transaction phases, the backup manifest and undo, drift
detection, verification, the apply sheet and result UI, the History page, and the desktop + lock providers
for Cinnamon, GNOME, MATE, Xfce and Plasma.

### Not in scope
Anything privileged: greeter, Plymouth, GRUB, the helper, polkit, `/var/backups` — all M5. Sync mode (M6).
**M4 must still run without ever calling `sudo` or `pkexec`**, and a test asserts it.

---

## M4.1 — The plan model

- [ ] `apply/plan.py` — `Step` (typed op, target, payload hash, estimated duration, `needs_root`, its own
      inverse) and `Plan` (ordered steps, the image, options, the surfaces, totals)
- [ ] `plan()` is **pure**: no side effects, safe to call on every selection change, and cheap enough to power
      the "Show what this will do" sheet live
- [ ] A step that cannot describe its own inverse cannot be planned — enforced in the constructor, not by review
- [ ] Batching rules encoded here, not in providers: expensive shared steps (from M5: one `update-initramfs`,
      one `update-grub`) are emitted once, at the end
- [ ] Plans serialise to JSON — the same structure the sheet renders, the CLI prints (`linwp plan --json`) and
      M5 hands to the helper on stdin
- [ ] A plan carries the transform's parameters and output hash from M3's render cache, so the apply installs
      exactly the bytes that were previewed

## M4.2 — The executor and its phases

- [ ] `apply/executor.py` implementing the concept's §10 sequence: **precheck → backup → write → verify →
      commit | rollback**, with per-step progress events
- [ ] **Precheck:** image decodable, options valid, target providers still detected, free space, no concurrent
      apply (a lock file in `$XDG_RUNTIME_DIR`), and — from M5 — `/boot` writability and polkit
- [ ] **Write:** user-space writes go through the provider; file writes (later) are temp-file → `fsync` →
      `rename` in the destination filesystem
- [ ] **Verify:** read the value back from the authority (not from cache) and compare with what was intended
- [ ] **Rollback:** any failed step restores the backup for every step already applied, in reverse order, then
      reports which step failed and why; a partial apply is never left behind
- [ ] Idempotence: a step whose target already holds the intended value is skipped and reported as "already set"
- [ ] Every apply writes an `apply_event` row (M1 schema) with the plan, result, timings and the backup reference

## M4.3 — Backups, undo and drift

- [ ] `apply/backup.py` — a manifest per apply in `~/.local/share/lin-wallpapers/backups/<timestamp>/`:
      for user-space surfaces the captured settings keys and values, with types; for files (M5) path, mode,
      owner, sha256. The layout is identical for both, so M5 only adds a second root (`/var/backups/...`)
- [ ] `linwp undo` / the Undo button replay the manifest in reverse: restore values, re-verify, record a new
      `apply_event` of kind `undo`
- [ ] **Drift detection:** if the current value is not what this app applied (the user changed the wallpaper
      by hand afterwards), undo says so and asks — restore anyway, or cancel. It never silently clobbers.
- [ ] Undo of an undo is just another apply; the History page reads as a stack, not a mystery
- [ ] Backup retention policy in Settings (keep N applies, default 20), with pruning that never removes the
      backup of the currently applied state

## M4.4 — Desktop providers

Each implements `plan/apply/verify/revert` over its own mechanism, declares `supports_per_monitor`, and never
touches another desktop's settings.

- [ ] `desktop_cinnamon` — `org.cinnamon.desktop.background` `picture-uri` + `picture-options`
- [ ] `desktop_gnome` — `org.gnome.desktop.background` `picture-uri` **and** `picture-uri-dark` (both, or the
      wallpaper reverts when the dark theme is active), plus `picture-options`
- [ ] `desktop_mate` — `org.mate.background` `picture-filename` (a plain path, not a URI) + `picture-options`
- [ ] `desktop_xfce` — `xfconf-query -c xfce4-desktop`, enumerating `.../last-image` properties per monitor and
      workspace, writing each, and reporting how many were set
- [ ] `desktop_plasma` — `plasma-apply-wallpaperimage`, falling back to the scripted `org.kde.PlasmaShell`
      D-Bus call; both paths verified by reading the config back
- [ ] Slideshow safety: if the desktop is currently running a wallpaper slideshow, the plan says that applying
      replaces it, and the backup captures the slideshow setting so undo restores it
- [ ] Per-monitor: where supported, apply to all outputs by default, with the option to pick one

## M4.5 — Lock-screen providers

- [ ] `lock_cinnamon` — reports "follows the desktop" (the base script's finding) and plans **no step** unless
      the user asks for a different image, in which case `org.cinnamon.desktop.screensaver` is written
- [ ] `lock_gnome` — `org.gnome.desktop.screensaver picture-uri`
- [ ] `lock_xfce` — `xfce4-screensaver` settings where present; otherwise reported unsupported with the reason
- [ ] `lock_plasma` — `kscreenlockerrc` through the KDE config tooling, user-scope only
- [ ] When the lock screen follows the desktop, the UI says so instead of showing a redundant success

## M4.6 — Apply UI

- [ ] The apply sheet from the mockup: image, target surfaces, the full step list with durations and
      `needs_root` markers, the warning lines, Cancel / Apply
- [ ] Progress per step, with the current step named; cancel between steps (never mid-write)
- [ ] Result state: per-surface ✓/✗ with when each takes effect, the backup path, Undo, and — for failures —
      the failing step, the reason and the rollback outcome
- [ ] The Screens page's Apply and Revert buttons become live for desktop and lock; the three privileged
      surfaces keep their disabled state and now say "M5"
- [ ] History page: the apply list with thumbnails, surfaces, result badges, and per-row Undo / Re-apply /
      "Show manifest"

## M4.7 — CLI

- [ ] `linwp plan <image> --surface desktop,lock [--json]` — print the plan, change nothing
- [ ] `linwp apply <image> --surface desktop,lock [--mode fill] [--dry-run]`
- [ ] `linwp undo [--id N]`, `linwp history [--json]`
- [ ] Exit codes distinguish success, "nothing to do" (idempotent), "precheck failed", "failed and rolled
      back", and "refused by the user"; documented in `--help` and the README

## M4.8 — Tests

- [ ] **Fake backends:** an in-memory GSettings/xfconf/Plasma double so all five desktop providers are tested
      without those desktops installed; the real backend is exercised on the reference machine (Cinnamon)
- [ ] **Transaction tests:** failure injected at each phase → full rollback, consistent state, correct report
- [ ] **Crash test:** the process is killed between steps → the next run detects the incomplete apply from its
      journal and offers to finish or roll back
- [ ] **Idempotence:** applying the same image twice produces "already set" for every step the second time
- [ ] **Undo tests:** exact restoration, drift detection, undo-after-manual-change, undo of an undo
- [ ] **No-privilege test:** the whole M4 surface runs under a wrapper that fails if `sudo`, `pkexec`,
      `systemd-run` or a write outside `$HOME` is attempted
- [ ] **Plan/apply agreement:** a property test asserting the executed steps equal the planned steps, in order

### Deferred out of M4 (on purpose)
Everything requiring root, and sync mode. The plan JSON is already shaped for the helper, so M5 adds
`needs_root` execution behind `pkexec` without changing the model.

---

## M4 acceptance criteria

1. Apply and undo work end to end on the reference machine for desktop and lock, with the previous wallpaper
   restored exactly.
2. The sheet shows the real plan before anything is written, and the executed steps match it exactly.
3. A failure injected at any phase leaves the machine in its pre-apply state, with a report naming the step.
4. Applying the same image twice is a no-op the second time, reported as "already set".
5. Undo detects drift (a wallpaper changed by hand afterwards) and asks instead of clobbering.
6. All five desktop providers pass against their fake backends; Cinnamon also passes against the real one.
7. GNOME sets both the light and dark keys; MATE gets a path, not a URI; Xfce reports how many monitor and
   workspace properties it wrote; Plasma verifies by reading back.
8. History lists every apply and undo with its backup, and the manifest can be shown.
9. **No `sudo`, no `pkexec`, no write outside `$HOME`** anywhere in M4 — enforced by the test wrapper.
10. `linwp plan|apply|undo|history` match the GUI, with `--json` and documented exit codes.

## M4 risks

| Risk | Mitigation |
| --- | --- |
| The desktop writes the setting back (its own settings dialog is open, or a slideshow ticks) | Verify by reading back after a short settle; if it changed, report it rather than fighting; slideshow state is captured and restored by undo |
| GNOME's dark-variant key is forgotten and the wallpaper "reverts at night" | Both keys are part of one step; a test asserts both are written and verified |
| Xfce's per-monitor/workspace property explosion leaves some screens unchanged | Enumerate rather than guess, write all, and report the count in the result |
| Plasma tooling differs between versions | `plasma-apply-wallpaperimage` first, scripted D-Bus fallback, both verified by config read-back; unsupported versions say so |
| Undo becomes unreliable once the user edits things by hand | Drift detection, manifests that record what was expected, and a History page that reads as a stack |
| The transaction engine gets rewritten for root in M5 | M4 deliberately builds the *whole* engine; M5 adds providers and one execution backend, and the plan JSON is already the helper's input format |

## After M4

M5 adds the privileged half — specified below.

---

# M5 — Apply (privileged)

**Goal:** the product's reason to exist. The login screen, boot splash and boot menu change from one click,
through a one-shot helper, with one authorization — reproducing exactly what
[`reference/apply-08-screen-wallpaper.sh`](../reference/README.md) does by hand, inside M4's transaction.

**Demo at the end of M5:** press *Apply everywhere*, authorize once, watch eleven steps run in about
25 seconds, log out to a new login screen and reboot into a new boot menu and splash — then press Undo and
get the distribution's defaults back. `linwp apply <image> --surface all` does the same from a TTY.

### In scope
The one-shot `pkexec` helper and its allow-listed operations, the polkit actions and authorization flow, the
greeter providers (slick-greeter, lightdm-gtk-greeter), the Plymouth provider (initramfs-tools), the GRUB
provider, the boot-safety net, `/var/backups` manifests, the live splash check, and `linwp doctor` in full.

### Not in scope
GDM and SDDM greeters, the dracut back end, and the remaining distribution shapes — M6, and they are new
providers behind the same helper operations. Sync mode is M6.

---

## M5.1 — The helper

- [ ] `/usr/libexec/lin-wallpapers-helper` — a one-shot executable: reads one plan as JSON on stdin,
      performs it, writes a JSON result on stdout, exits. **No daemon, no D-Bus name, no service unit**
      (concept §11.1–11.2)
- [ ] Allow-listed operations only: `probe`, `write_system_image`, `edit_ini`, `install_theme`,
      `set_alternative`, `write_dropin`, `regen_initramfs`, `regen_bootmenu`, `revert_backup`. No
      "write this file" primitive, no operation taking a shell command or a destination path — destinations
      are constants in the helper, checked with `realpath` against an allow-list
- [ ] Input is re-validated, never trusted: the image arrives as a file descriptor with a declared sha256; the
      helper re-hashes, re-decodes under a pixel/time budget, and **re-runs the transform itself**
- [ ] Subprocesses: absolute paths, argument vectors, fixed environment, timeouts, no shell — only
      `update-initramfs`/`dracut`, `update-grub`/`grub-mkconfig`, `update-alternatives`, `plymouthd`/`plymouth`
- [ ] In-process hardening: `umask 022`, dropped ambient capabilities, `NoNewPrivileges` via `prctl`, work in a
      `mkdtemp` under `/var/tmp` that it removes; optional `systemd-run --scope` wrapper where systemd exists
- [ ] Structured progress on stderr (one JSON line per step) so the GUI shows real progress, and everything
      lands in the journal for a post-mortem
- [ ] Exit codes: success, refused, precheck failed, failed-and-rolled-back, failed-and-rollback-failed (the
      last one is the only case that ever asks the user to act, and it names the backup directory)

## M5.2 — Authorization

- [ ] Four polkit actions — `…apply.login-screen`, `…apply.boot-splash`, `…apply.boot-menu`, `…revert` —
      with clear message strings; default `auth_admin_keep`
- [ ] **One prompt per apply:** a five-surface apply is one plan, one helper run, one authorization
- [ ] No polkit agent, or authorization refused → the plan stops before any write, the sheet says so, and
      Retry is offered. Nothing half-applied, no password ever handled by the app
- [ ] `linwp` from a TTY uses `pkexec` the same way, or runs directly when already root (a plain
      `sudo linwp apply` must work for recovery)
- [ ] The polkit rule that sync mode (M6) may install is **not** written here; M5 only ever prompts

## M5.3 — Greeter providers

- [ ] `greeter_slick` — render to `/usr/share/backgrounds/lin-wallpapers/wallpaper.jpg` (dir 0755, file 0644,
      root-owned), then `background=` and `draw-user-backgrounds=false` in `/etc/lightdm/slick-greeter.conf`
- [ ] `greeter_lightdm_gtk` — the same image, `[greeter] background=` in `/etc/lightdm/lightdm-gtk-greeter.conf`
- [ ] The INI editor from the base script (`set_ini`/`del_ini`): create the file and section when missing,
      replace in place otherwise, never reformat the rest of the file, never touch `lightdm.conf` (a conffile)
- [ ] **Verification that matters:** re-read the config, resolve the path, and confirm the file is readable
      *as the greeter's user* (`lightdm`) — the failure mode this product exists to prevent is a grey login screen
- [ ] Revert: delete the two keys, remove the installed image, leave the file otherwise untouched

## M5.4 — Plymouth provider

- [ ] Generate the theme into `/usr/share/plymouth/themes/lin-wallpapers/` from
      `resources/plymouth-template/` — the `.plymouth` manifest, the script (background sprite at z = −100,
      spinner at 75 % height, password/question/message callbacks) and the rendered `wallpaper.png`
- [ ] Spinner frames: copied from whichever theme `default.plymouth` currently resolves to (`mint-logo`,
      `bgrt`, `spinner`, …); if it has none, draw a fallback spinner from the accent colour. Copied frames stay
      under their own licences ([NOTICE](../NOTICE))
- [ ] `update-alternatives --install … default.plymouth … 150` then `--set` — the base script's exact pair
- [ ] Initramfs behind an interface (`InitramfsBackend`): `initramfs-tools` in M5 (`update-initramfs -u -k all`),
      dracut in M6. Whichever owns `/boot/initrd.img-*` is chosen by probe
- [ ] **Verification:** for every installed kernel, the rebuilt image contains the theme's `.plymouth`, its
      script and `wallpaper.png` (`lsinitramfs | grep`) — the check that was done by hand after the base script ran
- [ ] Revert: alternative back to the previous theme recorded in the manifest, theme directory removed,
      initramfs rebuilt again, verified again
- [ ] Live check: `plymouthd` + `plymouth --show-splash`, 8 s, `plymouth quit` — offered after an apply, never
      automatic, and skipped when a session is not on a VT that can show it

## M5.5 — GRUB provider

- [ ] Render the 8-bit PNG to `/boot/grub/lin-wallpapers.png` at the detected `GRUB_GFXMODE`
- [ ] Write `/etc/default/grub.d/99-lin-wallpapers-background.cfg` (`GRUB_BACKGROUND`, `GRUB_GFXMODE`) — only
      when it differs (`cmp -s`), and **never** `/etc/default/grub`, which is a package conffile
- [ ] Regenerate with `update-grub`, or `grub-mkconfig -o <detected grub.cfg>` where that is what exists
      (BIOS, EFI, and vendor paths under `/boot/efi/EFI/<vendor>/`)
- [ ] Verification: `grub.cfg` is newer than the drop-in and references the image; the PNG decodes under
      GRUB's constraints (colour count, size)
- [ ] Revert: drop-in and image removed, `grub.cfg` regenerated, verified

## M5.6 — Boot safety net

- [ ] **Validate before installing:** the generated theme is rendered offscreen and the GRUB PNG decoded; a
      failure aborts before anything is written
- [ ] Prechecks: `/boot` writable and with free space for every kernel's initramfs, no `apt`/`dpkg` lock held,
      kernels enumerated, current alternative recorded
- [ ] **Order:** all file writes first, the two expensive regenerations last, one of each per apply
- [ ] Cancellation is refused *during* an initramfs rebuild (the one step that must not be interrupted), and
      the UI says why
- [ ] If the rebuild fails: restore the previous alternative, rebuild again, verify, and report — the machine
      must never be left with a theme that is not in its initramfs
- [ ] `docs/recovery.md` and an in-app panel: remove `splash` from the kernel line in the boot menu for one
      boot, then `sudo linwp undo`; the base script's `--undo` remains the backstop
- [ ] Release checklist (`docs/release-checklist.md`): the one thing CI cannot do — a real reboot on the
      reference machine, plus a VM per distribution shape — run and signed off per release

## M5.7 — Apply everywhere

- [ ] One plan covering all five surfaces: user-space steps executed in-process (M4), privileged steps handed
      to a single helper run, expensive steps batched once
- [ ] Progress across the whole apply, with the initramfs step showing its own longer estimate
- [ ] The result panel verifies all five and states when each takes effect; History rows reference the
      `/var/backups/lin-wallpapers/<timestamp>/` manifest
- [ ] Undo spans both halves: user settings restored in-process, privileged files restored by the helper under
      the `…revert` action, with the same drift detection M4 introduced

## M5.8 — CLI and doctor

- [ ] `linwp apply <image> --surface all|login|splash|menu`, `linwp undo`, `linwp plan --json` — the privileged
      half wired to the same code the GUI uses
- [ ] `linwp doctor` in full: the machine model, every provider's verdict and evidence, privileged prechecks
      (polkit agent, `/boot` space and writability, kernels, initramfs generator, GRUB path), and what would
      block each surface. `--json` is the bug-report format, and it seeds a new fake root
- [ ] `linwp preview --surface splash --live` runs the 8-second splash check

## M5.9 — Tests

- [ ] **Fake-root integration:** apply and revert into `tests/fakeroot/<shape>/` with fake `update-initramfs`,
      `update-grub` and `update-alternatives` binaries that record their arguments; assert the resulting tree,
      the recorded commands, and the rolled-back tree
- [ ] **Helper unit tests:** malformed plans rejected, unknown operations rejected, destinations outside the
      allow-list rejected, path traversal rejected, mismatched sha256 rejected, no shell ever invoked
- [ ] **Failure injection** at each privileged step, including a failing initramfs rebuild, asserting restore
      of the previous alternative and a successful second rebuild
- [ ] **Verification tests:** a greeter image that `lightdm` cannot read fails verification; a theme missing
      from one kernel's initramfs fails verification
- [ ] **Conffile test:** no package conffile is modified during any apply (`dpkg --verify` clean afterwards)
- [ ] **Nothing left running:** after an apply, no helper process exists and no unit was created
- [ ] Container/VM runs for at least Mint Cinnamon and Debian Xfce shapes; the real-reboot checklist covers
      what containers cannot

### Deferred out of M5 (on purpose)
GDM and SDDM, dracut, and the remaining fake-root shapes (M6). They add providers and one backend behind the
same helper operations — no new mechanism, no new privilege.

---

## M5 acceptance criteria

1. On the reference machine, *Apply everywhere* reproduces the base script's result exactly: the same
   greeter keys, the same installed image, the theme selected through `update-alternatives`, the theme
   present in every kernel's initramfs, the GRUB drop-in and a regenerated `grub.cfg`.
2. One authorization prompt for the whole apply; refusing it leaves the machine untouched.
3. Verification runs before commit, and a failure at any step rolls back completely and says which step failed.
4. Undo restores the distribution defaults, verified the same way, including the initramfs rebuild.
5. `dpkg --verify` reports no modified conffiles after an apply and after an undo.
6. A reboot on the reference machine shows the new boot menu and splash, and a logout shows the new login
   screen — recorded in the release checklist.
7. The helper rejects malformed plans, unknown operations, traversal attempts and hash mismatches; it never
   invokes a shell.
8. After an apply, no helper process is running and nothing was enabled: `pgrep`, `systemctl list-unit-files`
   and `~/.config/autostart` are all clean.
9. `linwp apply --surface all` from a TTY (via `pkexec` or as root) matches the GUI, and `linwp doctor --json`
   explains any surface it would refuse.
10. Fake-root integration passes for the Mint and Debian Xfce shapes, asserting both the applied tree and the
    rolled-back tree.

## M5 risks

| Risk | Mitigation |
| --- | --- |
| A bad theme or a failed rebuild spoils boot | Offscreen validation before install, initramfs content verification, automatic restore-and-rebuild, `docs/recovery.md`, and the `splash`-removal escape |
| `/boot` fills during the rebuild | Precheck free space for every kernel; refuse rather than half-write |
| The greeter shows grey because it cannot read the image | The copy step is part of the plan, and verification re-reads the file as the greeter's user |
| A package upgrade later overwrites the change | Drop-ins only, never a conffile; `dpkg --verify` in CI |
| `update-alternatives` fights the distribution's own theme selection | Priority 150 with an explicit `--set`, previous selection recorded in the manifest, and revert restores it |
| A user cancels mid-rebuild | Cancellation refused during that one step, with the reason shown |
| The helper becomes a general-purpose root writer over time | Fixed operation list, destinations as constants, no path arguments, review rule in `.claude/rules/privileged-helper.md` |
| CI cannot prove a real boot | Documented per-release reboot checklist on the reference machine plus VM runs per distribution shape |

## After M5

M6 widens the same machinery and makes the app explain itself — specified below.

---

# M6 — Breadth, explanation and release

**Goal:** the same build behaves well on any Debian-based system — doing what that system supports, saying
clearly what it does not, and logging why — then ships as a `.deb`.

**Demo at the end of M6:** the same package installed on Mint Cinnamon, Ubuntu GNOME, Debian Xfce, Kubuntu
and MX. On each, the screens it can change are live; the ones it cannot are **greyed out, still visible**,
labelled *"Unsupported in Debian 12 — Plymouth isn't installed on this system"*, with a **Why?** popover
showing the evidence and a Diagnostics view that logs every one of those decisions. Sync mode can be turned
on, and turned back off, leaving nothing behind.

### In scope
The capability-state framework and reason-code catalogue, the activity log and Diagnostics page, GDM and
SDDM providers, the dracut initramfs back end, fake roots for five distribution shapes, sync mode,
collections and slideshows, `.deb` packaging with AppStream metadata, and the v1.0 release process.

### Not in scope
LXQt/Pantheon/Budgie desktops, per-monitor and Wayland refinements, and online scan sources — M7.

---

## M6.1 — Capability states and reason codes

- [ ] `src/capability/states.py` — the five states from [§15.1](../TECHNICAL-CONCEPT.md): `available`,
      `needs_authorization`, `degraded`, `unsupported`, `blocked`; every feature in the app resolves to one
- [ ] `src/capability/reasons.py` — the §15.2 catalogue: code → state, message template, expected evidence
      keys, optional remedy. Adding a reason means adding a catalogue entry, never a new string in a widget
- [ ] `src/capability/messages.py` — renders a code plus evidence into the headline
      *"Unsupported in {distribution} {version}"* (from `/etc/os-release`, with the pretty name) and the
      plain-language line beneath it
- [ ] A **feature registry**: not only the five surfaces but per-monitor wallpapers, slideshows, the live
      splash check, sync mode, each image format, and the boot-menu surface — every one resolvable and
      explainable, whether or not a provider exists for it here
- [ ] Providers return `(state, code, evidence, remedy?)`; returning prose, `False` or an exception-as-answer
      fails review and the contract tests
- [ ] Re-resolution on change: a package installed, a drive connected, a display added or `/boot` remounted
      flips a feature's state while the app is open, and the change is announced in place (no restart)

## M6.2 — The greyed-out treatment

- [ ] One component (`ui/components/capability_control.py`) wraps any control with its state: greyed but
      focusable and screen-reader readable, with the state's mark (shield for authorization, warning for
      degraded, muted for unsupported/blocked)
- [ ] Nothing is removed, ever: an unsupported surface keeps its card, its preview and its place on the
      Screens page, and says what it is missing
- [ ] **Why?** popover: headline, plain reason, the evidence list ("`/usr/sbin/plymouthd` not found";
      "`default.plymouth` alternative missing"), the remedy as text, **Copy diagnostics**, and **Open the log
      here** — which opens Diagnostics filtered to those lines
- [ ] Blocked ≠ unsupported: "temporarily unavailable" states say what to change and re-check themselves
- [ ] Applies never silently skip a surface: an unsupported target is reported in the plan as "will be
      skipped — {reason}", before the user presses Apply

## M6.3 — The activity log and Diagnostics

- [ ] `util/log.py` — JSON Lines to `~/.local/state/lin-wallpapers/log/`, one file per session, rotation at
      10 files / 20 MB, areas (`probe`, `scan`, `analyse`, `preview`, `apply`, `helper`, `capability`)
- [ ] Every probe verdict, scan summary, skipped path with its reason, plan, step outcome, authorization
      result, verification, rollback and capability state change is logged — the log is the app's account of
      itself, not a debug afterthought
- [ ] The helper's structured progress lines are captured into the same log and also land in the journal
- [ ] `pages/page_diagnostics.py` — the capability table (feature, state, reason, evidence) over the log
      viewer, with filters by area, level and session, and a search box
- [ ] **Copy diagnostics** bundles `linwp doctor --json`, the recent log and the distribution details; the
      same bundle seeds a test fake root
- [ ] No telemetry, no network calls — asserted by a test that fails on any outbound socket

## M6.4 — More providers

- [ ] `greeter_gdm` — the documented, reversible GResource/dconf path where it works; where it does not
      (Wayland-only or a locked-down configuration), the surface reports `OWNED_BY_OTHER` or
      `SESSION_UNSUPPORTED` and stays greyed out with the explanation
- [ ] `greeter_sddm` — `/etc/sddm.conf.d/` drop-in pointing the active theme's `background=` at the installed
      image; theme detection included, with `degraded` when the theme ignores the key
- [ ] `InitramfsBackend: dracut` — `dracut --regenerate-all --force`, with the same "theme present in every
      image" verification as initramfs-tools
- [ ] `bootmenu_none` — systemd-boot or no boot manager detected: the surface stays visible and greyed with
      the reason
- [ ] Every new provider ships: detection evidence, capabilities, plan/apply/verify/revert, a preview spec,
      reason codes, a fake-root golden test, and its row in the §4.2 matrix (the universality checklist)

## M6.5 — Distribution shapes and CI

- [ ] `tests/fakeroot/` completed for five shapes: Mint Cinnamon, Ubuntu GNOME, Debian Xfce, Kubuntu, MX
- [ ] **Capability matrix tests:** for each shape, and for deliberately broken variants (Plymouth absent, no
      GRUB, `/boot` read-only, no polkit agent, unknown greeter), assert the resolved state, the reason code
      and the rendered message for every feature
- [ ] Container runs in CI for the shapes that can run headless; the rest covered by the release checklist
- [ ] A "cold system" test: no catalogue, no settings, no network — first run still explains itself

## M6.6 — Sync mode

- [ ] `sync/agent.py` — watches the desktop wallpaper setting, debounces 10 s, checks the file is stable and
      suitable, then re-applies the enabled surfaces
- [ ] **Opt-in and off by default**, as a user-session autostart entry
      (`~/.config/autostart/lin-wallpapers-sync.desktop`) — not a system service, nothing enabled at install
- [ ] The authorization trade-off is stated before enabling: authorize each sync, or install a polkit rule
      for `apply.*` limited to the active local session. The rule is **shown in full** first, written by the
      helper, and removed when sync is switched off
- [ ] Turning sync off changes no screen; a test asserts the autostart file and any rule are gone afterwards
- [ ] Minimum interval so a fast slideshow never rebuilds the initramfs repeatedly; below it, only the
      user-space surfaces follow, and the UI says so

## M6.7 — Collections and slideshows

- [ ] Manual collections and smart collections (saved filter queries) on the Collections page
- [ ] A collection can be a desktop slideshow source where the desktop supports it; where it does not, the
      control is greyed with `PER_MONITOR_UNSUPPORTED`-style reasoning for slideshows
- [ ] Slideshow interaction with sync mode made explicit in one sentence in the UI, not in a doc only

## M6.8 — Packaging and release

- [ ] Two `.deb`s via `debhelper` + `dh-python`: `lin-wallpapers` (GUI + CLI) and `lin-wallpapers-helper`
      (helper + polkit actions). **`postinst` enables and starts nothing**
- [ ] `.desktop`, AppStream metainfo with screenshots, symbolic icons, GResource bundle, man pages for
      `lin-wallpapers` and `linwp`
- [ ] `lintian`-clean; install / upgrade / remove / purge tested, with purge leaving no units, no autostart
      entry and no root-owned leftovers outside `/var/backups` (which is kept deliberately, and documented)
- [ ] `docs/release-checklist.md` executed: real reboot on the reference machine, plus a VM per shape,
      covering apply, undo, log out and reboot
- [ ] Version, tag, `changelog.md`, release notes, and the README status line moved from "design phase" to
      shipped

## M6.9 — Tests

- [ ] Capability rendering tests: every code in the catalogue renders a complete sentence with real evidence
      (no `{placeholder}` left unfilled) — a table-driven test over the whole catalogue
- [ ] A "missing component" suite: remove Plymouth / GRUB / the greeter from a fake root and assert the app
      still starts, still browses, still applies what it can, and greys the rest with the right message
- [ ] Log assertions: a greyed control's "Why?" lines exist in the log with matching code and evidence
- [ ] Sync tests: enable → change wallpaper → surfaces follow; disable → nothing left behind
- [ ] Packaging tests in a container: install, run `--version`, purge, assert cleanliness

---

## M6 acceptance criteria

1. On a system without Plymouth, the boot splash stays visible, greyed, headed *"Unsupported in {distro}"*,
   with a plain reason, evidence, a remedy and a matching log entry — and the rest of the app works normally.
2. Every reason code in the catalogue renders a complete, plain-language sentence from real evidence.
3. Installing the missing component while the app is open flips the feature to available in place.
4. No feature is ever hidden or removed; a table-driven test enumerates the feature registry and asserts each
   is present in the UI in one of the five states.
5. The Diagnostics page explains every greyed control, and "Why?" jumps to the exact lines.
6. GDM, SDDM and dracut providers pass their fake-root tests; unsupported paths report codes rather than fail.
7. The capability matrix passes for all five distribution shapes and the broken variants.
8. Sync mode is off by default, enables with the trade-off stated, and removes its autostart entry and any
   polkit rule when disabled.
9. The packages install, upgrade, remove and purge cleanly, enable nothing, and are `lintian`-clean.
10. No telemetry and no outbound network connection, asserted by test.

## M6 risks

| Risk | Mitigation |
| --- | --- |
| Greyed-out controls become a graveyard of dead UI | States are specific ("Plymouth isn't installed", not "unavailable"), remedies are named, and blocked states re-check themselves |
| Reason messages drift into developer language | One catalogue, table-driven rendering tests, and plain-language review as part of the checklist |
| GDM's override is fragile across `gnome-shell` upgrades | Treated as `degraded` by default, documented as reversible, re-verified after upgrades, and reported honestly rather than silently failing |
| The log grows or leaks | Rotation, session files, `$HOME`-only paths, no network, purge documented |
| Sync mode's polkit rule becomes a permanent hole | Shown in full before writing, scoped to the active local session and the `apply.*` actions, removed when sync is disabled, and asserted by test |
| Packaging enables something by accident | `postinst` asserted to enable nothing; purge test checks units, autostart and leftovers |
| "Breadth" turns into an endless provider list | M6 ships exactly the providers listed here; anything else is M7 |

## After M6

M7 widens reach again — LXQt, Pantheon and Budgie, per-monitor and Wayland refinements, online scan sources —
each arriving as a provider with its own reason codes, greyed-out state and fake-root test, changing nothing
in the core.
