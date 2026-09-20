# `make check` is the single /build-test path (milestones M0.7).
PY := .venv/bin/python
XVFB := $(shell command -v xvfb-run 2>/dev/null)

.PHONY: setup check lint types gtk4-lint layers test smoke run clean

setup:
	./run.sh --dev

check: setup
	bash -n run.sh
	.venv/bin/shellcheck run.sh
	.venv/bin/ruff check .
	.venv/bin/mypy
	$(PY) tools/gtk4_lint.py
	.venv/bin/lint-imports
	$(PY) -m pytest -m "not smoke" --cov
	$(MAKE) smoke

# The smoke test needs a display: xvfb-run where installed, otherwise the current session's. With
# neither it fails — a suite that skipped every test must not read as a green build.
# `setup` first: the app must render the CSS and schema as they are now, not as last built.
smoke: setup
	@if [ -z "$(XVFB)" ] && [ -z "$$DISPLAY" ] && [ -z "$$WAYLAND_DISPLAY" ]; then \
		echo "make smoke: no display and no xvfb-run, so the app cannot be launched." >&2; \
		echo "  Install a virtual one with: sudo apt install xvfb" >&2; \
		exit 1; \
	fi
	LWP_SMOKE_REQUIRED=1 $(if $(XVFB),xvfb-run -a) $(PY) -m pytest -m smoke -rs

run:
	./run.sh

clean:
	rm -rf build .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
