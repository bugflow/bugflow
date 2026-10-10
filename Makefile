.PHONY: check lint fmt imports types test env up down

# The composition a local run brings up, and the name its .env gives the
# solution, which is the compose project and the prefix of the edge
# network.
DEPLOYMENT ?= example
SOLUTION ?= $(shell sed -n 's/^SOLUTION=//p' deployments/$(DEPLOYMENT)/.env)
COMPOSE = SOLUTION=$(SOLUTION) docker compose \
	-f deployments/$(DEPLOYMENT)/docker-compose.yml

check: lint fmt imports types test ## Everything a change must pass before it is pushed

lint:
	uv run ruff check .

fmt:
	uv run ruff format --check .

imports:
	uv run lint-imports

types:
	uv run mypy

test:
	uv run pytest

env: ## Write .env with generated secrets, and render env/ from it
	@./deployments/scripts/make-env.sh

up: ## Bring a server up from deployments/$(DEPLOYMENT)
	@docker network inspect $(SOLUTION)-edge >/dev/null 2>&1 \
		|| docker network create $(SOLUTION)-edge
	$(COMPOSE) up -d --build

down: ## Stop the server, keeping its database
	$(COMPOSE) --profile polling --profile webhooks down
