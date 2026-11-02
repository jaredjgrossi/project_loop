# Shortcuts. Run `make help` to list them.
.PHONY: help setup up down data corridors crowds test

help:
	@echo "make setup   first-time setup: Python deps, NYC map, services, data and street load (a few minutes, ~600 MB download)"
	@echo "make up      start Postgres + GraphHopper"
	@echo "make down    stop them (data is kept)"
	@echo "make data    reload parks, fountains, restrooms into Postgres"
	@echo "make corridors rebuild the corridor catalog from OSM (needs GraphHopper running)"
	@echo "make crowds  precompute crowd levels per sidewalk (needs the downloads in data/crowds/raw, decision 016)"
	@echo "make test    run the unit tests"

setup:
	uv sync
	uv run python -m routing.prepare_osm
	docker compose up -d --build --wait
	uv run python -m etl.load_all
	uv run python -m etl.load_osm
	uv run python -m etl.build_corridors

up:
	docker compose up -d --wait

down:
	docker compose stop

data:
	uv run python -m etl.load_all --refresh

corridors:
	uv run python -m etl.build_corridors

crowds:
	uv run python -m etl.load_crowds

test:
	uv run pytest
