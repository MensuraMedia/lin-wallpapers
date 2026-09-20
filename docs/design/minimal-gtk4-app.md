# Technical concept — a small GTK 4 wallpaper app

_A deliberate change of tack from the M0–M8 project. One small GTK 4 application: open an image, choose all
screens or one, preview how it will look, apply it to the **desktop background**. No boot splash, no login
screen, no GRUB, no root, no daemon, no catalogue. This document covers both **how it works** (Part A) and
**the flat GTK 4 dashboard/sidebar GUI** built on
[gtk-python-dashboard-starter](https://github.com/mikesdatawork/gtk-python-dashboard-starter) (Part B)._

Status: **concept.** 2026-09-20. Environment-specific commands marked _(verify on target)_.

---

## 0. Scope — what this is, and what it drops

**In:** open any image the desktop can use as a background; detect the monitors; assign the image to **all
monitors or a chosen one**; a live **preview** of the fitted result; one click to apply; a modern flat
dashboard GUI with a sidebar.

**Out (the entire reason the big project stalled):** boot splash (Plymouth), login greeter, GRUB, the
privileged `pkexec` helper, the scanner/catalogue/scoring engine, sync mode. Desktop wallpaper is a
**user-session, no-root** operation — which is exactly why this version is small and shippable.

---

# Part A — How it works

## A1. User flow
1. **Open** — a file chooser filtered to image types; pick a file (or drag-and-drop onto the window).
2. **Target** — a toggle: *All screens* / a specific monitor (chosen from the detected list).
3. **Fit** — Fill (zoom + centre-crop, the default), Fit (letterbox), Centre, Stretch.
4. **Preview** — the image rendered exactly as it will appear on the target monitor(s), in a small mock
   desktop frame; a multi-monitor layout preview shows every screen with its assigned image.
5. **Apply** — writes the background through the detected backend. Done — nothing stays running (except on
   Wayland compositors that require a wallpaper process; see A5).

## A2. Supported image formats — whatever the system can load
Do not hardcode a list. Enumerate the installed **GdkPixbuf loaders** at runtime
(`GdkPixbuf.Pixbuf.get_formats()` → each format's mime types and extensions) and build the file-chooser
filter from them. That yields exactly the set the desktop's own settings accept: always PNG, JPEG, GIF, BMP,
TIFF, ICO, and — where the loader packages are installed — WebP, AVIF/HEIF, JPEG-XL, and SVG (librsvg). GTK 4
loads via `Gdk.Texture.new_from_filename()` (PNG/JPEG/TIFF fast path) or `GdkPixbuf` → `Gdk.Texture` for the
rest, then renders with `Gtk.Picture`.

## A3. Monitor detection (GTK 4, no `gi` gymnastics)
`Gdk.Display.get_default().get_monitors()` returns a `GListModel` of `Gdk.Monitor`. Each gives
`get_geometry()` (logical x/y/w/h in the global layout), `get_scale_factor()`, `get_connector()` (e.g.
`HDMI-A-1`), and `get_model()`. Physical pixels = geometry × scale. Subscribe to the model's
`items-changed` to react to hotplug. This is all the "Screens" knowledge the app needs.

## A4. Applying the desktop background — providers, not conditionals
Detect the running environment by **evidence** (`$XDG_CURRENT_DESKTOP`, `$WAYLAND_DISPLAY`/`$DISPLAY`,
which settings tool is on `PATH`) and pick a backend. None of these need root.

| Environment | Set the background | Per-monitor natively? |
| --- | --- | --- |
| **GNOME / Budgie / Unity** | `gsettings set org.gnome.desktop.background picture-uri 'file://…'` (+ `picture-uri-dark`, `picture-options`) | No — one image; use the composite trick (A6) |
| **Cinnamon** | `org.cinnamon.desktop.background picture-uri` | No — composite |
| **MATE** | `org.mate.background picture-filename '/path'` | No — composite |
| **Xfce** | `xfconf-query -c xfce4-desktop -p /backdrop/screen0/monitor<NAME>/workspace0/last-image -s /path` | **Yes** — one key per monitor |
| **KDE Plasma** | `qdbus org.kde.plasmashell /PlasmaShell evaluateScript "…"` iterating `desktopsForScreen` _(verify)_ | **Yes** — per screen |
| **LXQt** | `pcmanfm-qt --set-wallpaper /path --wallpaper-mode=…` | partial |
| **LXDE** | `pcmanfm --set-wallpaper /path` | partial |
| **X11, any WM (fallback)** | `feh --bg-fill IMG [IMG2 …]` or `xwallpaper --output NAME --zoom IMG` | **Yes** — one image argument per output |
| **wlroots (sway/Hyprland/river)** | `swaybg -o NAME -i IMG -m fill` / `swww img --outputs NAME IMG` / write the compositor `output … bg` line | **Yes** — per output (but needs a running process, see A5) |

Backend selection is a `WallpaperBackend.detect() → confidence` registry (the same evidence-based pattern the
current repo already uses for display detection). `os-release` is at most a tiebreaker, never the branch.

## A5. The one honest wrinkle — Wayland compositors need a process
On GNOME/KDE/Cinnamon (and X11 via the root pixmap) the background persists with **no** running helper — the
app writes a setting or the root pixmap and exits. On **wlroots** compositors the wallpaper is drawn by a
long-lived program (`swaybg`/`swww`/`hyprpaper`); persistence there requires either writing the compositor
**config** (so the compositor starts the wallpaper itself at login) or launching the wallpaper daemon. The
app should prefer **writing the config** (declarative, survives logout, nothing of *ours* runs) and say so in
the UI. This is the platform's reality, not a daemon of the app's own — consistent with "no background
process of ours."

## A6. "Apply to just one screen" on single-background desktops
GNOME/Cinnamon/MATE support only **one** background image (with a `picture-options` mode). To give one
monitor a different image, composite a single canvas the size of the whole monitor layout: paint each
monitor's current/assigned image into its rectangle, replace the **target** monitor's region with the new
image (fitted per A-fit), save the canvas to `~/.cache/lin-wallpaper/composite-<hash>.png`, and set it as the
background with `picture-options = spanned`. This is the standard technique and it reuses the same fit/crop
math as the preview, so **the preview equals the result**. On Xfce/KDE/X11-feh/wlroots the per-monitor key is
native and no compositing is needed.

## A7. Preview — "see it as applied"
One render function (`transform(image, monitor_px, fit)`) produces the exact bytes that will be applied;
the preview `Gtk.Picture` shows that same output scaled down, inside a thin "monitor" frame. A **layout
preview** draws the monitors as rectangles positioned by their `Gdk.Monitor` geometry, each filled with its
assigned image — so "all screens" vs "one screen" is visible at a glance before applying. Because preview and
apply share `transform()`, there is never a "looked different once applied" surprise.

## A8. Architecture (small, layered, testable)
```
app.py                       # Gtk.Application (GTK 4), single window, one-shot
ui/                          # GTK only: window, sidebar, pages, monitor cards, preview widget
  sidebar.py  pages/  components/
monitors.py                  # Gdk.Monitor → plain MonitorInfo DTOs (name, px, scale, geometry)
image.py                     # load + transform(image, size, fit) — the shared render (Pillow or GdkPixbuf)
backends/                    # one file per environment; a WallpaperBackend protocol + a registry
  gnome.py cinnamon.py mate.py xfce.py plasma.py x11_feh.py wlroots.py
  base.py                    # detect()/set(monitor|all, image, fit)/current()/supports_per_monitor
```
- **No `gi` below `ui/` and `app.py`** except `monitors.py` (which reads `Gdk`); backends shell out to the
  desktop's own tools and touch no GTK — trivially unit-testable with injected runners and a fake root.
- **One-shot.** The app applies and can exit; it never installs a service or autostart.
- **No root.** Everything is user-session settings or user-writable config.

---

# Part B — The flat GTK 4 dashboard GUI (from the starter)

Built on the `gtk-python-dashboard-starter` conventions, ported to GTK 4: a fixed **sidebar** of routes, a
content stack, `NAV_ITEMS` tuples, `register_page("<route>", page)`, and `BasePage.build_content()`. Modern,
flat, dark, one accent.

## B1. Window shell
- `Gtk.Application` + `Gtk.ApplicationWindow` (or **libadwaita** `AdwApplicationWindow` for the modern flat
  look and free light/dark). Root layout: a **150 px sidebar** (`Gtk.Box`, `.sidebar`) beside a
  `Gtk.Stack` content area — or, with libadwaita, an `AdwNavigationSplitView`/`AdwViewStack` + `AdwViewSwitcher`.
- Sidebar top: the app mark (a rounded tile + name); a vertical list of nav buttons bound to a `win.navigate`
  action (`Ctrl+1…n` accelerators); a small "This machine" footer showing the detected screens.
- Keep the starter's `register_page(route, page)` / `NAV_ITEMS = (label, route, icon)` / `BasePage` pattern so
  pages stay self-contained and the shell stays generic.

## B2. The pages (sidebar routes)
| Route | Purpose |
| --- | --- |
| **Wallpaper** (home) | The main flow: a big **Open image** button (`Gtk.FileDialog` + the format filter from A2) / drag-and-drop target; the chosen image; the **Fit** segmented control; the **Preview** (A7); a target toggle *All screens / This screen*; the **Apply** button. Everything one screen away from done. |
| **Screens** | Cards for each `Gdk.Monitor` — connector name, resolution × scale, primary badge, and the image currently assigned; click a card to set it as the per-screen target. Mirrors the layout preview. |
| **Preview** | A larger, full-window preview (the fitted image in a mock desktop with a panel/clock), and the multi-monitor layout view. |
| **Settings / About** | Default fit mode, remember-last-folder, the detected desktop/backend (with a reason if a surface is unsupported), version/credits. |

A minimal build can collapse this to **two** routes (Wallpaper + Screens); the sidebar makes adding Preview
and Settings trivial later.

## B3. Modern flat styling
- **Tokens only** in one CSS file: a dark surface set, a single accent, one on-accent text colour — the same
  discipline as the current repo (`@define-color`, no scattered hex), so a re-theme is one file. Flat
  surfaces, generous radii, subtle 1 px borders, no gradients except the logo tile.
- **libadwaita** is the fastest route to the "modern flat" look (adaptive, follows the system light/dark, gives
  `AdwToast` for the "Applied" confirmation and `AdwPreferencesPage` for Settings). Plain GTK 4 + CSS also works
  and matches the starter's hand-rolled sidebar more literally — pick one; the concept is agnostic.
- Widgets: `Gtk.Picture` (preview, `content-fit: cover`), `Gtk.FileDialog` (GTK 4.10+), `Gtk.DropTarget`
  (drag-and-drop), a segmented `Gtk.Box.linked` for Fit, `Gtk.Switch`/`Gtk.ToggleButton` for the target, an
  `AdwToast`/inline banner for "Applied to HDMI-A-1".

## B4. GTK 4 vs the current GTK 3 code
The existing repo is GTK 3 written to port to GTK 4; this concept starts **clean on GTK 4**. Reusable ideas
(not code) from it: the sidebar geometry and design tokens, the display-detection approach, and the single
`transform()` render that makes preview == apply. Everything scanner/catalogue/boot-related is dropped.

---

## C. Dependencies & footprint
- Runtime: `python3-gi`, `gir1.2-gtk-4.0`, `gir1.2-gdkpixbuf-2.0`, optionally `gir1.2-adw-1` (libadwaita);
  `python3-pil` **or** GdkPixbuf for the render. Backends call the desktop's own tools (`gsettings`,
  `xfconf-query`, `qdbus`, `feh`/`xwallpaper`, `swaybg`/`swww`) — declared, detected, greyed-with-reason when
  absent.
- A few hundred lines. No root, no daemon, no packaging beyond a `.desktop` + icon and the `install.sh` this
  repo already has.

## D. Non-goals / why this is achievable
- Not boot/login/splash/GRUB — those need root, a privileged helper, and per-distro providers (see
  `docs/design/cross-distro-apply.md`); this app deliberately stays in the user session.
- Not a catalogue/scanner — it opens the file the user points at.
- Because it is user-session-only and one-shot, it is **testable end to end without root**: backends run
  against injected runners + a fake `$HOME`/config, and the one interaction that mattered before (does the UI
  actually do the thing) is a single **Apply** button whose effect is a settings write you can read back.

## E. Suggested next step
Stand up the shell (window + sidebar + Wallpaper page with Open/Preview/Apply) against **one** backend
(whatever this machine runs — Cinnamon here), prove Apply changes the real desktop background and the preview
matches, then add backends and the Screens page. Small enough to build and *verify by using it* in one sitting
— which is the correction this project needed.
