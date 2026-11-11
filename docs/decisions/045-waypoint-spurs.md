# 045: A spur at our own waypoint moves the waypoint, not the route

**Status:** accepted (2026-11-11). From Jared's review of the re-pinned rankings after decision 044: kips-bay|6|waits
lost its waterfront #1 to a street-grid rectangle "because of a 150 m dead end". Amends decision 044 (spurs).

## What the dead end was
- The pinned #1 (before 044) was an out-and-back on the waterfront: 6.01 mi, 3.0 lights a mile, 51.7% waterfront.
- Its only spur was at 0.6 mi: 150 m reach, 2.4 m median between the way out and the way back.
- On the map (OSM ways from `osm_ways`):
  - The route crosses FDR Drive at E 34th St onto the East River Esplanade.
  - It goes 75 m south on the Esplanade (way 368939313, `highway=cycleway`, `foot=designated`), turns around in the
    middle of that way, and comes back to E 34th St. Then it runs north.
  - The Esplanade doesn't end there: the way runs on to FDR Drive's service road.
- The turnaround point is the anchored job's `entry` waypoint, exactly (40.7425, -73.9723): the shore point nearest
  the start. The streets reach the Esplanade at E 34th St, not there, so the route went to the waypoint and back.
- So it was neither an access path nor a ramp: a U-turn on the Esplanade itself, made by our own waypoint. The
  044 rule was right that it was padding. Dropping the whole route for 150 m of it was the wrong consequence.

## Decision
- **A spur at one of the route's own waypoints moves that waypoint to the spur's base, and the route is routed once
  more** (`generate.without_waypoint_spurs`).
  - GraphHopper's way between two waypoints never doubles back, so a quick out-and-back off the main line ends at
    one of our waypoints: one that sits off the way the streets go.
  - A spur is "at" a waypoint when its tip is within 30 m of it, beyond the waypoint's own distance off the route
    (where GraphHopper snapped it).
  - The base is the spur's tip less its reach, on the way out (`markers.point_along`). Every visit to the waypoint
    moves (the entry is visited going out and coming back). The start and the end never move.
  - One more routing call, only for routes with such a spur.
- A spur away from every waypoint is left as it is, and the 044 rule still rejects the route.
- The spur rule itself is unchanged: 150–400 m reach, more than 300 m from either end. No threshold moved.
- It applies to every generator that routes through waypoints: loops and out-and-backs (`route_fn` and the
  area-preferring router), one way (`a_to_b`), and via places (`via_jobs`). Not to past routes or "run again"
  (`spurs_ok`), which keep the line as run.

## kips-bay | 6 mi | waits
| #1 | Kind | Distance | Lights a mile | Waterfront | Spur |
|---|---|---|---|---|---|
| Pinned before 044 | Out-and-back on the waterfront | 6.01 mi | 3.0 | 51.7% | 150 m at 0.6 mi |
| After 044 (main) | Loop on the street grid | 6.11 mi | 8.7 | 23.4% | none |
| 045 | Out-and-back on the waterfront | 5.76 mi | 3.1 | 49.7% | none |

The 045 route is 5.76 mi, 4% short of 6, inside the 5% tolerance: the 2 × 75 m of padding is gone.

## Pinned rankings
- Re-pinned (`evals/routes/pinned_top3.json`).
- Of 30 pinned rows, one #1 changed, the intended one: kips-bay|6|waits, from "Loop on the street grid" back to
  "Out-and-back on the waterfront". Every other #1 is the same line as after 044.
- #2 or #3 changed in 15 rows. Candidates that 044 dropped for a waypoint spur now come back without it, and lines
  that went through a moved waypoint are a little shorter.

## Tests
- `api/tests/test_waypoint_spurs.py`, a fake network with dead ends off a main path:
  - a spur at a waypoint moves the waypoint (both visits) to the base, and the result has no spur;
  - a route without spurs is routed once;
  - a spur away from every waypoint is left for the spur rule;
  - the area router's extra argument passes through.
- `api/tests/test_markers.py`: `point_along` interpolates and clamps.
- `evals/routes/test_waypoint_spurs.py` (live): kips-bay 6 mi waits #1 is an out-and-back with at least 45%
  waterfront and at most 4 lights a mile, within tolerance, with no spur and no U-turn at the E 34th St entry.
  Fails on main.

## Checks
- 1,059 unit tests pass with CI's no-database settings.
- All live route evals pass: the 30 pinned rows (re-pinned), W 71st St (no spurs, honest kinds), one way, via
  places, past routes, and the rest (119).
