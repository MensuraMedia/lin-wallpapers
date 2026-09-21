# Status & Handoff — LinWallpaper

_Last updated: 2026-09-20 (late). The active deliverable is **LinWallpaper** (`linwallpaper/`), a small
GTK 4 + libadwaita desktop-wallpaper app. The earlier GTK 3 milestone project under `src/` is **superseded**
and kept only for history (see the note at the bottom). Latest commit: `8059381`._

## How to read status
✅ working & verified · 🟡 built, not live-verified in that environment · ⬜ not built.

---

## ✅ Working now (verified this machine: Cinnamon / X11)

| Area | State |
| --- | --- |
| GTK 4 + libadwaita app, sidebar shell, movable/resizable window, menu + panel icon | ✅ |
| Open any image (GdkPixbuf-derived filter), live preview, Fit (Fill/Fit/Center/Stretch) | ✅ |
| **Desktop apply** (Cinnamon `gsettings`), per fit → `picture-options`, **Undo** | ✅ read-back verified |
| **Screens page is the whole app** (Wallpaper page removed; opens on Screens; sidebar = Screens / Settings) | ✅ |
| Every surface as a **uniform, larger** fixed-aspect simulated monitor (primary-monitor aspect, no stretch) | ✅ |
| Monitors **line up across cards** — the left control column is a fixed width, so wrapping meta text no longer shoves the monitor sideways | ✅ verified (screenshot) |
| **Wallpaper page** — a tight thumbnail grid library; ships a **built-in default** (always first, non-removable); per-tile **Apply** / **Use in Screens** / **Remove** | ✅ verified (screenshot) |
| **Add images… / Add folder…** on the Wallpaper page; a folder adds every supported image inside it; originals are referenced, never copied | ✅ verified |
| **Screens → Image** now opens a **wallpaper picker** (the library as thumbnails) with a **Browse files…** fallback | ✅ verified (screenshot) |
| **Settings → Integration** toggle installs an **"Add to LinWallpaper"** file-manager right-click action (Nemo live; Nautilus/Thunar/Dolphin providers built) | ✅ Nemo verified; others built |
| **`python3 -m linwallpaper.addcli <paths>`** — the CLI the context action calls; adds files/folders to the library | ✅ verified |
| **Live-refresh** — the Wallpaper page watches the library dir (`Gio.FileMonitor`); a file-manager "Add to LinWallpaper" appears **instantly**, no restart/navigation | ✅ verified (screenshots) |
| **`install.sh` two modes** — user-level (run-from-checkout, default) and **`--system`** (copies the package to `PREFIX/lib/linwallpaper` + a `linwallpaper` launcher on PATH; `--prefix`, `--uninstall`) | ✅ both verified (temp prefix: install → run via launcher → uninstall) |
| Each card meta: **Supported file types** + **Current resolution** under the screen name | ✅ |
| Controls in **Image → Fit → Apply** order (per card and the global bar; Image shows the chosen filename) | ✅ |
| Global bar (**Image** + **Fit** + **Apply to all** → every desktop monitor + lock) | ✅ |
| Per-card **Image** + per-surface image override (each screen its own image) | ✅ |
| **Password dialog** on privileged surfaces (in-app; sudo here, no polkit agent) | ✅ dialog verified |
| Privileged helper `--dry-run` (backup-first, drop-ins only, idempotent, refuses without root) | ✅ verified |

## ✅ Now confirmed by the user
- **Live privileged apply (login / boot splash / boot menu) works.** The user applied the privileged
  surfaces and **rebooted**: *"everything applied as expected."* This closes the last open verification —
  the reversible helper (backups, drop-ins, `--undo`) sets the real greeter/splash/GRUB surfaces correctly.

## 🟡 Built, not verified in that environment
- Desktop backends **GNOME / MATE** (gsettings base), **Xfce** (xfconf, native per-monitor), **X11 feh** —
  implemented, only Cinnamon is live-tested here.
- Context-menu providers **Nautilus / Thunar / Dolphin** — implemented to the same interface as Nemo
  (`linwallpaper/contextmenu/`), only **Nemo** is live-tested here (the dev box is Cinnamon).

## ⬜ Not built
- KDE Plasma / wlroots (sway, Hyprland) desktop backends.
- Fedora (`dracut`/`grub2-mkconfig`) and Arch (`mkinitcpio`) privileged apply — see
  `docs/design/cross-distro-apply.md`.
- An in-app **Undo/Revert** button for the privileged surfaces (currently reverted from a terminal).

## Backlog
- **[low] On opening the app, the last-applied image is not shown in a surface's simulated monitor.**
  Reported after a successful apply + reboot (the real surfaces were set correctly — this is preview-only).
  The monitor preview comes up empty/placeholder instead of the image that was applied. User has deferred
  this: *"low priority at this time and can be addressed later."* Likely in the render precedence in
  `screens.py` (`resolved_image` → persisted `applied_image` → placeholder) and/or `applied.json`
  persistence in `state.py` — verify in the running app, not by tests.

## Open items / known notes
- Privileged render size defaults to **1920×1080** (or the primary monitor px) — a non-1080p greeter/boot
  panel would letterbox/crop (cosmetic).
- Active greeter unconfirmed here, so **login sets both** `slick-greeter.conf` and a `lightdm-gtk-greeter`
  drop-in (harmless).
- Benign `Gtk-WARNING … min height -1` from the aspect-pinned monitor layout — a warning, not a crash.
- The **Supported file types** line lists every installed pixbuf loader (wraps two lines, includes uncommon
  ones); could be trimmed to a common set — a one-liner in `screens.py::_supported_types_text()` — if wanted.
  It no longer affects layout: the left column is pinned to `_LEFT_COL_WIDTH` (screens.py), so every card wraps
  it identically and all the simulated monitors share the same left edge.
- The **live privileged apply (login/boot) is confirmed working** (user applied + rebooted). Revert any
  surface with: `sudo python3 linwallpaper/privileged/lw_privileged.py <login|splash|grub> --undo`.
- Offered but not built: an in-app **Undo/Revert** button for the privileged surfaces.

## Run / verify
```
python3 -m linwallpaper.main      # or ./linwallpaper/run.sh ; install: ./linwallpaper/install.sh
python3 -m pytest linwallpaper -q
.venv/bin/ruff check linwallpaper
```
The way to trust a GUI change here is to **run it** (or drive a real input event) — not just green tests;
that lesson is baked into how this app was verified.

## Docs
- `README.md` — LinWallpaper, features, OS-support tables, install/usage/safety.
- `docs/design/wallpaper-collections.md` — the Wallpaper library + "Add to LinWallpaper" concept & as-built.
- `docs/design/minimal-gtk4-app.md` — the concept / as-built design.
- `docs/design/cross-distro-apply.md` — plan to make the privileged apply universal.
- `reference/apply-08-screen-wallpaper.sh` — the origin script the privileged helper reproduces.

---

### Note on the superseded GTK 3 project (`src/`)
The repo also contains an earlier, larger GTK 3 milestone project (scanner/catalogue/apply engine, M0–M8).
It was assessed as not delivering the product and was **replaced** by LinWallpaper. Its code, docs
(`docs/orchestration.md`, `docs/milestones.md`, `docs/design/m1-architecture.md`) and `changelog.md`
remain for history but are **not** part of LinWallpaper.
