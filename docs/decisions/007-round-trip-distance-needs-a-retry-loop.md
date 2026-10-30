# 007: Hitting the distance target needs a retry loop (Phase 2)

**Status:** finding in Phase 1; implementation deferred to Phase 2

GraphHopper's `round_trip` treats the requested distance as a hint. For a 4.0 mile request from the same start point, seeds 0 through 6 returned 3.03, 10.71, 3.64, 3.00, 3.27, 3.09 and 3.90 miles: mostly 3 to 4 miles, with a 10.7 mile outlier. Seed 0 misses by -24%, against the plan's ±5% target.

Phase 1 reports the real distance and says when it is outside ±5% (`make_loop` prints the miss and suggests `--seed`). Phase 2 should: request many seeds, rescale `round_trip.distance` by requested/actual and retry, keep the candidate closest to the target, and, if none is within tolerance, return the nearest one with how far off it is (product rule 3).
