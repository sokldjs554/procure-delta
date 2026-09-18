.PHONY: lint test up down

ifeq ($(OS),Windows_NT)
PYTHON ?= .venv/Scripts/python.exe
NPM ?= npm.cmd
else
PYTHON ?= .venv/bin/python
NPM ?= npm
endif

lint:
	$(PYTHON) -m ruff check apps/api
	$(PYTHON) -m mypy apps/api/app
	$(NPM) --prefix apps/web run lint
	$(NPM) --prefix apps/web run typecheck

test:
	$(PYTHON) -m pytest apps/api/tests
	$(NPM) --prefix apps/web test

up:
	docker compose up --build

down:
	docker compose down

.PHONY: test-contract source-smoke source-smoke-live

test-contract:
	cd apps/api && $(abspath $(PYTHON)) -m unittest discover -s contract_tests -v

source-smoke:
	docker compose run --rm --no-deps api python -m app.sources.koneps_smoke --fixture

source-smoke-live:
	docker compose run --rm --no-deps api python -m app.sources.koneps_smoke --live --max-pages 2
