# Parse evals

The 50 cases from `docs/phase3/parse-evals-v1.md`, one file each in `cases/`, graded by `grader.py`.

```
make eval-parse                          # the stub parser: every case fails
make eval-parse PARSER=api.parse:parse   # once the parser exists (Phase 3, step 4)
uv run python -m evals.parse.run --case R02 -v
```

## Files
- `contexts.json`: C1, C2 and C3 (now, location, profile). Places are public stand-ins: Kips Bay Library, Grand Army
  Plaza, Union Square. `label` and `stand_in` are for people and are dropped from the request.
- `recent_routes.json`: the list the phone sends in C1 and C2.
- `cases/<id>.json`: `context`, `text`, `doc` (the line from the evals doc), `expect`, optional `alternatives`, and
  `must_not` as machine checks. `needs` names the later step a case depends on (`end`, `via`, `reuse`, `hills`,
  `planned`); the table counts those apart.

In `expect`, each field is `{"value", "source"}`; source is `said`, `preset`, `default` or `usual`, and is only
checked when given. "Now" and "today" are written as the context's values (06:40, 2026-11-03). Place refs are
`{"place": name}`, `{"address": text}` or `{"saved": id}`, with an optional `"borough"` (R19); avoids are `{"name", "how"}`.

## What the parser returns
See the docstring at the top of `grader.py`: the contract's `parsed` event, plus a `trace` with each field's source,
the place lookups made, the routing calls made, and the template key behind every string the runner sees.

## Keys chosen here (Code owns the keys; the wording lives in `api/copy.py`)
- Can't-do lines use the gap ids G1–G11, plus `bike_lanes` for P25 (the bike-lane rule has not landed).
- Notes: `crowds_estimated` (R04, P24) and `fountains_seasonal` (P35).

## Grading choices (2026-11-06)
- Rule 3 ("no unlisted field beyond code-filled defaults") counts the runner's usual values (source `usual`) as
  code-filled, alongside `default` and `preset` (R2). An unlisted day equal to the context's today is allowed too.
- Rule 3 applies to PARSE outcomes. An ASK keeps what the runner said so the answer can continue the request; its
  keep list is the minimum that must be kept. Must-nots still apply to every case.
- Rule 8 (spans, 2026-11-09) applies to every outcome: a said chip without a span, or a span that isn't the request's
  words at its positions, fails the case. The oracle gives each said chip the whole sentence as its span.
