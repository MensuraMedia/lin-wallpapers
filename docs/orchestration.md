# Orchestration board

How the agent team delivers work on Lin Wallpapers: progressively, one phase at a time, tested at every
gate. Agent definitions live in `.claude/agents/`; this board is the shared plan and the record of each gate.

## The team

| Agent | Tier | Role in a phase | Writes code? |
| --- | --- | --- | --- |
| **team lead** (the main session) | — | Plans phases, assigns file ownership, runs the gate, rules on open questions, keeps docs and changelog current | integrates only |
| **architect** | Opus | Turns a milestone into a module contract: APIs, ownership, build order, test plan, open questions | design docs only |
| **scout** | Haiku | Fast read-only reconnaissance: where things are, what a tool outputs on this machine | no |
| **implementer** | Sonnet | Builds exactly the files it owns for the phase, with their tests, until `make check` is green | yes — owned files only |
| **code-reviewer** | Sonnet | Quality, security and correctness review of the diff | no |
| **data-checker** | Haiku | Schema, fixtures, golden data and migrations match the contract | no |
| **adversary** | Opus | Tries to break the phase — rules, spec, tests, hostile input, concurrency, performance claims — and reports only what it reproduced | scratch dir only |

Rules of engagement:

1. **Disjoint ownership.** Two agents never edit the same file in the same phase. Shared files
   (`pyproject.toml`, `changelog.md`, `README.md`, `docs/milestones.md`) belong to the team lead.
2. **Contract first.** Implementers build against `docs/design/<milestone>-architecture.md`; a change to the
   contract goes through the team lead, not around it.
3. **The adversary collaborates.** Its report is a worklist for the implementer, with repro commands. The
   implementer fixes; the adversary re-checks only its own findings.
4. **Nobody weakens a gate.** No test, lint rule, type check or import contract is relaxed to get to green.
   If a rule is wrong, the team lead changes it explicitly and records why.
5. **Every phase leaves the tree shippable**: `make check` green, docs and changelog updated.

## The phase gate

A phase is closed only when all of these hold:

- [ ] `make check` passes (shellcheck → ruff → mypy → gtk4_lint → import-linter → pytest → smoke)
- [ ] New behaviour has tests that fail when the behaviour is broken (the adversary spot-checks by mutation)
- [ ] Adversary verdict is **PASS** or **PASS WITH FIXES** with every S1/S2 finding fixed and re-checked
- [ ] Standing rules hold: nothing left running, no network, nothing written outside `$HOME`/XDG, no `gi` in
      services, tokens only, no fake data in `src/`
- [ ] `changelog.md` row added; milestone checkboxes ticked; deviations recorded

## Plan

| Phase | Scope | Agents | Owned files | Gate |
| --- | --- | --- | --- | --- |
| **P0** | Docs: exclusions (§5.1), display detection (§5.2), ideal-images segment (§6.1), schema, M1 tasks, README, CLI stubs | team lead | docs, `src/cli/linwp.py` | ✅ closed — `make check` green (36 unit + 6 smoke) |
| **P1** | Shell ↔ mockup alignment; Ubuntu font family throughout | implementer → adversary | `src/ui/**`, `src/pages/page_base.py`, `resources/css/**`, `src/config/config_{theme,layout}.py`, `tests/smoke/**` | ✅ closed — full gate green (1030 unit + 19 smoke) |
| **P2** | M1 architecture contract | architect → adversary (paper review) | `docs/design/m1-architecture.md` | ✅ closed — contract + rulings; scaffold green |
| **P3** | M1.1a exclusions engine · M1.1b display detection (parallel) | 2 × implementer → adversary | `src/scanner/exclude.py` + tests · `src/scanner/displays.py` + tests + DRM fixtures in `tests/fakeroot/` | ✅ closed — adversary PASS WITH FIXES (0 S1/S2); 2 S3 test gaps → P4.1 |
| **P4** | M1.4 catalogue (db, schema, migrations, queries) · M1.5a ideal segment | implementer + data-checker → adversary | `src/catalogue/**` + tests | ✅ closed — adversary PASS WITH FIXES (Python≡SQL over 108k cases, rebuild 53 ms, no I/O); 2 S3 gaps → P4.1 |
| **P4.1** | Close the 4 adversary S3 mutation gaps (every-display `EXISTS` guard; multi-segment literal case-sensitivity; `run_migrations` too-new guard; `recover` fast-path) | implementer → adversary re-check | `tests/unit/test_queries.py`, `test_exclude_glob.py`, `test_catalogue_migrations.py` | ✅ closed — 3 regression tests (recover fast-path skipped as optional) |
| **P5a** | M1.1 roots (fix R1–R4 + tests) · M1.2 walk · M1.3 probe · M1.5 thumbnails — 3 parallel lanes | impl-E ∥ impl-F ∥ impl-G → code-reviewer → adversary | E: `src/scanner/roots.py` + `tests/unit/test_roots.py` · F: `src/scanner/{walker,probe}.py` + tests · G: `src/catalogue/thumbs.py` + `test_thumbs.py` | ✅ closed — adversary PASS (1 S1 found & fixed: `probe_file` never-raises on foreign magic bytes; 2 S3 gaps closed) |
| **P5b** | Ingest (writer thread + `ScanService`) · CLI wiring (`scan/list/show/exclude/displays`) | impl-H → code-reviewer → adversary | `src/catalogue/ingest.py`, `src/cli/{context,cmd_scan,cmd_list,cmd_show,cmd_exclude,cmd_displays}.py`, `src/cli/linwp.py`, `tests/unit/test_ingest.py` + update `test_cli.py` | open — serialize after P5a |
| **P6** | View models (I: DTOs first) · Sources + Browse pages & components (J) | impl-I → impl-J → adversary | I: `src/viewmodels/**` + VM tests · J: `src/pages/page_{sources,browse}.py`, `src/ui/components/**`, `src/pages/__init__.py`, `src/ui/content_area.py`, app entry + smoke | open — J follows I's DTOs |
| **P7** | M1.8 performance, 10k fixture generator, nasty-file corpus, cancellation and kill -9 tests, `docs/perf.md`, M1 acceptance run | implementer + adversary | `tests/**`, `docs/perf.md` | open |

## Gate log

| Date | Phase | `make check` | Adversary | Notes |
| --- | --- | --- | --- | --- |
| 2026-09-18 | P0 | green | n/a (docs) | Spec for exclusions, display detection and the ideal segment written; `linwp` stubs added |
| 2026-09-18 | P1 | green mid-phase (301 unit + 18 smoke); final run pending P4's in-progress file | PASS WITH FIXES → 1 × S2 (Ctrl+Q lost state) and 5 × S3 fixed; 13/13 mutations now caught (was 2/12) | Logo block centred at the user's request; dim-text token kept at the spec value |
| 2026-09-18 | P2 | green (141 unit) | paper review folded into rulings Q1–Q10a, T1 | Seven deferrals accepted for the first M1 slice |
| 2026-09-18 | P1 (final) | green — 1030 unit, 19 smoke, mypy 59 files, 5 contracts kept | closed | — |
| 2026-09-18 | P3 + P4 (build) | green (same run) | in progress | exclude.py 512 tests / 100 % branch; displays.py 122 tests / 100 % branch; catalogue 214 tests / 98 %; ideal rebuild 20k × 2 displays in 54 ms, no file I/O; rulings Q2a, P3-1, P4-1…3 recorded |
| 2026-09-19 | Gate fix | green | n/a | ruff E501 in `scanner/roots.py` line-wrapped; full `make check` re-verified green (shellcheck → ruff → mypy → gtk4_lint → import-linter → 1030 unit → 19 smoke) |
| 2026-09-19 | P3 + P4 (review) | green (1030 unit + 19 smoke) | **PASS WITH FIXES** — 0 S1/S2; 18/22 mutations caught; 4 S3 test gaps → P4.1 | Python≡SQL 0 mismatches / 108k cases; rebuild 20k×2 = 53 ms; fetch_page 6–16 ms; locked-DB `CatalogueBusyError` at ~5 s and `kill -9` → `interrupted` recovery reproduced. **P3 and P4 closed.** |
| 2026-09-19 | P5 planning | — | code-reviewer + architect | roots.py review: NEEDS WORK (0 tests = blocker; bug R1 `/run/media` segment count). Architect P5–P7 plan accepted; rulings Q11–Q17 + R1–R4 recorded in the M1 contract; board expanded to P4.1 / P5a (3 lanes) / P5b / P6 (I→J). |
| 2026-09-19 | P4.1 | green | closed (test-only) | 3 regression tests close the every-display `EXISTS` guard, multi-segment literal case-sensitivity, and the `run_migrations` too-new guard; `recover` fast-path skipped as optional. |
| 2026-09-19 | P5a (build) | green (1236 unit + 19 smoke) | in progress | 4 parallel lanes, disjoint ownership: roots (fix R1–R4, `test_roots.py` 83/100 %) · walker+probe (77, `TOO_LARGE`/64 KiB/draft-decode; fixed a sentinel-drop-on-cancel bug) · thumbs (42/100 %). |
| 2026-09-19 | P5a (review) | green (1244 unit + 19 smoke) | **PASS** — 1 S1 found (`probe_file` raised on foreign magic bytes under an allowed extension) fixed and regression-caught (6500-case fuzz clean); 2 S3 gaps closed; 20/22 mutations caught, no new S1/S2. **P5a closed.** |
