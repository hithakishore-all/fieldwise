# One command each. Works on macOS and Linux. Windows: see README "Commands without make".
PY ?= python3.12
VENV := .venv
BIN := $(VENV)/bin
-include .env
export

.PHONY: setup seed start test reset check offline

setup:            ## create .venv and install pinned dependencies
	$(PY) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements.lock
	-$(BIN)/python -m playwright install chromium

seed:             ## load demo data into an empty database
	$(BIN)/python -m app.cli seed

start:            ## run on http://127.0.0.1:8000
	$(BIN)/python -m app.cli start

test:             ## run every automated test (uses its own temporary databases)
	$(BIN)/python -m pytest -q

reset:            ## wipe and reload the demo data
	$(BIN)/python -m app.cli reset

check:            ## show which database is configured and whether it answers
	$(BIN)/python -m app.cli check

offline:          ## zero-setup run on a local SQLite file, no PostgreSQL needed
	DATABASE_URL=sqlite:///./fieldwise.db $(BIN)/python -m app.cli reset
	DATABASE_URL=sqlite:///./fieldwise.db $(BIN)/python -m app.cli start
