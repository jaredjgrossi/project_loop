# 048: GPX for a stored route

**Status:** accepted (2026-11-12). From the full product review (3.2: "nothing leaves the phone"). The app's Share
sheet needs a file.

## Decision
- `GET /v1/routes/{id}/gpx`, with the token, returns the route as GPX 1.1 (`application/gpx+xml`, an attachment named
  `loop-<route id>.gpx`).
  - `{id}` is a route's own id (`r_xxxxxxxx.N`) or a build's id (its first route).
  - Unknown build or route: HTTP 404.
- The file has the line, a `Start` waypoint, a `Mile n` waypoint at each whole mile, and a `Turnaround` waypoint where
  the run turns (the main turnarounds only, decision 044). The route's label is the track's name. That reaches
  WorkOutDoors, Footpath, Garmin Connect and AirDrop.
- It has no `<ele>`: elevation per point isn't stored (only a profile every 0.1 mi), and the watch app or Strava works
  out its own. No invented numbers.
- It works for any stored build, so a saved or run route can be shared later (builds are kept for good, decision 043).

## Tests
- `api/tests/test_gpx.py`: a build id gives the first route and a route id gives that route; unknown routes give none;
  the file is valid GPX with the start, the miles and the turnaround; a label with markup stays well-formed.
- `api/tests/test_server.py`: the endpoint, the header and file name, 404 and 401.
- `evals/routes/test_review_fixes.py` (live): a built route's every route downloads, with as many track points as
  its line and a Start and Mile 1 waypoint.
