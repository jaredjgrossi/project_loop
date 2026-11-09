# 040: The model leaves unsaid fields out (step 5b)

**Status:** accepted (2026-11-09). Phase 3, step 5b, run after step 11 at Jared's request, before merging PR #11.
Kept by the brief's rule: 44 or more cases pass all three runs.

## Decision
- **The tool schema no longer requires every field.** `_obj(props, need=...)` requires only what makes a value
  mean anything:
  - a place's, time's, day's or past route's `kind`;
  - a distance's value and unit;
  - an avoid's name and how;
  - a via's name and kind;
  - a stop's kind;
  - a quote's chip and words;
  - a second run's `present`.

  Nothing at the top level is required. `_conform` already filled missing fields as not said, so code reads a
  sparse input exactly like a full one (`test_a_sparse_tool_input_reads_as_the_full_one`).
- **Prompt `parse_v7`** is v6 with one rule changed and two clarified.
  - Leave out every field the runner didn't say. No "none", empty text, 0, empty lists, or objects of kind "none".
  - The field lines say "leave it out" where they said "none" or 0.
  - Two phrases fix regressions the first v7 draft showed:
    - "A place named on its own ("kip bay 3 mi") is the start, not the end." P04 failed 3 of 3 without it.
    - "'no bike lanes' is this (the `bike_lanes` can't-do flag), not an avoid." P25 failed 2 of 3 without it.

## Numbers (Haiku 5.5, low effort, three runs of the 51 cases; latency and tokens from `llm_calls`)
| | v6 (before) | v7 first draft | **v7 (kept)** |
|---|---|---|---|
| Pass per run | 46 / 50 / 47 | 50 / 47 / 49 | **51 / 49 / 51** |
| Cases passing all 3 | 44 | 47 | **49** |
| Claude latency, median | 3.27 s | 1.54 s | **1.61 s** |
| Claude latency, p90 | 4.85 s | 2.80 s | **3.11 s** |
| End to end per parse, median (Claude, lookups, geocoding) | 3.36–3.46 s | 1.62–1.71 s | **1.66–1.74 s** |
| Output tokens, median | 932 | 215 | **219** |
| Cost per parse | $0.00061 | $0.00024 | **$0.00024** |

- The model writes about a quarter of the tokens it did. A parse takes half the time and costs 40% as much.
- `parsed` reaches the phone about 1.7 s sooner.
- Still missed once each:
  - R02: the Reservoir recorded with the word "through", so it's passed instead of lapped;
  - R11: no "How far?" question.
- This round cost about $0.06, all logged in `llm_calls`.
