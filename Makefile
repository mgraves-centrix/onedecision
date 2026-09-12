VENV := .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

# Local PostgreSQL from docker-compose.yml. Override to point elsewhere.
# Set ONEDECISION_PG_PORT when 5432 is already taken on this machine: it moves the
# published port and follows through into both connection strings.
export ONEDECISION_PG_PORT ?= 5432
DATABASE_URL      ?= postgresql://onedecision:localdev@127.0.0.1:$(ONEDECISION_PG_PORT)/onedecision
TEST_DATABASE_URL ?= postgresql://onedecision:localdev@127.0.0.1:$(ONEDECISION_PG_PORT)/onedecision_test

.DEFAULT_GOAL := help

.PHONY: help setup seed run test test-pg eval demo smoke clean db-up db-down db-shell migrate

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

setup: ## One-command local setup (venv + pinned dependencies)
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev,postgres]"
	@echo ""
	@echo "Setup complete. Next: make seed && make run"

seed: ## Reset the demo: rebuild SQLite from the synthetic fixtures
	$(PY) -m app.seed --reset

run: ## Start the local web app on http://127.0.0.1:8000
	$(VENV)/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

test: ## Run the test suite (no network, no model calls). SQLite, plus Postgres if it is up.
	$(PY) -m pytest

test-pg: ## Run the whole suite against BOTH SQLite and a local PostgreSQL
	ONEDECISION_TEST_DATABASE_URL=$(TEST_DATABASE_URL) $(PY) -m pytest

smoke: ## Minimal Strands agent smoke test (prints real tool calls)
	$(PY) scripts/smoke_strands.py

demo: ## Run the full scripted golden-path demo end to end in the terminal
	$(PY) scripts/run_demo.py

eval: ## Run the evaluation harness and write docs/evaluation-results.md
	$(PY) -m app.evaluation --write-report

db-up: ## Start a local PostgreSQL (docker compose) and apply migrations
	docker compose up -d --wait db
	ONEDECISION_DATABASE_URL=$(DATABASE_URL) $(PY) -m app.seed --reset

db-down: ## Stop the local PostgreSQL (keeps the volume)
	docker compose down

db-shell: ## psql into the local PostgreSQL
	docker compose exec db psql -U onedecision -d onedecision

migrate: ## Apply any unapplied migrations to the configured database
	$(PY) -c "from app import db; print('applied:', db.init_db() or 'nothing new'); print(db.describe())"

clean: ## Remove local state and caches
	rm -rf var .pytest_cache **/__pycache__ app/__pycache__ tests/__pycache__
