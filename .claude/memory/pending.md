# Pending

> **2026-09-20 (evening): the user assessed the project as FAILED ("not effective. this project has
> failed.").** See `docs/STATUS.md` → "Current assessment". Do not resume feature work as if the gate
> being green means the app works — it repeatedly did not. What follows is the honest open list.

## Broken / unresolved (user-facing)
- **Exclusions don't show in Sources → Exclusions.** Excluding from Browse removes the card but the rule
  never appears in the Sources panel. Root cause: `SourcesVM` never subscribed to the `ChangeFeed`. A fix
  was attempted (subscribe + refresh); **user reports it is still not effective** — re-verify live, not by
  tests.
- **Add to Collection / Preview** context-menu items do nothing (Collections = M6, Preview = M3, unbuilt);
  they were also styled to look enabled (styling fix in flight).

## The fundamental gap
- The app **cannot set a wallpaper** — the entire apply path (preview M3, apply M4, privileged helper M5)
  is unbuilt. Everything shipped so far is scan + catalogue + browse + exclude. The product does not yet do
  the one thing it exists to do.

## Process failure to fix before continuing
- Features were called "done" on green unit/smoke tests that bypassed the real user interaction (the
  right-click was broken for days while tests passed; exclusions-in-Sources passed tests but failed live).
  Any future work must verify user-facing behaviour by real input driving (`Gtk.main_do_event`) or a human
  in the loop — the gate is necessary but NOT sufficient.

## If work resumes (smallest → largest)
- Re-verify/fix the exclusions-in-Sources bug **in the running app**.
- Fix the disabled-menu-item styling so unbuilt actions read as unavailable.
- P7 to formally close M1 (perf + acceptance).
- Then the real product work: M2 scoring, M3 preview + Screens, M4/M5 apply — that is where a "wallpaper
  manager" actually begins.
