# 036: Along-avoids — don't run along a street; crossing it is fine

**Status:** accepted (2026-11-09). Phase 3, step 8b (added by Jared, 2026-11-06). Implements rule R15 in the engine;
before this an along-avoid was a blocking can't-do line.

## Decision
- **The street, from the places table.**
  - An along-avoid names a street ("42nd St") or a stretch ("1st Ave, E 25th–E 34th St", the parser's form,
    decision 028).
  - Code finds the street nearest the start (`places.lookup`) and takes its centre lines within 6 km.
  - For a stretch, code cuts those lines between the points where its two cross streets meet them.
  - Code also finds every crossing: where another street or path meets it.
  - Claude only names it; code finds every coordinate.
- **Two halves, like a no-go zone (decision 010), but costly rather than closed:**
  - **The router:**
    - A strip 20 m either side of the centre line (the sidewalks too) is cut into one GraphHopper area per block,
      with a 30 m gap around every crossing.
    - Edges in the strip get priority 0.05 (20 times the cost).
    - The gaps matter. A GraphHopper area catches every edge that touches it, so without them the side streets that
      meet the avenue would cost as much as running along it.
  - **The hard rule:** a route that stays inside the whole strip for 75 m or more in one go runs along the street,
    and is rejected (`runs_along`).
    - Crossing a 30 m avenue takes about 40 m of strip, and a diagonal crossing about 50 m.
    - A short block is about 80 m.
- **One priority rule for all the areas.**
  - GraphHopper evaluates each rule on every edge. With 25 separate rules a route took 0.13 s, against 0.05 s with
    one rule (`in_a || in_b || ...`), and 0.015 s with none.
  - Simplifying the polygons didn't help further.
- **A street Loop can't find** near the start isn't avoided. `final.notes` says so (`avoid_not_found`, rule 3).
- **Along-avoids no longer block the build:**
  - `avoid_along` leaves the engine's "later" list;
  - the server builds;
  - the contract's can't-do section says so.

## Results (live, Kips Bay, public stand-in contexts)
| Case | Without the avoid | With it | Engine time (without → with) | First route after `parsed` |
|---|---|---|---|---|
| R07, 3.1 mi, avoid 42nd St | top 3 never near 42nd St | the same top 3 | 7.3 s → 13.5 s | 0.26 s → 1.24 s |
| P23, 6 mi, avoid 1st Ave E 25th–E 34th St | #1 runs 131 m along the stretch | no route along it; a new #1 | 18.5 s → 25.4 s | 0.36 s → 0.56 s |

- **The cost:**
  - The engine is slower: about 1.4 to 1.8 times, mostly the router's area checks.
  - The first route comes later. Finding the street and its crossings takes about 0.5 s before generation starts.
  - Only requests with an along-avoid pay it.
- **The check itself** costs 1.3 ms per candidate, with the strip cached per street.
- **No other route moved:** all 147 live route evals pass, and the pinned top 3s are unchanged. One is skipped: the personal-runs eval, which needs the git-ignored run data.

## Tests
- `api/tests/test_along.py` (13):
  - running along is caught; crossing straight or diagonally isn't; a parallel street a block away isn't;
  - router areas leave the crossings open and cover mid-block and the sidewalk;
  - one priority rule;
  - stretch names split; a stretch is cut between its cross streets;
  - the generator rejects a route along the street;
  - the engine passes the streets to the router and the rule, and notes a street it couldn't find.
- `api/tests/test_server.py`: an along-avoid builds. The blocked-build tests moved to past routes (step 10).
- `evals/routes/test_along.py`: R07 and P23 end to end. No route runs along the street.
