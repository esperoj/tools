# --- Configuration ---
VENV     ?= .venv
BIN      := $(VENV)/bin
PYTHON   := $(BIN)/python3
PIP      := $(BIN)/pip
SRC      := wayback_machine

.PHONY: setup lock lint test release clean clean-all

# --- 1. Environment Setup ---

setup: $(VENV)/.setup_done

$(VENV)/.setup_done: pyproject.toml
	@echo "--- Syncing virtual environment ---"
	@test -d $(VENV) || python3 -m venv $(VENV)
	@$(PIP) install -e ".[dev]"
	@touch $(VENV)/.setup_done

lock: setup
	@echo "--- Pinning current environment to requirements.txt ---"
	@$(PIP) freeze > requirements.txt

# --- 2. Code Quality & Testing ---

lint: setup
	@echo "--- Running Pyright & Ruff ---"
	@$(BIN)/pyright
	@$(BIN)/ruff check $(SRC) --fix
	@$(BIN)/ruff format $(SRC)

test: setup
	@echo "--- Running Pytest ---"
	@$(BIN)/pytest --cov-report term-missing --cov=$(SRC)

# --- 3. Distribution & Versioning ---

release: setup
	@echo "--- Tagging Release ---"
	@VERSION=$$($(PYTHON) scripts/get_version.py); \
	git tag -a "v$${VERSION}" -m "Release $${VERSION}"; \
	git push origin "v$${VERSION}"

# --- 4. Cleanup ---

clean:
	@rm -rf .ruff_cache .pytest_cache .coverage .pyrightpy

clean-all: clean
	@rm -rf $(VENV)
