# Setting up Loop (Mac, new to Docker)

The README has what Loop is; this is how to run it.

## What you are installing, in plain terms
- **Docker** runs programs in sealed boxes called *containers*, so you don't install Postgres or Java on your Mac. **Docker Desktop** is the app that runs them. A *volume* is a folder Docker keeps so a container's data survives restarts. **Docker Compose** starts several containers together from one file, [`docker-compose.yml`](../docker-compose.yml).
- This project runs two containers: **Postgres + PostGIS** (the database) and **GraphHopper** (the route engine).
- **uv** manages Python and its packages. **osmium** cuts the big map file down to NYC.

## 1. Install the tools
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

## 2. Get the code

```bash
git clone https://github.com/jaredjgrossi/project_loop.git
```

```bash
cd project_loop
```

## 3. Run the one-time setup

```bash
make setup
```

This takes a while and downloads about 600 MB (the New York State map, then NYC's parks, fountains and restrooms). It:
1. installs Python 3.12 and the packages (`uv sync`),
2. downloads the state map from Geofabrik and cuts it to the five boroughs (`routing/data/nyc.osm.pbf`),
3. builds and starts the database and GraphHopper, waiting until both are healthy,
4. loads the NYC datasets and the street network (about 414,000 OSM ways) into the database,
5. builds what the routes and the place lookups read: the corridor catalog and closures, the places table (named
   parks, streets, stations and the curated landmarks), neighborhoods and the curated running loops.

The crowd and school-pulse data need extra downloads: `make crowds` and `make pulses` say what.

When it finishes you will see row counts for `parks`, `drinking_fountains` and `public_restrooms`, and a warning that the fountain dataset is old. That warning is expected (see [decision 004](docs/decisions/004-amenity-data-trust.md)).

## 4. Make a loop

```bash
uv run python -m api.scripts.make_loop "11 Madison Ave, Manhattan" 4
```

Use a street address **with a number**; include the borough when the same address exists in more than one (the script tells you if it does). Then drag the saved `.geojson` file onto <https://geojson.io> to see it. Add `--top 3` for three different loops.

Your own address works the same way. Output goes to `out/`, which is not tracked by git.

---

## Run the API

The API needs a Claude key (to read the sentence) and a token the app presents. Put them in `.env`, which git ignores:

```
ANTHROPIC_API_KEY=...
LOOP_TOKEN=...            # make one with: openssl rand -hex 24
# LOOP_PRIOR_INSTALL_IDS= # see below
```

```bash
make serve
```

It listens on 127.0.0.1:8000. The request and the streamed events are in [`docs/phase3/parse-contract-v1.md`](phase3/parse-contract-v1.md), and how the iPhone app reaches it in [`docs/phase3/ios-wiring.md`](phase3/ios-wiring.md).

`LOOP_PRIOR_INSTALL_IDS` lists the app installs (comma separated) whose own run history may shape their routes. The history in `runner_prior` is one person's Apple Health runs, so no other install gets it ([decision 046](decisions/046-prior-is-the-owners.md)). Unset means nobody.

To find your own id, build one route from the app, then list the newest ids:

```bash
docker compose exec db psql -U loop -d loop -c "SELECT request->>'install_id' AS install, max(created_at) FROM saved_routes GROUP BY 1 ORDER BY 2 DESC LIMIT 5"
```

The iPhone app is in [`ios/`](../ios/README.md).

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
- **After changing the map or GraphHopper config**, delete `routing/graph-cache/foot-v4` (or bump the suffix in `routing/config.yml`) so GraphHopper rebuilds its graph. To rebuild the map itself: `uv run python -m routing.prepare_osm --refresh`.
- **Start over completely**: `docker compose down -v` also deletes the database volume; `make setup` rebuilds it.

## Tests

```bash
uv run pytest api/ etl/      # unit tests: no database or network needed in CI mode
uv run pytest evals/         # live evals: need `make up`, the loaded places and, for parse evals, ANTHROPIC_API_KEY
uv run python -m evals.parse.run --parser api.parse:parse -v   # the parse evals, with a pass/fail table
```

CI runs the unit tests only, with Postgres and the network off ([decision 019](decisions/019-ci-unit-tests.md)). The live evals run on the Mac.
