# Status & Handoff — LinWallpaper

_Last updated: 2026-09-20. The active deliverable is **LinWallpaper** (`linwallpaper/`), a small GTK 4 +
libadwaita desktop-wallpaper app. The earlier GTK 3 milestone project under `src/` is **superseded** and
kept only for history (see the note at the bottom)._

## How to read status
✅ working & verified · 🟡 built, not live-verified in that environment · ⬜ not built.

---

## ✅ Working now (verified this machine: Cinnamon / X11)

| Area | State |
| --- | --- |
| GTK 4 + libadwaita app, sidebar shell, movable/resizable window, menu + panel icon | ✅ |
| Open any image (GdkPixbuf-derived filter), live preview, Fit (Fill/Fit/Center/Stretch) | ✅ |
| **Desktop apply** (Cinnamon `gsettings`), per fit → `picture-options`, **Undo** | ✅ read-back verified |
| **Screens page**: every surface as a fixed-aspect **simulated monitor** (no stretch) | ✅ |
| Global bar (Fit + Open image + **Apply to all** → desktop + lock) | ✅ |
| Per-card **Open image…** + per-surface image override (each screen its own image) | ✅ |
| **Password dialog** on privileged surfaces (in-app; sudo here, no polkit agent) | ✅ dialog verified |
| Privileged helper `--dry-run` (backup-first, drop-ins only, idempotent, refuses without root) | ✅ verified |

## 🟡 Built, not verified in that environment
- Desktop backends **GNOME / MATE** (gsettings base), **Xfce** (xfconf, native per-monitor), **X11 feh** —
  implemented, only Cinnamon is live-tested here.
- **Privileged apply** for **login / boot splash / boot menu** — implemented (reversible, backups, `--undo`),
  but the *live* root apply is **user-tested** (no passwordless sudo here; the assistant will not rebuild
  initramfs/GRUB in a test). Login is the safest to try first; boot splash/menu rebuild initramfs/GRUB.

## ⬜ Not built
- KDE Plasma / wlroots (sway, Hyprland) desktop backends.
- Fedora (`dracut`/`grub2-mkconfig`) and Arch (`mkinitcpio`) privileged apply — see
  `docs/design/cross-distro-apply.md`.
- An in-app **Undo/Revert** button for the privileged surfaces (currently reverted from a terminal).

## Open items / known notes
- Privileged render size defaults to **1920×1080** (or the primary monitor px) — a non-1080p greeter/boot
  panel would letterbox/crop (cosmetic).
- Active greeter unconfirmed here, so **login sets both** `slick-greeter.conf` and a `lightdm-gtk-greeter`
  drop-in (harmless).
- The simulated monitors are being made a **larger, consistent size** (in progress) and the **Wallpaper
  page is being removed** (Screens now carries the whole flow).
- Benign `Gtk-WARNING … min height -1` from the aspect-pinned monitor layout — a warning, not a crash.

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
- `docs/design/minimal-gtk4-app.md` — the concept / as-built design.
- `docs/design/cross-distro-apply.md` — plan to make the privileged apply universal.
- `reference/apply-08-screen-wallpaper.sh` — the origin script the privileged helper reproduces.

---

### Note on the superseded GTK 3 project (`src/`)
The repo also contains an earlier, larger GTK 3 milestone project (scanner/catalogue/apply engine, M0–M8).
It was assessed as not delivering the product and was **replaced** by LinWallpaper. Its code, docs
(`docs/orchestration.md`, `docs/milestones.md`, `docs/design/m1-architecture.md`) and `changelog.md`
remain for history but are **not** part of LinWallpaper.
