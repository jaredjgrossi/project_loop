# 021: Counting each crosswalk once favors out-and-backs, most for runners who wait. Documented, not fixed

**Status:** open (Phase 2, 2026-11-03). Nothing in the ranking changed. This records a known bias and a test that measures it, so that changing the ranking input is a separate decision, made with the reviewer's ratings.

## The bias
The ranking's signals dimension uses `crossing_counts`: each signalized crosswalk the route walks counts once, however often it's crossed (011). An out-and-back crosses most of its crosswalks twice. A runner who waits stops at each one every time, but the ranking sees half of those stops. A loop of the same length with the same number of stops is counted in full. So for the same stops, the out-and-back gets the better signals fit.

Decision 020 now counts every crossing for display (stretches, the summary's lights a mile, the expected wait), but deliberately not for the ranking.

## How large (measured)
**The unit test** (`api/tests/test_ranking.py::test_counting_each_crosswalk_once_favors_out_and_backs_for_runners_who_wait`) takes a 3 mi out-and-back that crosses 9 crosswalks out and the same 9 back: 18 stops, 6.0 a mile, counted as 3.0. Compared with the same route counted at every crossing, it scores:
- 5.4 points higher for a runner who waits;
- 2.3 points higher for a runner who zig-zags.

The gap is wider for runners who wait because 010 weights signals four times as heavily for them (×2.0 against ×0.5).

**Live pools.** Seven review rows, run without the reviewer's runs and with no start time. Each candidate within the distance limit is re-scored with the signals fit from every crossing; nothing else changes. Duplicates aren't dropped here.

| | Runners who wait | Runners who zig-zag |
|---|---|---|
| Out-and-backs: points gained by counting once | median 5.8, max 16.5 (n=141) | median 3.4, max 7.0 (n=133) |
| Loops | median 0.0, max 0.7 (n=100) | median 0.0, max 0.4 (n=97) |
| Lollipops | median 1.0, max 7.0 (n=16) | median 1.1, max 3.3 (n=30) |
| #1 that changes | 2 of 7 rows | 2 of 7 rows |

Where the #1 changes, both times an out-and-back gives way to a loop:

| Row | Runners who wait: #1 now → counted at every crossing | Runners who zig-zag |
|---|---|---|
| Kips Bay 6 mi | out-and-back 74.3 (3.0 a mile once, 6.7 at every crossing) → loop 73.5 (8.7 / 8.9) | out-and-back 73.2 → loop 71.4 |
| Flatiron 4 mi | out-and-back 68.8 (2.8 / 5.6) → loop 63.7 (6.6 / 6.6) | out-and-back 68.0 → loop 65.5 |

Upper East Side 3 mi swaps between two out-and-backs tied at 92.1 for runners who wait. That's a tie, not a change of route type. At the other rows the #1 stays an out-and-back, typically about 5 points lower.

## Why it isn't fixed here
- **It would reorder routes.** Counting every crossing ranks out-and-backs lower, most for runners who wait. That's a ranking change, which the reviewer asked to keep out of 020.
- **Every crossing over-counts real behavior.** On the way back, the reviewer often takes the other sidewalk (020: 1.36 crossings per crosswalk on real out-and-backs, against 2.0 on generated ones). Generated out-and-backs retrace exactly, so they really do cross each light twice, but a runner may not run them that way.
- **The real-run eval (011, 012) uses the same count on both sides.** Changing it changes the answer key too. The verdicts would need re-running, not just re-reading.

## Options for the follow-up decision
1. **Rank on every crossing.** The simplest, and honest about stops. It reorders 2 of 7 rows in the table above. 010's signals weight is untuned, so it may need revisiting at the same time.
2. **Rank on every crossing, for runners who wait only.** They're the ones who pay for each stop. Zig-zaggers are partly credited by the expected wait already (015).
3. **Rank on expected wait** (015) in place of signals a mile, for runners who wait. It already counts every crossing and credits zig-zag alternatives. It would need to become a scored, labeled `estimate` dimension.
4. **Leave it,** if the ratings show runners prefer out-and-backs anyway (011: 66% of the reviewer's runs).

The reviewer's "I ran it" ratings (014's feedback schema) are the evidence to choose between these.
