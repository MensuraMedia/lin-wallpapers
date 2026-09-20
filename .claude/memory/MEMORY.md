# Memory index

Human-readable handoff supplementing git history and the changelog. One line per entry.

## Sessions
- [2026-09-20](sessions/2026-09-20.md) — planning round + P4.1/P5a landed (adversary PASS); launch icon, desktop entry and installer added.

## Pending
- [pending.md](pending.md) — next actions (P5b is next).

## Standing constraints worth re-reading
- No daemon, no background process, **no system tray**, no autostart, no login hook (CLAUDE.md rule 1). This shapes what is even buildable — e.g. per-virtual-desktop wallpaper (see `docs/design/virtual-desktop-wallpapers.md`) is only feasible where the desktop environment itself persists the mapping.
