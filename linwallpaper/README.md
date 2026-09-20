# LinWallpaper

A small, self-contained **GTK 4 + libadwaita** desktop-wallpaper app: open an image,
preview exactly how it will fit, and apply it to your desktop background — for all
screens or one. No root, no daemon, one-shot.

- App id: `io.mensuramedia.LinWallpaper`
- Window title: `LinWallpaper`
- Runs on the **system** `python3` (uses the distribution's `gi`, GTK 4, libadwaita,
  GdkPixbuf and Pillow packages — no venv, no PyPI).

## Run

```sh
./linwallpaper/run.sh          # or:  python3 -m linwallpaper.main
```

`run.sh` resolves its own directory, so it works from any cwd or by absolute
path / symlink.

## Install (desktop integration, user-level)

```sh
./linwallpaper/install.sh              # install icon + .desktop into ~/.local/share
./linwallpaper/install.sh --uninstall  # remove it
./linwallpaper/install.sh --exec CMD   # override the launcher command
```

This installs, into `$XDG_DATA_HOME` (or `~/.local/share`):

- `data/io.mensuramedia.LinWallpaper.desktop` — the menu entry (Exec is rewritten
  to this checkout's `run.sh`; `StartupWMClass` matches the app id so the running
  window's icon resolves), validated with `desktop-file-validate`.
- `data/icons/hicolor/scalable/apps/io.mensuramedia.LinWallpaper.svg` and the
  `-symbolic` variant — the screen-with-landscape mark tinted to the libadwaita
  blue accent. PNGs are rasterised too when `rsvg-convert`/`inkscape`/ImageMagick
  is present.

It installs *desktop integration only* — no service, daemon, autostart or login
hook. The window sets its icon name to the app id, so the taskbar/menu icon shows
once installed.

## What it does

- **Wallpaper page** — Open image (`Gtk.FileDialog`, filter built from the installed
  `GdkPixbuf` loaders) or drag-and-drop; a `Gtk.Picture` preview; filename / resolution
  / format chips; a **Fit** segmented control (Fill / Fit / Center / Stretch); an
  **Apply to** toggle (All screens / This screen); the detected backend; **Apply**
  with an `Adw.Toast` "Applied — Undo".
- **Screens page** — a card per `Gdk.Monitor` (connector, WxH, scale, primary badge)
  with a per-monitor **Choose image…**.
- **Preview page** — a larger fitted preview in a mock desktop frame.
- **Settings / About** — default fit, detected desktop + backend (greyed reason if
  unsupported), version/credits.

## How apply works (providers, not conditionals)

`backends/` holds one file per environment implementing a common protocol
(`detect() → confidence`, `current()`, `apply()`, `restore()`). The registry picks the
highest-confidence backend by **evidence** (`$XDG_CURRENT_DESKTOP`, the tools on
`PATH`, the presence of a gsettings schema) — never by branching on a distro name.

| Backend | Mechanism | Per-monitor |
| --- | --- | --- |
| Cinnamon | `gsettings org.cinnamon.desktop.background` | via composite |
| GNOME | `org.gnome.desktop.background` (+ dark) | via composite |
| MATE | `org.mate.background` (bare path) | via composite |
| Xfce | `xfconf-query` per-monitor `last-image` | native |
| X11 (feh) | `feh --bg-*` | native (fallback) |

**Fit → picture-options:** Fill→`zoom`, Fit→`scaled`, Center→`centered`,
Stretch→`stretched`.

**One screen on a single-background desktop:** composite (Pillow) a canvas spanning
the whole monitor layout — the chosen image fitted into the target monitor's rect, the
rest kept — save to `~/.cache/linwallpaper/composite-*.png`, set with
`picture-options = spanned`. The **same `imaging.transform()`** feeds both the preview
and the composite, so preview == result.

## Layout

```
linwallpaper/
  main.py            Adw.Application + CSS load
  monitors.py        Gdk.Monitor -> frozen MonitorInfo DTOs (the only gi outside ui/)
  imaging.py         validate + load + transform(path,size,fit) + GdkPixbuf format list
  backends/          base.py (protocol+registry) cinnamon gnome mate xfce x11_feh
  ui/
    window.py sidebar.py state.py imgutil.py style.css
    pages/  wallpaper.py screens.py preview.py settings.py
  data/
    io.mensuramedia.LinWallpaper.desktop
    icons/hicolor/{scalable,symbolic}/apps/io.mensuramedia.LinWallpaper*.svg
  tests/  test_core.py
  install.sh  run.sh  README.md
```

**Robustness:** every image entering the app (Open dialog, per-screen chooser,
drag-and-drop) goes through `AppWindow.load_image`, which calls
`imaging.validate()` first — a missing, corrupt or non-image file shows an inline
error toast and never crashes. The Open dialog filter is built from both the
pixbuf loader mime types **and** their extensions. Both previews use
`ContentFit.CONTAIN` so the baked-in fit (letterbox / centre padding) shows whole
and each Fit/Center/Fill/Stretch render is visibly distinct.

## Tests

```sh
python3 -m pytest linwallpaper -q      # pure parts, no display
```
