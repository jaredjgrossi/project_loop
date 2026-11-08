# Shortcuts. Run `make help` to list them.
.PHONY: help setup up down data corridors closures crowds pulses places test eval-parse

help:
	@echo "make setup   first-time setup: Python deps, NYC map, services, data and street load (a few minutes, ~600 MB download)"
	@echo "make up      start Postgres + GraphHopper"
	@echo "make down    stop them (data is kept)"
	@echo "make data    reload parks, fountains, restrooms into Postgres"
	@echo "make corridors rebuild the corridor catalog from OSM, then its closures (needs GraphHopper running)"
	@echo "make closures reload the closures (corridor gaps and routing/curated_closures.geojson, decision 017)"
	@echo "make crowds  precompute crowd levels per sidewalk (needs the downloads in data/crowds/raw, decision 016)"
	@echo "make pulses  load school and ferry pulse sources (needs the downloads in data/pulses/raw, decision 022)"
	@echo "make places  build the places table for name lookups (needs make setup; decision 026)"
	@echo "make test    run the unit tests"
	@echo "make eval-parse run the parse evals and print a pass/fail table (PARSER=module:function, default the stub)"

setup:
	uv sync
	uv run python -m routing.prepare_osm
	docker compose up -d --build --wait
	uv run python -m etl.load_all
	uv run python -m etl.load_osm
	uv run python -m etl.build_corridors
	uv run python -m etl.build_closures
	uv run python -m etl.load_places

up:
	docker compose up -d --wait

down:
	docker compose stop

data:
	uv run python -m etl.load_all --refresh

corridors:
	uv run python -m etl.build_corridors
	uv run python -m etl.build_closures

closures:
	uv run python -m etl.build_closures

crowds:
	uv run python -m etl.load_crowds

pulses:
	uv run python -m etl.load_pulses

places:
	uv run python -m etl.load_places

test:
	uv run pytest

PARSER ?= evals.parse.stub:parse
MODEL ?=
EFFORT ?=
THINKING ?=
eval-parse:
	uv run python -m evals.parse.run --parser $(PARSER) $(if $(MODEL),--model $(MODEL)) $(if $(EFFORT),--effort $(EFFORT)) $(if $(THINKING),--thinking $(THINKING))
