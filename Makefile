# Motorsport Events — common tasks.
#   make help   for the list.

.DEFAULT_GOAL := help
COMPOSE := docker compose -f docker-compose.forgejo.yml

.PHONY: help install hooks test ingest scheduler serve build-site serve-site \
        forgejo-up forgejo-register forgejo-runner forgejo-logs forgejo-down forgejo-status

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

## --- development ---------------------------------------------------------

install:  ## Create venv and install runtime + dev deps
	python3 -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip && \
	  pip install -r requirements.txt -r requirements-dev.txt

hooks:  ## Install the git pre-push test hook
	./scripts/install-hooks.sh

test:  ## Run the test suite
	. .venv/bin/activate && pytest

ingest:  ## Refresh events from all sources
	. .venv/bin/activate && python -m app.ingest

scheduler:  ## Run the auto-refresh scheduler (foreground)
	. .venv/bin/activate && python -m app.scheduler

serve:  ## Run the web app (http://localhost:8000)
	. .venv/bin/activate && uvicorn app.main:app --reload

build-site:  ## Build the static SPA data (site/events.json)
	. .venv/bin/activate && python -m app.build_site

serve-site:  ## Preview the static SPA (http://localhost:8200)
	cd site && python3 -m http.server 8200

## --- local Forgejo CI ----------------------------------------------------

forgejo-up:  ## Start Forgejo and print next steps
	./scripts/forgejo-up.sh

forgejo-register:  ## Register the runner: make forgejo-register TOKEN=<token>
	@test -n "$(TOKEN)" || { echo "Usage: make forgejo-register TOKEN=<token>"; exit 1; }
	RUNNER_TOKEN="$(TOKEN)" $(COMPOSE) run --rm runner-register

forgejo-runner:  ## Start the runner daemon
	$(COMPOSE) up -d runner

forgejo-status:  ## Show Forgejo/runner container status
	$(COMPOSE) ps

forgejo-logs:  ## Tail Forgejo + runner logs
	$(COMPOSE) logs -f forgejo runner

forgejo-down:  ## Stop Forgejo and the runner
	$(COMPOSE) down
