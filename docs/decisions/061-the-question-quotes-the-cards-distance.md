# 061: The engine's distance question quotes the number the card will show

**Status:** accepted (2026-11-16). Found in the demo's segment E (issue #50); narrows decisions 034 and 035 (the
"Make it X mi?" questions) and the brief's steps 8 and 9.

## Context
"A lap of the Prospect Park drive loop and the way there takes at least 4.3 mi. Make it 4.3 mi?" was answered, and
the route came back as 4.22 mi. The question quoted GraphHopper's length of the shortest tour (6831 m, 4.245 mi)
rounded up to the next tenth; the card measures the same route's geometry (6796 m, 4.22 mi). A stated minimum was
undercut by two steps that had nothing to do with the lap: the rounding (0.055 mi) and the two measurements
(0.022 mi). The rounding up was there so an accepted answer was never shorter than the shortest way; the tenth
bought that at the cost of overstating it.

## Decision
- **The question and its option quote the shortest route's geometry length at the card's precision** (0.01 mi,
  `api.shape.measured_m`, the shape metrics' own projection and sum). The accepted answer is then the distance the
  card shows: "takes at least 4.22 mi. Make it 4.22 mi?" builds a 4.22 mi card. The copy is unchanged.
- **The feasibility check uses the same number** (`shorter_than_the_shortest_way` compares the quoted value, not
  the raw meters), so an accepted answer can never be asked about again, even at a 0 % tolerance.
- The A-to-B question ("The shortest way there is X mi") changes the same way; the two share `ask_miles`.
- Nothing else uses the new measurement: the generators still scale from GraphHopper's figure, and the card's own
  measurement is as before.

## Checked
- Unit tests: five expectations updated to the new numbers (`api/tests/test_a_to_b.py`, `api/tests/test_engine.py`, `api/tests/test_server.py`).
- Pinned top 3 (`evals/routes/test_pinned_top3.py`): unchanged. None of the 30 rows has an end or a via, so none
  reaches the shortest-way check; the run is the proof.

## Not done
- The question still says "at least", and the route can measure a hair over the quoted two decimals (4.2228 shows
  as 4.22). That is the card's rounding, the same on both sides.
