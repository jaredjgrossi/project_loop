# 044: Honest kinds and names, no spurs, the main turnaround, loop as a hard rule, climb without noise

**Status:** accepted (2026-11-11). From Jared's phone test of "5 miles starting on west 71st st", with the route
type set to Loop, before marking PR #11 ready. Amends decisions 008 (shape), 014 (elevation), 020 (markers) and
037 (hills).

## What the phone showed, and why
- **Labeled "loop", but an out-and-back.**
  - The #1 was 67% retraced: up the Hudson River Greenway and back, with a small loop at the far end. The generator
    called routes out-and-backs only from 70% retraced, so this was a "lollipop".
  - Its label came from the job that made it, "loop on Riverside Walk, heading 19 degrees", and the route file was
    named "Loop route" for every route.
- **The route type the app sent did arrive.**
  - The Loop builds came with a top-level `shape: "loop"`; the text has no shape words. The chip edit carried it in
    `constraints` too. Neither side dropped it.
  - The server's rule for "loop" accepted lollipops.
- **TURN at the wrong place.** The route had a dead end 1.3 km in, reaching only 170 m (a quick out-and-back off the
  greenway that padded the distance). The turnaround finder marked every reversal, spur or not.
- **Climb 130.5 m** on ground that spans 0–27 m. Gain summed every route point's height through a 1.5 m threshold,
  so tile noise counted as climbing.

## Decision
- **Kinds are measured, and names follow them.**
  - Out-and-back from 50% retraced (was 70%): "most of it retraced".
  - A route's name (`label` in route entries, `label` and `name` in the route file) is the kind plus the place from
    the generator's label (`api/naming.py`): "Out-and-back on Riverside Walk", "Loop on the street grid".
  - The generator's own label stays in `plan` and in the candidates, so the pinned evals still compare like with
    like.
- **Turnarounds and spurs** (`api/markers.py`):
  - Every reversal is found on the route sampled every 5 m. A point is a tip when the route 40, 100 or 200 m before
    and after it comes back within 25 m.
  - Each reversal's reach is how far the way out runs within 30 m of the way back, crossing gaps up to 150 m (a
    turn around a block).
  - A turnaround reaches 400 m or more, or is at the route's farthest point from the start.
  - A spur reaches 150–400 m: "a quick out-and-back of a few hundred meters", 300–800 m in all. It also isn't
    within 300 m of the start or finish, where the start sits mid-block.
  - A shorter reversal is part of the line, neither a spur nor a turnaround.
    - At first every reversal under 400 m counted, and that changed 12 of the 30 pinned #1s: waterfront
      out-and-backs whose way onto an esplanade doubles back 50–135 m (a ramp or a footbridge approach).
    - The phone's spur reached 170 m.
- **The spur rule:** the generator rejects a route with a spur (`spur`), so distance is made up by the main line, or
  the route is a little short within tolerance. A past route rebuilt or run again keeps the spurs the runner ran.
- **Loop is a hard rule:**
  - `shape: "loop"` accepts loops only.
  - The generator keeps the best routes of the kinds it rules out (`GenerationResult.fallback`).
  - With no loop at all, those come back with the note "No good loop from here; showing the best out-and-back".
  - With loops that miss the distance, the nearest loop comes back with the usual distance note.
- **Climb** is read from the height every 0.1 mi through a 2 m dead band: the reading moves only when the height
  leaves the band. It's given in whole meters.
  - Hills (decision 037) use the same reading. Its threshold rose from 1 m to the 2 m band, so the two always
    agree.

## Results (live, 5 mi from W 71st St)
| Route type | Before | After |
|---|---|---|
| any | #1 "out-and-back through Central Park"; route named "Loop route" | #1 "Out-and-back through Riverside Park", 4.92 mi, 97% retraced, one TURN at 2.46 mi, no spurs, climb 47 m |
| loop | #1 a lollipop (67% retraced), "loop on Riverside Walk", TURN at the spur (0.82 mi), climb 130.5 m | #1 "Loop on the street grid", 4.92 mi, loops only, no TURN, climb 28 m |

## Tests
- `api/tests/test_markers.py`:
  - a spur isn't the turnaround;
  - only the main turnaround is marked;
  - a plain out-and-back has one turnaround and no spur;
  - a jog at the start isn't a spur.
- `api/tests/test_generate.py`:
  - a route padded with a spur is rejected;
  - mostly retraced is an out-and-back, and loop rules it out but keeps it as a fallback.
- `api/tests/test_engine.py`: with no loop, the best other kind comes back with the note; with loops, the fallback
  is never used.
- `api/tests/test_naming.py`: names start from the kind; a route that isn't a loop is never called one.
- `api/tests/test_elevation.py`: per-point noise isn't summed as climbing; whole meters.
- `evals/routes/test_w71st.py` (live):
  - no spur;
  - names from the kind;
  - TURN at the main turnaround;
  - loop as a hard rule;
  - climb in whole meters and under 70 m.

## Pinned top 3s (re-pinned with `evals.routes.time_generation --pin`)
- **One #1 changed, of 30 rows:** `kips-bay|6|waits`. The old #1, "out-and-back on the waterfront, heading 3 degrees", has a dead end reaching 150 m, 970 m in. The new #1 is a 1.5:1 street-grid rectangle (a loop). The same start with `zigzags` keeps its #1: its dead end reaches 125 m.
- **#2 or #3 changed in 11 rows,** from spurs ruled out and from lollipops now counted as out-and-backs (50% retraced). No row changed only its kinds.
- **All 215 live place, route and app evals pass.** One is skipped: the personal-runs eval, which needs the git-ignored run data.
