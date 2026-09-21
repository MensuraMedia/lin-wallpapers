# Concept — Wallpaper collections & "Add to LinWallpaper"

_Status: concept + first implementation. Covers the **Wallpaper** page, the collection data
model, the **Add to LinWallpaper** file-manager context menu, and how a collection feeds the
**Screens** page's *Image* picker._

---

## 1. Goal & user stories

LinWallpaper today opens *one* image at a time through a file dialog. This feature gives it a
small, persistent **library** of wallpapers the user curates once and reuses everywhere.

- *As a user* I open the app and see a **Wallpaper** page with at least one wallpaper — the
  **built-in default** that ships with the app — so the page is never empty.
- *As a user* I **right-click** an image (or a folder, or a multi-selection) in my file manager
  and choose **"Add to LinWallpaper"**; those images appear on the Wallpaper page.
- *As a user* I click a wallpaper on that page and **apply it** (to all desktop monitors) in one
  click, or send it to the **Screens** page to place it per-surface.
- *As a user*, when I click **Image** on a Screens card, my **collection appears** first — I pick
  from it, or fall through to a normal file browse.
- *As a user* I can turn the **context-menu integration on/off** in **Settings**.

Design rule for the whole feature: **never destroy or move the user's files.** The library stores
*references* (absolute paths) plus small cached thumbnails; the originals are never modified. (The
one copied file in the whole feature is the built-in default that ships inside the app.)

---

## 2. Data model

### 2.1 The collection index (gi-free service)

A single service module, `linwallpaper/collection.py` (no `gi` — it lives in the service layer),
owns the library. It reads/writes one JSON index:

```
$XDG_DATA_HOME/linwallpaper/collection.json      (default ~/.local/share/linwallpaper/…)
```

```jsonc
{
  "version": 1,
  "items": [
    { "path": "/home/user/Pictures/beach.jpg", "added": "2026-09-21T07:40:00Z" },
    { "path": "/home/user/Pictures/city.png",  "added": "2026-09-21T07:41:12Z" }
  ]
}
```

- **Built-in default** is *not* stored in the index — it is always injected at the front of the
  list from `linwallpaper/data/wallpapers/default-graphite-wood.jpg` (shipped inside the package,
  EXIF-stripped). It cannot be removed. This guarantees the page is never empty.
- **De-duplication** by real path. Adding the same file twice is a no-op.
- **Validation on add**: each candidate goes through `imaging.validate()`; unreadable/non-image
  files are skipped and reported in the return value (count added / skipped).
- **Missing files**: an entry whose path no longer exists is shown greyed with a "file moved or
  deleted" reason (project rule: *never hide a feature — grey it out with a reason*), and offers
  **Remove**. It is not silently dropped.

Public API (all pure-Python, unit-testable against a temp dir):

```python
class Collection:
    def __init__(self, data_dir: Path | None = None): ...
    def items(self) -> list[Item]            # built-in first, then index order
    def add_paths(self, paths) -> AddResult   # files and/or dirs → (added, skipped, dirs_scanned)
    def remove(self, path) -> bool
    def contains(self, path) -> bool
```

`add_paths` accepts files **and** directories. A directory contributes every supported image
**directly inside it** (non-recursive in v1; recursion is a future toggle — see §8). Support is
decided by `imaging.validate()`, so it matches exactly what the desktop can decode.

### 2.2 Thumbnails

Tiles render from a cached thumbnail so the grid is fast and never decodes full 4K files on the UI
thread:

```
~/.cache/linwallpaper/thumbs/<sha1(path|mtime)>.png     (e.g. 320×200, "cover" crop)
```

Thumbnails reuse the existing `imaging.transform(path, size, FIT_FILL)` — the *same* render the
previews and apply already use — so what the tile shows matches what gets applied. A stale
thumbnail is detected by the mtime in the cache key and re-rendered.

---

## 3. The Wallpaper page

A new page `ui/pages/wallpaper.py` (`route="wallpaper"`), registered in `window.py` and added to
`NAV_ITEMS` between **Screens** and **Settings**.

```
┌───────────────────────────────────────────────────────────┐
│ Wallpaper                                                   │
│ Your library — apply one to every screen, or send it to     │
│ Screens to place it per-surface.                            │
│                                                             │
│  [ + Add images… ]  [ + Add folder… ]        12 wallpapers  │
│                                                             │
│  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐            │
│  │DFLT │ │ img │ │ img │ │ img │ │ img │ │ img │  …          │
│  └─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └─────┘            │
│   Default  beach   city    ...                              │
└───────────────────────────────────────────────────────────┘
```

- A **`Gtk.FlowBox`** of thumbnail tiles, "displayed neatly and tightly" — homogeneous tiles,
  small gutters, wraps to the width. Each tile = thumbnail (fixed aspect) + filename caption; the
  built-in default carries a small **"DEFAULT"** badge and no Remove.
- **Tile actions** (hover buttons / context menu on the tile):
  - **Apply** — set it on every desktop monitor + lock now (uses the desktop backend, with the
    same Undo toast Screens uses).
  - **Use in Screens** — set it as the global image and navigate to **Screens** so the user can
    choose fit/surface and apply to login/boot too.
  - **Remove** — drop it from the library (originals untouched; disabled on the built-in).
- **Add controls** at the top: **Add images…** (multi-select file dialog) and **Add folder…**
  (folder dialog) — the in-app equivalent of the context menu, so the feature works even without
  the file-manager integration installed.
- **Refresh (live)**: the page watches the library directory with a `Gio.FileMonitor` and reloads +
  repopulates whenever `collection.json` changes, so an image added by the context menu (a *separate*
  `addcli` process) appears **instantly**, without a restart or navigation. `refresh()` also reloads
  from disk on navigation, and the picker reloads before it lists. (The in-memory `Collection` caches
  its list, so a plain re-render would not see external writes — `Collection.reload()` re-reads the
  index; this was a real bug, now fixed.)

---

## 4. "Add to LinWallpaper" context menu

### 4.1 The entry point — a tiny CLI

The context menu action calls a stable, GUI-free entry point that appends paths to the library and
exits:

```
python3 -m linwallpaper.addcli <path> [<path> …]
```

`addcli.py` (gi-free) constructs `Collection()`, calls `add_paths(argv)`, prints a one-line
summary, and — if an instance is running — the running app picks the change up on the next visit to
the Wallpaper page (v1) or via a file-watch (future). No new files are copied; only the index is
updated. This is the single integration seam every file manager targets.

### 4.2 Providers, not conditionals

File managers each have their own extension format. Per the project rule (*providers, not
conditionals; no branch on a desktop name outside a provider's `detect()`*), each lives behind a
provider in `linwallpaper/contextmenu/`:

| Provider | File manager | What it installs (user-level, no root) |
| --- | --- | --- |
| `nemo.py`    | Nemo (Cinnamon)         | `~/.local/share/nemo/actions/linwallpaper-add.nemo_action` |
| `nautilus.py`| Nautilus (GNOME)        | a script in `~/.local/share/nautilus/scripts/Add to LinWallpaper` |
| `thunar.py`  | Thunar (Xfce)           | a `<action>` merged into `~/.config/Thunar/uca.xml` |
| `dolphin.py` | Dolphin (KDE)           | `~/.local/share/kio/servicemenus/linwallpaper-add.desktop` |

Each provider implements:

```python
class ContextMenuProvider:
    name: str
    def detect(self) -> float           # 0..1 confidence this FM is the active one
    def is_installed(self) -> bool
    def install(self, exec_cmd) -> None  # writes its entry, points at addcli
    def uninstall(self) -> None
```

`detect()` uses evidence only — the file manager on `PATH`, `$XDG_CURRENT_DESKTOP`, the running
FM process — never a distro name. `detect_context_provider()` returns the highest-confidence
provider, mirroring `backends.detect_backend()`.

Example — the Nemo action (Cinnamon, the live dev environment):

```ini
[Nemo Action]
Name=Add to LinWallpaper
Comment=Add the selected image(s) to your LinWallpaper library
Exec=python3 -m linwallpaper.addcli %F
Icon-Name=io.mensuramedia.LinWallpaper
Selection=NotNone
Extensions=jpg;jpeg;png;webp;bmp;tiff;gif;
Quote=double
```

`Extensions=dir;` is added so **folders** are eligible too; `%F` passes every selected path, so a
multi-selection or a folder all arrive in one call. Nemo hot-loads actions from that directory — no
restart needed.

### 4.3 The Settings toggle — "Add Context Option"

In **Settings**, a new group **Integration** with a switch **"Add to file-manager right-click
menu"** and a subtitle naming the detected file manager (e.g. *"Nemo — right-click images → Add to
LinWallpaper"*). Toggling:

- **On** → `provider.install(exec_cmd)` and persist `context_menu=true`.
- **Off** → `provider.uninstall()` and persist `false`.
- **No supported FM detected** → the row is shown **disabled with a reason** ("no supported file
  manager detected"), never hidden.

The setting persists in a small gi-free settings store:

```
$XDG_CONFIG_HOME/linwallpaper/settings.json   →  { "context_menu": true }
```

The `exec_cmd` written into the action is resolved the same way `install.sh` resolves the app's
`Exec=` — it points at this checkout (or the installed launcher) so the action runs the right
interpreter/module.

---

## 5. Screens integration — the collection *is* the picker

When the user clicks **Image** on a Screens card (global bar or a per-surface card), instead of a
bare file dialog they get a **wallpaper picker** that shows the collection first:

```
┌──────────── Choose a wallpaper ─────────────┐
│  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐            │
│  │DFLT │ │ img │ │ img │ │ img │  …          │
│  └─────┘ └─────┘ └─────┘ └─────┘            │
│                                              │
│                   [ Browse files… ]  [Cancel]│
└──────────────────────────────────────────────┘
```

- Picking a tile calls the *existing* `on_chosen(path)` callback that `_on_open_global` /
  `_on_open_surface` already pass — so nothing downstream changes; the picker just supplies the
  path the file dialog used to.
- **Browse files…** falls through to the current `Gtk.FileDialog`, so the file-anywhere workflow
  is preserved. A file chosen that way can optionally be offered "Add to library too".
- The picker is one widget (`ui/wallpaper_picker.py`) reused by both the global and per-surface
  Image buttons.

This satisfies: *"when they choose 'Image' in the 'Screens' page, LinWallpaper Wallpaper
collections will appear."*

---

## 6. Layering, conventions & safety

- **Layering** (import-linter contracts): `collection.py`, `addcli.py`, `contextmenu/*` are
  **service-layer, gi-free**. Only `ui/pages/wallpaper.py` and `ui/wallpaper_picker.py` import
  `gi`. Widgets never touch the filesystem directly — they go through `Collection`.
- **Providers, not conditionals** for the file-manager integration, exactly like `backends/`.
- **Tokens only / no fake data**: tiles are real library entries; an empty library still shows the
  real built-in default, not a mock.
- **Non-destructive**: originals are referenced, never copied, moved, renamed or stripped. (EXIF
  stripping applies only to the one *shipped* default asset, done once at build time.)
- **No daemon**: the CLI runs once and exits; the context-menu action is a one-shot `Exec=`. The
  app itself remains one-shot/no-background.
- **Tests** run against `tests/fakeroot/` / temp dirs: `Collection` add/remove/dedupe/validate,
  folder scan, missing-file handling; each provider's `install()`/`uninstall()` writing into a
  fake `$HOME`; `addcli` argv handling. No test touches the real `~/.local/share` or a real FM.

---

## 7. What ships in the first implementation

1. **Built-in default** asset (done): `data/wallpapers/default-graphite-wood.jpg`.
2. **`collection.py`** service + **Wallpaper page** (grid, add images/folder, apply, use-in-Screens,
   remove) + nav entry.
3. **`addcli.py`** entry point.
4. **`contextmenu/`** with the **Nemo** provider live (the dev environment is Cinnamon), plus the
   provider base + `detect_context_provider()`; Nautilus/Thunar/Dolphin providers are stubbed to
   the same interface and filled next.
5. **Settings** "Integration" toggle wired to the detected provider + the settings store.
6. **Screens** Image buttons routed through the new wallpaper picker.

Verification is by hand on the live box (launch + screenshot the page and picker; run `addcli` and
check the index; toggle the setting and confirm the `.nemo_action` file lands and Nemo shows the
entry), not by green tests alone — the standing lesson of this project.

## 8. Open questions / future

- **Multiple named collections** ("Nature", "Work") vs. today's single flat library. The index
  format has a `version` field and room for a `collections: []` grouping later.
- **Recursive folder add** as an opt-in ("include sub-folders").
- ~~**Live sync**: watch `collection.json` so context-menu adds appear in an open window instantly.~~
  **Done** — the Wallpaper page uses a `Gio.FileMonitor` on the library dir (see §3).
- **Reorder / favourite / tags** on tiles.
- **Import-a-copy** option (for images on removable media) — off by default to preserve the
  non-destructive rule.
