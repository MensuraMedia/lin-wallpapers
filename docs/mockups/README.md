# UI mockups (concept stage)

Five 1280 × 800 desktop screens plus the shared sidebar component, in the Lin Wallpapers design language
(TECHNICAL-CONCEPT §14 layout, §16 colors: `ui-kit-yellow-gray-yello.jpg` — #1E2233 / #252A3E / #2B3044
surfaces, one yellow accent #FFC700). Values are illustrative but taken from the reference machine
(Mint 22.2, Cinnamon, slick-greeter, Plymouth + GRUB, 1920 × 1080).

| File | Screen | Interactive |
| --- | --- | --- |
| `Main.dc.html` | **Browse**: scan banner, filter chips, virtualized card grid with score rings and badges (native, text-safe, duplicates, offline drive, low-scoring portrait), selection bar | Links to the other artboards |
| `Image.dc.html` | **Image detail**: large preview with the fill crop frame, fit-mode control, score breakdown, metadata, palette, badges, and the five surface tiles showing where the image is already set | Links |
| `Screens.dc.html` | **Screens**: the five surfaces as cards with mini previews, provider names, mechanism, status (applied / follows desktop / needs authorization), plus the sync switch and a "what was detected" panel | Links |
| `Preview.dc.html` | **Preview**: all five screens rendered from the same transform — desktop with panel, lock with clock, greeter with avatar and field, Plymouth splash with spinner, GRUB menu | `wallpaper` tweak: Mountain / Forest / Night switches all five previews |
| `Apply.dc.html` | **Apply**: the plan sheet (11 steps, straight from the base script), the verified result with per-surface outcomes and the backup path, and apply history including a rolled-back attempt | Links |
| `Sidebar.dc.html` | Shared sidebar component (`active` tweak) — logo, routes, "this machine" footer | Yes |

- **Format:** Design Component HTML (`.dc.html`) with an index in `canvas.json`; viewable on the project's
  private design canvas. Visual reference for M0–M5, not production code (the app is GTK + Cairo).
- **Fonts:** Manrope, with inline stroke icons standing in for the planned symbolic set.
- The "photographs" in the mockups are drawn with gradients and SVG silhouettes — placeholders for real images.
