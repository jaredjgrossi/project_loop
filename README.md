# Loop

Turn a plain-English run request into a real NYC route, scored with NYC data. The full plan is in [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md).

**Where things stand (Phase 1, data foundation):** one command sets up a local stack, and one script turns an NYC street address and a distance into a running loop you can look at on a map. There is no scoring, Claude, or frontend yet.

```bash
uv run python -m api.scripts.make_loop "11 Madison Ave, Manhattan" 4
```

```
Start:     11 MADISON AVENUE, New York, NY, USA  [40.74152, -73.98649]
Requested: 4.00 mi
Actual:    3.03 mi  (-24%)
           That is outside the +/-5% target. ...
Saved:     out/loop-11-madison-ave-manhattan-4mi-seed0.geojson
View it:   drag that file onto https://geojson.io
```

The distance miss is real: GraphHopper's round trips are approximate. See [decision 007](docs/decisions/007-round-trip-distance-needs-a-retry-loop.md).

---

## Setup (Mac, new to Docker)

### What you are installing, in plain terms
- **Docker** runs programs in sealed boxes called *containers*, so you don't install Postgres or Java on your Mac. **Docker Desktop** is the app that runs them. A *volume* is a folder Docker keeps so a container's data survives restarts. **Docker Compose** starts several containers together from one file, [`docker-compose.yml`](docker-compose.yml).
- This project runs two containers: **Postgres + PostGIS** (the database) and **GraphHopper** (the route engine).
- **uv** manages Python and its packages. **osmium** cuts the big map file down to NYC.

### 1. Install the tools
You need [Homebrew](https://brew.sh). Then:

```bash
brew install --cask docker
```

```bash
brew install uv osmium-tool
```

Open Docker Desktop once (Applications, or `open -a Docker`). Accept the license and enter your password if asked. Wait until the whale icon in the menu bar stops animating.

In Docker Desktop, go to **Settings → Resources** and give it at least **4 GB** of memory.

Check that it works:

```bash
docker run --rm hello-world
```

You should see "Hello from Docker!".

### 2. Get the code

```bash
git clone https://github.com/jaredjgrossi/project_loop.git
```

```bash
cd project_loop
```

### 3. Run the one-time setup

```bash
make setup
```

This takes a few minutes and downloads about 600 MB (the New York State map, then NYC's parks, fountains and restrooms). It:
1. installs Python 3.12 and the packages (`uv sync`),
2. downloads the state map from Geofabrik and cuts it to the five boroughs (`routing/data/nyc.osm.pbf`),
3. builds and starts the database and GraphHopper, waiting until both are healthy,
4. loads the NYC datasets into the database.

When it finishes you will see row counts for `parks`, `drinking_fountains` and `public_restrooms`, and a warning that the fountain dataset is old. That warning is expected (see [decision 004](docs/decisions/004-amenity-data-trust.md)).

### 4. Make a loop

```bash
uv run python -m api.scripts.make_loop "11 Madison Ave, Manhattan" 4
```

Use a street address **with a number**; include the borough when the same address exists in more than one (the script tells you if it does). Then drag the saved `.geojson` file onto <https://geojson.io> to see it. Try `--seed 1`, `--seed 2`, ... for different loops.

Your own address works the same way. Output goes to `out/`, which is not tracked by git.

---

## Day to day

| Task | Command |
|---|---|
| Start the services | `make up` |
| Stop them (data is kept) | `make down` |
| Are they running? | `docker compose ps` |
| See GraphHopper's log | `docker compose logs -f graphhopper` |
| Reload the NYC datasets from the web | `make data` |
| Run the tests | `make test` |

To open a database prompt: `docker compose exec db psql -U loop -d loop`.

## Troubleshooting

- **"Cannot connect to the Docker daemon"**: Docker Desktop isn't running. Open it and wait for the whale to settle.
- **GraphHopper stays "unhealthy" or restarts**: give Docker Desktop more memory (Settings → Resources), then `docker compose up -d`. Check `docker compose logs graphhopper`.
- **"Could not reach GraphHopper"** from `make_loop`: run `make up`.
- **"port is already allocated"**: something else uses 5432 or 8989. Stop it, or change the left-hand port numbers in `docker-compose.yml`.
- **After changing the map or GraphHopper config**, delete `routing/graph-cache/foot-v2` (or bump the suffix in `routing/config.yml`) so GraphHopper rebuilds its graph. To rebuild the map itself: `uv run python -m routing.prepare_osm --refresh`.
- **Start over completely**: `docker compose down -v` also deletes the database volume; `make setup` rebuilds it.

## Tests

```bash
uv run pytest
```

Covers the geocoding wrapper (against recorded real responses), distance conversion, ETL row parsing (against real rows), the GraphHopper client and `make_loop`. Infrastructure (Docker, the live services) is checked by running `make setup`, not by pytest.

## What's here

```
api/       geocoding, GraphHopper client, scripts/make_loop
etl/       download + parse + load NYC Open Data into PostGIS
routing/   GraphHopper Dockerfile, config, custom foot model, map-extract script
docs/      project plan and decisions/ (why each choice was made)
```

Data: NYC Parks Properties (`enfh-gkve`), Parks Drinking Fountains (`qnv7-p7a2`), Public Restrooms (`i7jb-7jku`) from NYC Open Data; map data © OpenStreetMap contributors via Geofabrik; addresses from NYC Planning Labs GeoSearch. Every loaded row keeps its source dataset ID, source row ID and load time.
