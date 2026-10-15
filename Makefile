# delve: standard targets. With RESULTS_DIR set, every check also writes its result as
# <aspect>.<language>.<format> and its exit code, for test-everything results import.
.DEFAULT_GOAL := help
PY      := .venv/bin/python
NICE    := nice -n 19
RESULTS_DIR ?=
record = $(if $(RESULTS_DIR),mkdir -p $(RESULTS_DIR); rc=0; $(2) || rc=$$?; echo $$rc > $(RESULTS_DIR)/$(1).exit; exit $$rc,$(2))

.PHONY: help venv dev lint fmt type test check examples clean

help:  ## Show the targets.
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

venv:  ## Create .venv (virtualenv, no system packages needed).
	@test -x $(PY) || python3 -m virtualenv -q .venv || python3 -m venv .venv

dev: venv  ## Install delve editable with both providers and the dev tools.
	@.venv/bin/pip install -q -e ".[dev]"

lint:  ## ruff check and format check.
	@$(call record,lint.python,$(NICE) timeout 300 .venv/bin/ruff check src tests $(if $(RESULTS_DIR),--output-format sarif -o $(RESULTS_DIR)/lint.python.sarif))
	@$(call record,format.python,$(NICE) timeout 300 .venv/bin/ruff format --check src tests)

fmt:  ## Format the code.
	@.venv/bin/ruff format src tests && .venv/bin/ruff check --fix src tests

type:  ## pyright.
	@$(call record,types.python,$(NICE) timeout 600 .venv/bin/pyright $(if $(RESULTS_DIR),--outputjson > $(RESULTS_DIR)/types.python.json))

test:  ## pytest (no cloud account needed: providers are stand-ins).
	@$(call record,test.python,$(NICE) timeout 900 .venv/bin/pytest -q $(if $(RESULTS_DIR),--junitxml=$(RESULTS_DIR)/test.python.junit.xml))

examples:  ## Validate every example spec.
	@for f in examples/*.yaml; do .venv/bin/delve validate $$f || exit 1; done

check: lint type test examples  ## Everything CI runs.

clean:  ## Remove caches and build output.
	@rm -rf .pytest_cache .ruff_cache build dist src/*.egg-info
