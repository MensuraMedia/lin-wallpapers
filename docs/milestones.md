# Milestones

Delivery plan for Lin Wallpapers. Each milestone is a working, demonstrable state of the app — never a
half-integrated layer. Written per the universal instruction set: `/plan-first` before a milestone,
`/build-test` before each commit, `/session-end` at the end of a session, `changelog.md` updated as work
happens.

| | Milestone | Outcome |
| --- | --- | --- |
| **M0** | **Foundation** | The app opens, navigates and is themed; no features yet. Detailed below. |
| M1 | Catalogue | Scanner, SQLite catalogue, thumbnails, Sources page, Browse page with filters |
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

M1 begins with `/plan-first` on the scanner and catalogue: root discovery and the exclusion policy
([TECHNICAL-CONCEPT.md §5](../TECHNICAL-CONCEPT.md)), the SQLite schema (§7), the thumbnail cache, and the
Browse page bound to real rows.
