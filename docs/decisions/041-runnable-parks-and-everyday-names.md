# 041: "Which park?" offers places to run; places answer to the names people use

**Status:** accepted (2026-11-09). From Jared's end-to-end phone test, before merging PR #11. Amends decision
026 (places table and lookup) and rule R13.

## Decision
- **"Which park?" offers only runnable places** (`api.places.parks_near`):
  - major parks (10 ha and up, or Battery Park on the curated list);
  - named waterfront paths at least 2 km long, with at least half their length within 60 m of the shore.

  The list:
  - takes places up to 8 km away, nearest first, at most four;
  - shows each one's distance to its nearest edge in the option text: "Central Park · 1.5 mi";
  - drops an option whose nearest point is within 150 m of a nearer one's, since that's the same place to run.

  The old list was the nearest parks of any size, and offered playgrounds and small squares.
  - The waterfront rule is a share, not a touch: the High Line comes within 79 m of the Hudson at one end and isn't
    a waterfront path.
  - `etl.load_places` measures each long path's share once (`places.waterfront_share`), so the question costs a
    0.02 s query, not the 1–1.7 s of measuring per request.
  - The automatic pick is unchanged: "the park" still means the nearest major park within about 1 mi, without
    asking.
- **Places answer to everyday names:**
  - Library outlines are loaded too (`a/amenity=library`). The Kips Bay library is mapped as its building,
    "NYPL: Kips Bay Library", and wasn't in the table at all.
  - Name variants are stored as aliases at load (`api.places.name_variants`):
    - a library: "X Library", "X Branch", "X Branch Library", and its system's "NYPL X Branch" or "New York Public
      Library X Branch";
    - a station: with and without "Station";
    - a park: with and without "Park" ("McCarren" is McCarren Park).
  - Word order and "the" anywhere don't matter. When no name matches exactly, a place whose words are the query's
    words in another order counts as exact. Partial matches search the aliases too.

## Results (live)
| From | "Which park?" options |
|---|---|
| Kips Bay | East River Esplanade · 0.4, John V. Lindsay East River Park · 1.2, Hudson River Park · 1.5, Central Park · 1.5 |
| Union Square | East River Esplanade · 0.8, Hudson River Park · 1.0, Hudson River Greenway · 1.0, John V. Lindsay East River Park · 1.2 |
| Bedford Av | McCarren Park · 0.3, John V. Lindsay East River Park · 0.9, East River Esplanade · 1.1, East River Greenway · 1.5 |

These all find the Kips Bay library, at the stand-in's own spot:
- "Kips Bay Library", "kips bay library", "the Kips Bay library" and "Library Kips Bay";
- "Kips Bay Branch", "NYPL Kips Bay Branch" and "New York Public Library Kips Bay Branch".

## Checks
- One live parse run after the reload: 48 of 51. R05 and R11 are known flakes. R03 passed 3 of 3 when re-run,
  with its lookup unchanged.
- All 156 live route evals pass.

## Tests
- `api/tests/test_places.py`:
  - library, station and park variants;
  - word order and "the".
- `api/tests/test_parse.py`: "Which park?" options are runnable, nearest first, with their distance (P20).
- `evals/places/test_lookup.py`, live:
  - the Kips Bay library by seven names;
  - parks and stations with or without the generic word;
  - from five starts, every option is runnable, nearest first, and never a playground, court, field or garden;
  - from Kips Bay, the esplanade comes first and Central Park is offered at 1.5 mi.
