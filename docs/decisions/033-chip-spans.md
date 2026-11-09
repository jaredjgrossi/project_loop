# 033: Chip spans — Claude quotes the runner's words, code finds them

**Status:** accepted (2026-11-09). Asked for by Jared after the request-screen design changed (UI decisions log,
2026-11-08): no chips on screen; the runner's sentence is the header, and while editing, the words Loop understood
light up and each opens the chip editor. Extends 028 (the parser) and 029 (the API).

## Decision
- **Claude quotes; code locates** (rule 1: Claude never produces numbers).
  - The extraction tool gets one list, `said`: `{chip, item, words}`, one entry per recorded value, with the
    runner's exact words. `item` is the 1-based position for via, avoid and amenity, and 0 otherwise.
  - The prompt is `parse_v4` (v3 plus "The runner's words"). It also adds one more rule from these runs: never add
    a cross street the runner didn't name.
  - `api/spans.find_span` finds the words in the request text as sent. It forgives letter case, curly quotes,
    dashes and runs of spaces, and maps the match back to the original characters.
  - A span is `{text, start, end}` in Unicode code points, end exclusive, and its `text` is always the request's
    own characters. Words that aren't found give `span: null`; code never guesses.
- **Every chip gets `span`:**
  - Said chips get their words. Preset, default and usual values get null.
  - A chip code set from another one's words shares that span: park scenery from a via park.
  - Chips built from a list map back to their item even when code dropped one, such as a street-the-whole-way via
    or an amenity with no mile.
- **The question gets `chip_id`.** When nothing was built for it yet ("Which 86th St?"), the event carries a chip
  made from the runner's own words (template `chip.asked`).
- **Quotes never fail a parse.** A quote with an unknown chip name is dropped and listed in the trace; Haiku's
  `day` is read as the time chip. Before this, a quote labeled `day` or `soft_avoid` failed R01, R09 and P27 outright.
- **`constraints.spans`**, by chip id, carries the spans through a chip edit. The app drops an edited chip's entry.
  Spans are never stored with a build (R8: they're the runner's words). `saved_routes` keeps the constraints without
  them.
- **Grader rule 8:** every said chip has a span that is the request's words at its positions, every other chip has
  null, and `chip_id` names a chip in the event or is null. It applies to every outcome.

## Numbers (Haiku 5.5, low effort, three runs of the 50 parse evals)
| Prompt | Pass per run | Cases passing all 3 | Said chips without a span | Cost / parse | Latency, median / p90 | Output tokens (median) |
|---|---|---|---|---|---|---|
| v3 (decision 028) | 48 / 47 / 45 | 44 | — | $0.00058 | 2.96 s / 4.3 s | ~830 |
| v4, first draft | 46 / 44 / 44 | 43 | 2 parses (R06) | $0.00062 | 3.43 s / 4.8 s | 926 |
| **v4 (committed)** | **49 / 47 / 48** | **47** | **0 of 150 parses** | **$0.00062** | **3.25 s / 4.9 s** | **927** |

- Spans cost about 0.3 s at the median and 100 output tokens.
- Step 5b, leaving unsaid fields out of the tool input, is the lever to win that back.
- Still failing: H04 (step 10, in code).
- Flaky: R05 (`familiar=new` from "new to this area", 2 of 3) and P23 (a stretch starting at E 15th St, 1 of 3).
- This round cost about $0.19, all logged in `llm_calls`.

## Tests
- `api/tests/test_spans.py` (12): exact words; case, quotes, dashes and spaces; words that aren't there; repeated
  words take the next occurrence; an emoji before the words.
- `api/tests/test_parse.py`: the quotes a correct model gives for all 50 cases. All 50 pass rule 8 against the fake
  places. Also: spans on said chips and null on others; no guess for missing words; scenery from a via; the
  question's chip; spans through a chip edit; positions from the text as sent; bad quotes dropped.
- `evals/parse/test_harness.py`: rule 8 catches a missing span, a span at the wrong positions, a span on a default,
  and a `chip_id` that isn't a chip.
- `api/tests/test_server.py`: spans are in the event and not in `saved_routes`.
