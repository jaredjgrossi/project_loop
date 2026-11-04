# 022: Scheduled crowd pulses on paths, from school days and ferry arrivals

**Status:** proposed (2026-11-03). Adds data to decision 016's crowd level. No ranking weight changed. Numbered 022 because the `phase2-ui-outputs` line already uses 020 and 021.

## Context
The reviewer's run test at Kips Bay 3 mi, on a weekday morning commute, found both waterfront routes crowded on the path. Two scheduled causes:
- school drop-off beside the East River path around E 26th–29th St;
- a SeaStreak commuter boat unloading at the East 34th–35th St landing.

The ranking order matched the run (#1 better than #2). But decision 016 couldn't see either cause, because paths are `not_scored`.

## Decision
**1. Sources** (`etl/load_pulses.py`, `make pulses`, tables `pulse_sources` and `pulse_ways`):
- **DOE schools.** School Point Locations (NYC Open Data `jfju-ynrr`, file dated 2024-08-28): 1,950 public schools. 28 pulse a path (see "Which ways pulse").
- **OSM schools DOE doesn't list.** `amenity=school` more than 75 m from any DOE point, with OSM's node and area for one school merged. That's 745 private, parochial and charter schools; 15 pulse a path.
  - The reviewer chose to add these on 2026-11-03. DOE data has no school near the East River path between E 23rd and E 34th St. OSM has the United Nations International School (private) at about E 24th–25th St.
- **NYC Ferry.** Its static GTFS (feed version 2026-11-03): 50 landings, 28 pulse a path. Arrivals at a trip's first stop, or with no drop-off, are left out.
- **SeaStreak.** Arrivals at the East 35th St landing, transcribed from the timetables effective 2026-09-08 (weekday) and 2026-09-12 (weekend) into `etl/curated/seastreak_schedule.json`, with source, trust, checked date and review-by date. SeaStreak publishes no GTFS.
- **Which ways pulse:** catalog corridor ways and waterfront paths within 150 m of a source, **with no street between them.**
  - **Catalog and waterfront paths only.** These are the paths decision 016 leaves `not_scored` and runners use as routes. Counting every non-sidewalk footway took in schoolyards, plazas and park paths (1,310 of 1,950 DOE schools).
  - **No street between source and path.** The straight line from the source to the nearest point of the way may not cross a car road, from motorway down to residential and unclassified. Service roads don't count, since they run inside campuses and parks.
  - **Why the street rule.** Without it, the Upper East Side's Bobby Wagner Walk loop was 82% busy at 8am, from Brearley, M.S. 224 and Coop Tech. Those schools are across the FDR or East End Avenue, and their students never enter the walk. At Kips Bay, by contrast, UNIS sits on the running path (the reviewer, 2026-11-03). A first version that blocked only motorways and trunk roads still let schools across East End Avenue pulse.
  - **What the rule removed:** The River School (across the FDR from the esplanade at E 35th St), J.H.S. 080 (Mosholu Parkway) and Dock Street School (DUMBO), among others.
  - **What it leaves:** Brearley keeps 13 m of Bobby Wagner Walk entrance steps and connectors at E 83rd St, where no street intervenes. No review route meets them in a window.
  - **Totals:** 43 schools and 29 ferry landings pulse 726 distinct path ways.

**2. Windows**, all labeled estimate (`api/pulses.py`):
- **Schools:** arrival 7:30–8:30 and dismissal 2:20–3:20, on DOE school days only, from the 2026–27 calendar transcribed into `etl/curated/nycps_calendar_2026_27.json`. No pulses on weekends, before the first day or after the last, or on closed, remote or no-student days. Election Day, Tuesday 2026-11-03, is a remote day.
  - **DOE publishes no bell times for most schools.** Open data has start and end times only in the 2021 high school directory, so the windows are a stated default: most schools start 8:00–8:40, and the school day is 6 h 20 min.
  - **OSM schools are assumed to follow DOE's calendar.**
- **Ferries:** from 2 minutes before each arrival to 8 minutes after it.
  - **SeaStreak:** every arrival.
  - **NYC Ferry:** only weekday arrivals 7–10am and 4–7pm. Its boats call at East 34th St 214 times a weekday, every few minutes from 6am to 10pm, mostly passing through. A window around every call would make that path crowded all day. The reviewer chose the peaks on 2026-11-03.

**3. Level.** A path sample inside a window is `high` (an estimate), with the cause as its basis. For example: "SeaStreak arrival 08:00 at East 35th St (window -2/+8 min assumed, estimate)". Outside the windows, paths stay `not_scored`, as in 016.
- **Pulses count only when crowds are scored at all,** that is, when the start is in a DOT window (decision 016). A pulse at 6:45am doesn't make crowds scored.
- **The ranking fit is unchanged:** 1 − busy share. A pulse is busy distance.
- **Precedence:** a path near a DOT automated counter uses the counter first. Sidewalks keep 016's level.
- **Stretches** show the pulse with the label "scheduled crowd pulse (school or ferry, decision 022)".

## Eval (`evals/crowds/test_pulses.py`)
The morning moment is SeaStreak's published 08:00 arrival on a school day, Wednesday 2026-11-04. It is not taken from the reviewer's runs.
- The Kips Bay sources are loaded: UNIS, and the East 34th St landing for both operators.
- Schools across a street from the path don't pulse. The River School has no pulse ways. No Upper East Side top-3 route at 3, 4 or 6 mi meets a pulse at 8am from the schools across the FDR or East End Avenue (Brearley, M.S. 224, Coop Tech, P.S. 146, P.S. 158).
- At 8am on a school day, both Kips Bay 3 mi waterfront routes meet a ferry pulse at East 34th–35th St and a school pulse. "Both ways" is busier and scores lower on crowds and overall.
- At 10:30 no Kips Bay top-3 route meets any pulse.
- On Election Day (remote) there's no school pulse, but the ferries still run.

## Result: the reviewer's Kips Bay 3 mi run test, school day 8am
| route | busy | pulses met (where) | score (no start time → 8am) |
|---|---|---|---|
| #1 out-and-back on the waterfront | 8.9% | SeaStreak 08:00 at East 35th St (E 34th St); UNIS arrival (about E 23rd–25th St); NYC Ferry 08:24 at East 34th St | 83.8 → 85.5 |
| #2 out-and-back both ways | 15.3% | SeaStreak 08:00 (E 34th St); NYC Ferry 08:13 and 08:24 (E 34th–38th St, run twice); UNIS (one sample) | 79.7 → 80.9 |

- **"Both ways" scores worse,** and the gap widens from 4.1 to 4.6 points (to 5.0 with crowds "avoid").
- **The 34th St stretch: yes, on both routes.**
- **The 26th–29th St stretch: no.** The only school on the path in that area, UNIS, is at E 24th–25th St, and its 150 m pulse covers about E 23rd–25th. Neither DOE nor OSM has a school on the path at E 26th–29th. The drop-off seen there may be UNIS families walking north, or another cause. It is not stretched to fit.
- **Scores go up from "no start time" to 8am** for both routes. A start time makes crowds a scored dimension (decision 016), and a mostly quiet route scores well on it.

## Result: the 15 review rows, Wednesday 2026-11-04, crowds "some" and "avoid", pulses off (016) against on (022)
**10:30, outside every window:** all 30 runs are identical.

**8:00:** 26 of 30 runs keep their #1. The busy share rises where a route meets a pulse:
- Kips Bay 3, 4 and 6 mi: 9%, 15% and 7%;
- Flatiron 3 and 4 mi: 26% and 23%, up from 17% and 12%;
- Astor Place 6 mi: 20%, up from 17%;
- Upper East Side 4 and 6 mi: 24% and 4%, from the E 90th St ferry;
- DUMBO 3 mi: 12%, from the Dumbo/Fulton Ferry and Pier 6 ferries.

Changed (the same at "some" and "avoid"):

| row | #1 with pulses off | #1 with pulses on | busy | park or water | signals/mi |
|---|---|---|---|---|---|
| Upper East Side 3 mi | loop on Bobby Wagner Walk (27% busy with pulses on: NYC Ferry 08:14 and 08:25 at East 90th St) | street out-and-back, heading 29° | 0% | 86% → 52% | 0.7 → 3.7 |
| Williamsburg 4 mi | North 5th Street Pier out-and-back (11% busy: NYC Ferry 08:01 and 08:33 at North Williamsburg) | Domino Park out-and-back | 0% | 42% → 15% | 2.3 → 4.1 |

Both are real trades. The old #1 meets a peak ferry arrival on the path, and the new one avoids it at a cost in park, water and signals. They are the same two rows decision 016's "typical sidewalk" rule flipped, but now for a published cause. If the reviewer would rather run through a ferry arrival than leave the water, the lever is the crowds setting or the pulse level, not a ranking weight.

**Before the street rule,** the Upper East Side's Bobby Wagner Walk loop was 82% busy, from schools across the FDR and East End Avenue. The rule removed those pulses (see "Which ways pulse").


## Limits
- **The windows are assumed.** No bell times are published, and the time a boat takes to unload is a guess.
- **Pulse level is always `high`.** There's no load data: no NYC Ferry alightings by landing, and no school enrollment in the points file.
- **Early dismissals are not modeled.** They're three hours early on six days, each for one school level. Neither are school-specific calendars: private schools are assumed to follow DOE's.
- **SeaStreak holiday and modified schedules** (service alerts) are not modeled. Its timetable must be checked by the review-by date.
- **"No street between" is a proxy for "students use the path".**
  - Manhattan Center for Science and Mathematics (E 115th St, inland of the FDR) fronts three footways the Upper East Side 6 mi route uses, so it pulses them at 8am. Not checked on the ground.
  - Brearley keeps 13 m of entrance steps at E 83rd St.
  - Any school the reviewer knows is wrong can be dropped by name.
- **Ties in the final ranking are ordered by completion time.** Flushing Meadows 3 mi has a loop and an out-and-back with identical scores, and the pinned top-3 eval failed there once and passed on a rerun. A fixed tiebreak belongs to decision 018's next step.
- **The downloads aren't scripted.** `etl/load_pulses.py` refuses to run without them, and the docstring says where each one comes from.
