# Lin Wallpapers — Status & Handoff

_Last updated: 2026-09-20. Companion to `docs/orchestration.md` (phase board), `changelog.md`
(chronological), and `.claude/memory/` (session notes). This file is the single "what works / what
doesn't / what's left" snapshot._

## How to read the status levels

| Level | Meaning |
| --- | --- |
| ✅ **Working** | In the codebase, tested, and confirmed to function (by tests that exercise the real path, and where relevant by a human in the running app). |
| 🧪 **Coded + tested, NOT live-verified** | Present in the code and passing unit/smoke tests, but the tests do **not** exercise the real end-user interaction, and it has **not** been confirmed working in the live GUI. May be broken in practice. |
| 📝 **Documented / mocked only** | Specified and/or mocked up. **No implementation.** |
| ⬜ **Not started** | — |

> **Honest headline:** the app is a working *catalogue browser* (it scans your folders, remembers
> them, and shows a filterable grid of your wallpapers). It **cannot set a wallpaper yet** — the
> apply engine does not exist. The Browse right-click **Exclude** actions are coded and unit/smoke
> tested but are **not confirmed working with a real right-click** (see the ⚠️ note below).

---

## ✅ Working now (verified)

### Scanning & catalogue (the engine)
- **Scan** a set of folders, in the GUI (Sources → Scan) and CLI (`linwp scan`). Nothing is scanned
  until you consent (no auto-scan).
- **Remembers** everything in `~/.local/share/lin-wallpapers/catalogue.db`: roots, images, displays.
  A rescan with no changes re-probes 0 files.
- **Roots discovery** — proposes your XDG Pictures, system wallpaper dirs, and mounted volumes
  (network/removable off by default with a reason).
- **Image probing** — dimensions, format, alpha/animation, safe against hostile/corrupt files.
- **Thumbnails** — sharded on-disk cache with eviction.
- **Exclusions engine** — folder/file/pattern rules and seven built-in groups (act on the catalogue,
  non-destructive). Reachable from `linwp exclude` and the Sources page.
- **Display detection** — GDK in the GUI, DRM/xrandr in the CLI; physical pixels; a
  `DISPLAY_NOT_DETECTED` reason when headless.
- **"Ideal for this desktop" scoring** — dimension arithmetic that flags which images cover your
  screen (no visual analysis yet — that's M2).

### GUI
- **Shell** — sidebar, routing, dark theme, the "THIS MACHINE" footer.
- **Sources page** — proposed folders with toggles, a **Scan** button, live scan progress, the
  detected-display strip, and the exclusion groups.
- **Browse page** — results grid with thumbnails, the **All / Ideal / Near misses** segment switch
  with live counts, search, and orientation/aspect/size filters. Grid fills from a real scan.
- **Scan-at-open** — first run lands on the Scan hero; later runs open to your library.

### CLI
- `linwp scan | list | show | exclude | displays`, with `--json` and correct exit codes.

### Packaging / integration
- **Launch icon** (hicolor SVG + symbolic) and **`.desktop`** entry; **`install.sh`** desktop
  integration; installed for the current user (appears in the Cinnamon menu under Preferences /
  search "Lin").

---

## ⚠️ Coded + tested, but NOT confirmed working in the live app

### Browse right-click → Exclude Image / Exclude Folder (+ Undo toast)  🧪
- **In the code** (committed): `BrowseVM.exclude_image/exclude_folder/undo_exclusion`,
  `ui/components/context_menu.py`, `ui/components/toast.py`, `compat.secondary_click_gesture` /
  `compat.menu_popover`, wired in `page_browse.py`. The underlying exclusion (rule → catalogue) is
  real and non-destructive.
- **Why it is NOT "done":** the unit and smoke tests invoke the menu handler **directly**
  (`page._open_card_menu(...)`, `browse_vm.exclude_image(...)`) — they never dispatch a real
  secondary-button (right-click) event through the `FlowBox`. So the tests can pass while a real
  right-click does nothing. **The user has reported the right-click does not work in the running
  app.** Likely cause: the `Gtk.FlowBox`/`FlowBoxChild` consumes the button event before the card's
  gesture fires, or the gesture is attached to the wrong target/phase.
- **To make it ✅:** reproduce a real right-click in the live app; if it doesn't open the menu, move
  the gesture to the widget that actually receives the event (or handle it on the `FlowBox` /
  `FlowBoxChild`), and add a smoke assertion that dispatches a synthetic button-3 event (not a direct
  handler call). **This is the top open item.**

---

## 📝 Documented / mocked only — NOT implemented

These are the rest of the right-click feature and the wallpaper-setting flow. Spec:
`docs/design/browse-context-menu.md`; artboards: `docs/mockups/{BrowseMenu,Collect,QuickApply}.dc.html`
(+ `png/`). In the current build the menu items **Add to Collection** and **Preview…** are shown
**disabled** with an "Arrives in M6 / M3" reason.

| Feature | What it needs | Milestone |
| --- | --- | --- |
| **Add to Collection** (dialog: pick existing / create new) | The deferred `collection` / `collection_item` tables (D9), a `CollectionsVM`, the picker dialog | M6.7 (self-contained; pullable earlier) |
| **Preview popup** (image at current resolution + per-surface checkboxes) | The M3 preview compositor (`transform()`), the Preview UI | M3 |
| **Apply** (set the checked surfaces) → land on **Screens** | The apply engine: desktop/lock providers + transaction/undo (M4), privileged login/splash/boot via the one-shot `pkexec` helper (M5), the Screens page (M3.5) | M3.5 / M4 / M5 |
| **Screens page** (all surfaces, providers, what's applied) | Provider detection + preview tiles | M3.5 |
| **Image detail page** | Score breakdown, palette, badges, crop frame | M2.6 / M3 |
| **Scoring, badges, duplicates** | The analysis pass | M2 |
| **Per-virtual-desktop wallpapers** | Feasibility study only — `docs/design/virtual-desktop-wallpapers.md` | exploratory |
| **System tray** | Out of scope by design (no background process / no daemon) | — |

---

## ⬜ Not started — remaining milestones

- **M1 · P7** — performance budgets (`docs/perf.md`), a 10k-image fixture, and the M1 acceptance run.
  This is all that's left to formally *close M1*.
- **M2 — Judgement** — scoring, badges, duplicate detection, the Image page.
- **M3 — Previews** — the transform pipeline, capability probes, the compositor, the Screens and
  Preview pages.
- **M4 — Apply (user space)** — the plan/executor/backup/undo, desktop + lock providers, the Apply UI.
- **M5 — Apply (privileged)** — the one-shot `pkexec` helper for login/splash/boot.
- **M6 — Reach / sync / capability states** — activity log, Collections, smart collections.
- **M7 — More providers, per-monitor, Wayland, optional online sources.**
- **M8 — GTK 4 port** (the code is written GTK-4-ready throughout).

---

## How to run & verify

```
./run.sh                      # launch the GUI (or use the menu launcher)
.venv/bin/linwp scan --help   # the CLI
make check                    # full gate: shellcheck, ruff, mypy, gtk4_lint, import-linter, pytest, smoke
```

- Current gate: **green** — 1305 unit + 24 smoke, mypy 83 files, 5 import contracts, gtk4_lint clean.
- The library at `~/Pictures/Wallpapers` (43 images) is already scanned into the catalogue.

## Where the handoff records live
- **`docs/orchestration.md`** — the phase board (P0…P7, P6-I/J) + the gate log (every adversary round).
- **`changelog.md`** — chronological, one row per change.
- **`.claude/memory/`** — `MEMORY.md` (index), `sessions/`, `pending.md`.
- **`docs/design/`** — `m1-architecture.md` (the M1 contract + rulings), `browse-context-menu.md`,
  `virtual-desktop-wallpapers.md`.

## Open items (priority order)
1. **⚠️ Verify/fix the Browse right-click** so a real right-click opens the Exclude menu (see the 🧪
   section) — currently the top gap between "tested" and "actually works."
2. Close **M1** with **P7** (perf + acceptance).
3. Decide whether to pull **Collections** (M6.7) forward as the next buildable menu item.
