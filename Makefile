VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

.DEFAULT_GOAL := help

.PHONY: help setup seed run test eval demo smoke clean

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

setup: ## One-command local setup (venv + pinned dependencies)
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"
	@echo ""
	@echo "Setup complete. Next: make seed && make run"

seed: ## Reset the demo: rebuild SQLite from the synthetic fixtures
	$(PY) -m app.seed --reset

run: ## Start the local web app on http://127.0.0.1:8000
	$(VENV)/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

test: ## Run the offline test suite (no network, no model calls)
	$(PY) -m pytest

smoke: ## Minimal Strands agent smoke test (prints real tool calls)
	$(PY) scripts/smoke_strands.py

demo: ## Run the full scripted golden-path demo end to end in the terminal
	$(PY) scripts/run_demo.py

eval: ## Run the evaluation harness and write docs/evaluation-results.md
	$(PY) -m app.evaluation --write-report

clean: ## Remove local state and caches
	rm -rf var .pytest_cache **/__pycache__ app/__pycache__ tests/__pycache__
