# 054 · Turn-by-turn steps for the Directions list

*2026-11-13 · branch `turn-steps`*

## Decision
Every route's `file` carries `summary.steps` (contract: `docs/phase3/parse-contract-v1.md`): GraphHopper's turn signs
for the foot route, with street names from the route's own labeled stretches, the turnaround from the turnaround
marker, and noise folded away. `summary.way` stays exactly as it was. Asked for by the iOS Directions list (decision
053), which could only say "Continue onto X" because the files had no turns. Code only; the LLM writes none of it.

## Choices worth knowing
- **Maneuvers from GraphHopper, names from our stretches.** Every request now sets `instructions: true` and each `Route`
  keeps `(sign, point index)` per instruction (no measurable cost: 44 ms either way on the local graph). GraphHopper's
  own street names are blank on most foot sidewalks and crossings, so the names come from the labeled stretches that
  `summary.way` uses. That keeps decision 049's rule: a runnable path is named after itself, a road's sidewalk or
  crossing keeps the road's name, and neither shows up as a step of its own.
- **Folding.** A step under 50 m joins the one before. Where a short step is folded away, the next turn is measured
  again from the line (25 m either side, GraphHopper's own angle thresholds), so a right-left jog around a crossing
  doesn't leave a bare "left". Without that, real Kips Bay routes had "left" in the middle of a straight avenue.
- **Same street, twice.** Real builds showed GraphHopper saying left/right at every bend of the East River Esplanade
  and "turn onto East 31st Street" while already on it. A "continue" onto the same street and a bend inside one path,
  park or corridor are not steps (a U-turn is). A real turn on a street the runner is already on keeps the turn and
  drops the name, because "onto" it would be wrong. The 31st/33rd Street jogs in the Kips Bay examples read "Turn left"
  for this reason: the labels give the same street for the avenue legs between.
- **A sign the line doesn't back up.** GraphHopper called a sidewalk kink with the heading 209 degrees before and 210
  after "right". A turn the line makes less than 11.5 degrees of (GraphHopper's own "continue" threshold) is a
  `continue`, which the same-street rule then drops. GraphHopper is still the source for every turn the line shows.
- **A change of street with no turn** is a `continue` onto the new street (the stretch boundary), as in "Continue onto
  New Wave Pier". These are in the list so the phone can say where the street changes, not only where it turns.
- **The turnaround is one boundary.** GraphHopper has a left, a via, a U-turn and a right around a turnaround; any
  instruction within 25 m of the marker is dropped and the marker's own step takes its place, at the marker's distance.
  A route with two turnarounds has two.
- **A start stub** under 50 m (the door to the corner) joins the first street, so the list starts with "Start on 3rd
  Avenue, 0.76 mi", not a 20 m step.
- **Tiling is exact in meters** (they are rounded cumulative positions scaled to the summary's distance) **and in the
  displayed miles** (`distance.value` is the difference of the displayed `from_mile`s), so what the screen shows adds up.
  `from_meters`, `status` and `maneuver_source` are additions to the shape asked for; `maneuver_source` is per step
  (GraphHopper, the turnaround marker, a change of street, or a turn measured from the line), so a step never claims
  GraphHopper said something it didn't.

## Checked on real routes (Kips Bay Library, stand-in start)
Out-and-back down the Esplanade: 11 steps (start on East 31st Street, a few turns to East 34th Street, "sharp right"
onto the Esplanade, turnaround at 1.51 mi, back by the same turns). The route that goes out both ways has two
turnaround steps and "Continue onto New Wave Pier" between them. The loop: "Start on 3rd Avenue 0.76 mi", right onto
East 16th Street, continue through Union Square Park, turnaround on West 16th Street, right onto West 31st Street.

## Not done
- **Routes that weren't routed have no steps.** "Run again" and a route rebuilt from a stored line have no GraphHopper
  instructions, so no `steps` key (the app keeps the stretch list, as asked). Routes stored from now on carry them.
- **Names are as good as the stretch labels.** The labeler names the nearest street within 30 m, so an avenue leg can
  carry a cross street's name or none; steps inherit that, as `summary.way` always has. A true intersection test
  would fix both.
- **No distances to the next turn on the approach, no "keep left at the fork" wording beyond the sign, and no
  roundabout exit numbers.** A roundabout is measured from the line like any folded turn.
- **The turnaround of a loop.** A loop that reverses at its far tip (the 3rd Avenue loop above) shows a `turnaround`
  step because `summary.turnarounds` lists one; the marker rule is unchanged (decision 044).
