# 057 · Out of area for named places and typed answers

*2026-11-14 · branch `out-of-area-named`*

## What went wrong
A phone test from outside New York (after decision 056): "3 miles from the Ritz Carlton Naples" made the server ask
"Couldn't find Ritz Carlton Naples. What's the address?" and then "couldn't find" again. Decision 056 sent `out_of_area`
only when Claude set `outside_nyc` on the extraction, and Haiku does not set it reliably: "Starbucks Tampa" was never
flagged, and the same Naples request was flagged on one run and not on the next. A typed answer was never checked at all.

## Decision
A second, small Claude call decides whether words name a place outside the five boroughs (`claude_area_check`, prompt
`area_v1`). It returns true or false and nothing else; code makes the `out_of_area` error from the runner's own words.
Claude still produces no geometry, numbers or copy. It runs:
1. **Where the lookup finds nothing.** Every site that would ask "Couldn't find X. What's the address?" (a start, end or
   via by name, an address the geocoder can't place) asks the area check first; outside means `out_of_area`, never the
   question. A place that is found is not checked, so a normal request pays nothing.
2. **On every typed answer, before the lookup,** for the start, end, a via and a planned start. A typed
   "Starbucks Tampa" is not turned into a Starbucks in New York, and a non-NYC address is `out_of_area`, not "couldn't
   find". Each text is checked once per build.
The extraction's own `outside_nyc` flag still short-circuits first and needs no second call.

## Choices worth knowing
- **Words only.** The check gets the place text, never a location or any context. A phone outside New York sends no coordinates
  to Claude (the existing rule: Claude never receives coordinates).
- **It fails open.** If the call fails or returns no tool call, the answer is "not outside" and the runner gets the old
  question. A broken check never blocks a request. Each call is logged in `llm_calls` with `purpose` "area" and
  `prompt_version` "area_v1" (Haiku 5.5, about $0.00007 a call).
- **No lookup change.** The places lookup matches whole names, so "Starbucks Tampa" or "Ritz Carlton Naples" finds
  nothing in New York; there is no case where a same-named NYC place is picked for a name with another city on it. A bare
  "Starbucks" is found as before.
- **`place` is the runner's own words** (for a typed answer, exactly what they typed), trimmed.
- **Prompt `parse_v7` is unchanged.** A `parse_v8` that spelled out the rule for the extraction was tried and dropped: it
  made the live eval fail R11 on every run (and P33 once) while v7 passes them, and the area check made it unnecessary.
  Its eval calls are in `llm_calls` under `parse_v8`.
- **Evals:** P60 (Ritz Carlton Naples), P61 (Starbucks Tampa) and P62 (an address in Naples, FL) expect
  `ERROR out_of_area`. Typed answers are multi-turn, so they are unit-tested (`api/tests/test_area.py`,
  `test_server.py`) and were run live against the branch server with the request's location set outside New York.

## Checked
Live parse evals, P19 and P60 to P62: 4 of 4 on three runs in a row. Whole set, two runs each on this branch and on main:
the same cases flake on both (P23, P49, P54, and R02 and R05 on main), none new.

## Not done
- **A bare chain name** with no city ("Starbucks", "the Ritz Carlton") is looked up in New York as before. A runner in
  Florida who leaves out the city gets New York's Starbucks or a question; the server doesn't use the phone's location to
  guess otherwise.
- **The city can be dropped by Claude's extraction:** "200 Fifth Ave, Naples, FL" gave `place` "200 Fifth Ave" in one run.
  The error is right; the name in it is as good as the extraction.
- **One extra Claude call** (about 1.3 s) on the requests that would have ended in "couldn't find" and on each typed place.
