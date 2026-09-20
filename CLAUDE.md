# Project: Lin Wallpapers — CLAUDE.md (v2026.04 — Claude Code Native)

## Overview
GTK wallpaper manager for every screen: finds, catalogues, previews and applies one image to the desktop,
lock screen, login screen, boot splash and boot menu — transactionally, with undo, and with **no daemon**.
Specs: `TECHNICAL-CONCEPT.md` (architecture), `docs/milestones.md` (delivery plan, M0–M8),
`reference/` (the base script the apply engine reproduces).

## Architecture
- Language/Framework: Python 3.11+ · GTK 3 via PyGObject, written to port to GTK 4 · Cairo · Pillow · SQLite
- Build system: `run.sh` (venv with system site packages + GResource + GSettings schema) · `make` · setuptools
- Key dependencies (from the distribution, never PyPI): `python3-gi gir1.2-gtk-3.0 gir1.2-gdkpixbuf-2.0
  python3-gi-cairo python3-pil`; dev tools from `requirements-dev.txt`
- Layers: `ui`/`pages` (GTK only) → `viewmodels` → services (`scanner`, `catalogue`, `imaging`, `preview`,
  `apply`, `helper`, `cli` — **no `gi`**) → `apply/providers` → system

## Build & Runtime Standards (Enforced)
```
# Build (venv, resource bundle, settings schema, dev tools)
./run.sh --dev

# Test
.venv/bin/python -m pytest -m "not smoke" --cov     # unit
make smoke                                          # launches the real app (xvfb-run if installed)

# Lint
.venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/python tools/gtk4_lint.py && .venv/bin/lint-imports

# Full pipeline (/build-test)
make check

# Run
./run.sh            # GUI
.venv/bin/linwp     # CLI
```
- Use /plan-first for complex features or multi-file changes
- Use /build-test (`make check`) before every commit: shellcheck → ruff → mypy → gtk4_lint → import-linter → pytest → smoke
- mypy is strict on `src/apply`, `src/catalogue`, `src/imaging`, `src/helper`
- Performance budgets: TECHNICAL-CONCEPT §20

## Project Conventions
- **Nothing runs in the background.** No daemon, no unit, no login hook. The helper (M5) is one-shot via `pkexec`.
- **Providers, not conditionals.** No branch on a distribution/release/desktop name outside a provider's `detect()`.
- **Layering is mechanical.** `import-linter` contracts in `pyproject.toml`; widgets never touch the filesystem.
- **GTK 4 readiness.** GTK is imported only from `src/gtk_version.py`; GTK 3-only calls live only in
  `src/ui/compat.py`; `tools/gtk4_lint.py` enforces both.
- **Tokens only.** Every color is a `@define-color` in `resources/css/tokens.css`; no hex anywhere else
  (tests enforce it). Cairo code resolves tokens with `compat.lookup_color()`.
- **Never hide a feature**; unsupported → greyed out with a reason code and evidence (§15.1–15.3).
- **Never edit a package conffile**; drop-ins only. Plan → precheck → backup → write → verify → commit | rollback.
- **No fake data in `src/`**; empty pages name the milestone that fills them.
- Tests never touch the real system: providers run against `tests/fakeroot/`.
- Starter-template conventions kept: `BasePage.build_content()`, `register_page("<route>", page)`,
  `NAV_ITEMS` tuples, 150 px sidebar, `src/modules/` managers.

## Sector-Specific Rules
<!-- Path-scoped rules load automatically when editing matching files -->
@.claude/rules/ for all active rules

## Memory & Workflow
- Use official Auto Memory (/memory) for Claude's own learnings across sessions
- Human-readable history supplements Auto Memory:
  - Session logs: `.claude/memory/sessions/`
  - Change manifests: `.claude/memory/changes/`
  - Decision log: `.claude/memory/decisions.md`
  - Pending items: `.claude/memory/pending.md`
  - Memory index: `.claude/memory/MEMORY.md`
- End every significant session with /session-end or the session-end checklist
- Update changelog.md as changes are made, not after

## Hooks (Automated)
Lifecycle hooks are configured in `.claude/settings.json` (deployed by `universal-agents/setup.sh`; they need `jq`):
- **SessionStart**: Injects pending items, last session log, and recent changelog
- **PreToolUse**: Security gate blocks secret file access and destructive commands
- **PostToolUse**: Auto-lint/format after file edits (Python section: `ruff`)

## Custom Commands
- `/plan-first` — Plan complex tasks before executing
- `/build-test` — Run full build + test pipeline from CLAUDE.md
- `/session-end` — End-of-session wrap-up and logging

## References
- @docs/ for project documentation
- @.claude/rules/ for path-scoped rules
- @.claude/memory/decisions.md for architectural decision history
