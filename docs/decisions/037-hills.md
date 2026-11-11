# 037: Hills — climb per mile from the elevation every 0.1 mi

**Status:** accepted (2026-11-09). Phase 3, step 10 (the brief's step 9). Before this, "flat" was a can't-do line
("Can't score hills yet").

## Decision
- **The measure** (`api/hills.py`):
  - The route's height is read every 0.1 mi, from GraphHopper's per-point elevation (decision 014).
  - The climb is the sum of the rises between readings. A rise counts once it reaches 1 m from the last turning
    point, so tile noise on flat ground isn't climbing.
  - Also kept: climb per mile, and the steepest 0.1 mi, up or down.
- **The ranking:** a `hills` dimension, only when the runner asked for flat (`hills: "avoid"`).
  - Fit is 1 at 3 m of climb per mile or less and 0 at 20 m or more, linear between.
  - Weight 60, provisional, against park/water 30 to 60 and crowds 25 to 50.
  - "Don't mind" adds no dimension, so no other ranking changes.
  - A route with no elevation gets `not_scored`, never "flat".
- **Labeled `estimate`, not `measured`.** The brief said measured, but this is the same Terrain Tiles data decision
  014 labels `estimate` for `climb`: a smoothed ground model at 10–30 m resolution, which reads the ground or water
  under a bridge deck. One label for one source.
- **The route file:** the #1 route's `summary.hills` is the climb per mile (`m/mi`), its source and the steepest
  0.1 mi. It's only present for a flat request.
- **Calibration:** the candidates of a 5 mi run, 75–81 each, from three starts:

  | Start | Climb per mile |
  |---|---|
  | Grand Army Plaza | 5.8–24 m, median 10 |
  | Kips Bay | 2.1–10.5 m, median 4.8 |
  | Fort Tryon Park | top routes 17–23 m |

- **"Flat" changes #1 where it matters.**
  - At Fort Tryon Park, without flat, #1 is an out-and-back on Fort Washington Ave climbing 22 m/mi. With flat, #1 is
    the Harlem River Drive greenway loop, at 17 m/mi.
  - At Grand Army Plaza, #2 and #3 change but #1 doesn't: an East Drive out-and-back at 9.9 m/mi, about the area's
    median. Flipping it would take weight 150, which would drown out every other preference.
  - At Morningside Park, the flat Riverside Walk out-and-back is #1 either way.
- **Along the way, a hang fixed** in `generate._run_prioritized`.
  - A streaming callback (`on_candidate`, or the tier callback) that raised killed its worker thread. The queue
    then never drained, and the build waited forever, which in the server is a stream that never ends.
  - Now the error is kept, the thread lives on, and the build raises it once the queue is done.
  - Found because the new `summary.hills` field read a key the top-3 events don't pass.

## Results (live)
- **P33** ("6mi flat", Kips Bay): built, with `summary.hills` an estimate in m/mi and no can't-do line.
- **R11** ("4xmile workout - avoid hills"), after "How far?": built, hills scored, and the workout-segments line
  (G8) kept.
- **Fort Tryon Park, 5 mi:** flat changes #1 to a route that climbs less.
- **No other ranking moved:** all 150 live route evals pass. One is skipped: the personal-runs eval, which needs the git-ignored run data.
- **No speed cost:** scoring hills costs about 1 ms a candidate. 6 mi from Kips Bay took 28–42 s to `final` either
  way, run to run.

## Tests
- `api/tests/test_hills.py` (7):
  - flat ground; a steady hill; tile noise; down and up;
  - no elevation is not scored;
  - readings every 0.1 mi;
  - the dimension appears only for flat, and a flatter route scores higher.
- `api/tests/test_generate.py`: a failing stream callback raises instead of hanging.
- `api/tests/test_server.py`, `test_engine.py`: flat builds with no can't-do line.
- `evals/routes/test_hills.py`: P33, R11 after its answer, and Fort Tryon Park.
