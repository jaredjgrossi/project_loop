# 028: The parser — one Haiku 5.5 extraction, then deterministic rules

**Status:** accepted (2026-11-08). Phase 3, step 4. Extends 025 (parse on the server), 026 (places) and 027
(RunConstraints). Model and settings chosen by Jared.

## Decision
- **One Claude call per parse** (`api/parse.py`) to `claude-haiku-5-5` at effort `low`, with adaptive thinking.
  - The model calls a single tool, `record_request`, which records the runner's words: a distance and its unit, a
    range, minutes, time and day words, place specs, avoids, preferences, stops, past-route words, a second run,
    and can't-do flags.
  - The tool never holds RunConstraints, numbers code computes, or coordinates.
  - The prompt is `api/prompts/parse_v3.md`, cached (about 5,150 tokens, read on 97% of calls). v1 and v2 stay in
    `api/prompts/`, since their calls are in `llm_calls` by version.
- **The tool isn't strict.** Strict mode allows 16 nullable parameters, and then rejected this schema's compiled
  grammar as too large. So:
  - Nothing in the schema is nullable. "Not said" is `"none"`, `""`, `0` or kind `"none"`.
  - `_conform` checks the input against the schema itself. It fills what the model left out, strips quotes around
    a choice, reads a number written as text, and drops an unknown can't-do key. Anything else fails the parse.
  - A malformed call (Haiku once leaked markup into a value) is asked for once more, and both calls are logged.
  - `tool_choice` is `auto`, because forced tool choice returns a 400 on the larger 5.5 models.
- **Code applies the eval rules** to the extraction (R1–R19):
  - It resolves places (decision 026) and addresses (GeoSearch, with the borough rule).
  - It turns time words, days, units, ranges and fractions into values.
  - It fills usual and default values, each labeled with its source.
  - It builds RunConstraints, chips, can't-do lines, notes or the one question. Every string comes from
    `api/copy.py`.
- **Rules held in code because the model didn't hold them:**
  - G8 follows the `workout` flag.
  - A place that looks like an address is geocoded.
  - A via through a park sets park scenery.
  - "Scenic" and "showing someone around" never set scenery (R6, eval P39): the model kept setting it, so code
    drops scenery when sightseeing words are the only cue.
- **Names live in the places table, not the prompt** (Jared, 2026-11-06). Curated redirects send "West Side Highway"
  to the Hudson River Greenway and "East River Path" to the East River Greenway. The prompt names no places.
- **Claude never receives coordinates.** It sees the text, the local time, whether location is known, saved-place
  labels and recent-route names, and a test checks this. `llm_calls` (`api/llm_log.py`) keeps the raw text, model,
  effort, thinking, tokens, cost and latency, never location, and deletes rows after 30 days. Its DDL runs once per
  process, behind a lock, after parallel parses deadlocked on it.
- **Latency target: about 3 s** for the parse (Jared, 2026-11-08, raised from 2 s). The app designs the wait.

## Numbers
Haiku 5.5 at low effort, three runs of the 50 parse evals each, five parses at a time.

| Setup | Pass per run (of 50) | Cases passing all 3 | Of the 35 needing nothing later | Cost / parse | Claude latency, median / p90 |
|---|---|---|---|---|---|
| prompt v1, thinking on | 36 / 33 / 36 | 29 | — | $0.00056 | 3.25 s / 4.6 s |
| prompt v2, thinking on | 48 / 43 / 44 | 40 | 34 / 32 / 31 | $0.00057 | 3.28 s / 4.1 s |
| prompt v3, thinking on | 46 / 47 / 47 | 44 | 33 / 33 / 33 | $0.00055 | 3.01 s / 4.2 s |
| v3, regraded with the final grader and code | 47 / 49 / 48 | 46 | 34 / 35 / 34 | — | — |
| v3, thinking off | 41 / 41 / 41 | 40 | 30 / 30 / 30 | $0.00053 | 2.80 s / 3.0 s |
| **final code, thinking on (committed)** | **48 / 47 / 45** | **44** | **35 / 34 / 32** | **$0.00058** | **2.96 s / 4.3 s** |

- End to end (Claude, lookups, geocoding), the final code's median is 3.07 s.
- **Thinking off is rejected.** It misses the bar Jared set (44 or more cases passing all three runs, as v3 does),
  and it saves only 0.2 s. Output stays at about 830 tokens, because most of it is the tool input itself, with every
  unsaid field written out.
- The lever for speed is a shorter tool input: since the tool isn't strict, the model could leave unsaid fields
  out. Not tried yet.
- Sonnet 5.5 and larger were not tried (Jared: stay on Haiku).
- The total spent on these runs is about $0.60, every call logged in `llm_calls`.

## Still failing (final code)
- **H04, every run:** "skip the ferry part" needs the reused route's geometry. It is handled in step 10, in code:
  "ferry" is matched against the `pulse_sources` landings along the reused route.
- **P49, every run:** Haiku sometimes writes "East River Esplanade", a real OSM park, for "the east river path", and
  the park then sets scenery. P49 waits on step 8 (via places), so this is taken up there.
- **Flaky, one run in three:**
  - P04 and P39 (a start marked as said)
  - R05 (`familiar=new` from "new to this area")
  - P23 (a stretch starting at E 16th St)

## Eval changes (approved by Jared)
- Rule 3 counts `usual` as code-filled and applies to PARSE outcomes. An unlisted day equal to today is allowed.
- P23 is loosened to "1st Ave, along, a stretch inside E 23rd–E 34th St" (2026-11-08).
- Names compare as the places table compares them ("First Avenue" is "1st Ave").
- `api/tests/test_parse.py` gives `build()` the extraction a correct model returns for each of the 50 cases. All 50
  pass with fake places, and all 50 pass against the real places table and geocoder. That separates rule bugs from
  model misses.
