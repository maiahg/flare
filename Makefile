UV ?= uv run
COMPOSE ?= podman compose

.DEFAULT_GLOBAL := help

.PHONY: help up down run lint fmt typecheck

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-12s\033[0m %s\n", $$1, $$2}'

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

run:
	$(UV) python main.py
lint:
	$(UV) ruff check .

fmt:
	$(UV) ruff format .
	$(UV) ruff check --fix .

typecheck:
	$(UV) mypy .

worker:
	$(UV) arq flare.worker.settings.WorkerSettings