.PHONY: setup test test-ui screenshots lint format web demo-db serve experiments report clean help

help: ## List targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

setup: ## Install Python (uv) and console (npm) dependencies
	uv sync --locked
	npm --prefix web ci

test: ## Unit and API tests
	uv run pytest

test-ui: web ## Browser and accessibility tests against the committed results (needs Chromium)
	uv run pytest -m ui

screenshots: web ## Re-capture docs/screenshots from the running console
	AGENTAUDIT_SCREENSHOTS=1 uv run pytest -m ui

lint: ## Ruff, mypy, ESLint and TypeScript checks
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy src tests
	npm --prefix web run lint
	npm --prefix web run typecheck

format: ## Auto-format Python
	uv run ruff format .
	uv run ruff check --fix .

web: ## Build the console into web/dist
	npm --prefix web run build

demo-db: ## Record the demo deployment the console serves (var/audit.db, signing key, witness)
	set -a; [ -f .env ] && . ./.env; set +a; uv run agentaudit demo-db

serve: web ## Serve API + console on http://127.0.0.1:8000 (reads .env if present; builds the demo database if missing)
	set -a; [ -f .env ] && . ./.env; set +a; [ -f "$${AGENTAUDIT_DB:-var/audit.db}" ] || uv run agentaudit demo-db; uv run agentaudit serve

experiments: ## Re-run E1-E5 and regenerate the report (runtimes are in each run's provenance)
	./scripts/reproduce.sh

report: ## Regenerate research/generated and figures from the latest runs
	uv run agentaudit report

clean: ## Remove build output, caches and the local audit database
	rm -rf web/dist var .pytest_cache .mypy_cache .ruff_cache
