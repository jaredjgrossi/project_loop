# Parse evals — v1
*Status: **v1, decisions applied** (2026-11-05). 50 cases: 11 real phrasings, 5 past-route phrasings Jared endorsed, 34 synthetic. Diary phrasings (Jared, R1, R2 typing real requests before runs) replace synthetic cases as they arrive; the cap stays 50. Contract: `phase3/parse-contract-v1.md`. Build: `phase3/build-brief-v1.md`.*

## What this is
The test set for Phase 3's parser: a plain-English request goes in. What comes out is `RunConstraints` plus request chips, "can't do yet" lines and notes, or exactly one clarifying question. Each case states what must come out and what must not happen. Phase 3 step 1 turns each case into a repo fixture.

Field names are the real ones from `api/constraints.py` (main, 2026-11-05). Fields marked **new** are added in Phase 3.

---

## Eval contexts
Every case names its context, so defaults are deterministic. Places are public stand-ins, never a real home address.

| | C1 · Runner 0 at home | C2 · Runner 0 somewhere new | C3 · New runner |
|---|---|---|---|
| Now | Tue 2026-11-03 06:40 ET (school day) | same | same |
| Current location | Kips Bay Library (446 3rd Ave) | Grand Army Plaza, Brooklyn | Union Square (14th St & Broadway) |
| Saved places | home = Kips Bay Library | home = Kips Bay Library | none |
| Usual distance | 3.1 mi | 3.1 mi | none |
| Usual time | 07:00 | 07:00 | none |
| Recent routes | see below | same as C1 (none near here) | none |
| Own-runs prior | available | available, no data here | none |

**Recent routes (C1, C2).** This is the list the phone sends with each request.
| id | date | name | distance | times run |
|---|---|---|---|---|
| rt_a | Tue 2026-10-27 | East River esplanade out-and-back | 3.0 mi | 5 |
| rt_c | Thu 2026-10-29 | Gramercy street rectangle | 3.1 mi | 1 |
| rt_b | Mon 2026-11-02 | Stuyvesant Cove both ways | 4.0 mi | 1 |

## Notation
`field=value (source)`. Source is the chip's word: **said**, **preset**, **default** or **usual** (from the profile or recent routes). Places look like `place:"Penn Station"`: resolved by the place lookup, trust `listed`.
- `cant:` a "can't do yet" line, with its gap id
- `note:` a caveat that isn't a refusal
- **ASK (about, from):** the single question. `about` is what it's for; `from` is parser, places or engine
- **[lookup]** the case needs the places table. **[engine]** the end-to-end result depends on routing (R9)

### Fields
Existing: `distance_mi` (0.5–30) · `tolerance_pct` · `shape` (loop | out_and_back | any) · `start_address` | `use_my_location` · `avoid_places` · `amenities` (restroom | water @ mile) · `start_date`, `start_time` · `mode` (training | exploring) · `lights` (waits | zigzags) · `crowds` (avoid | some | dont_mind) · `scenery` (park_or_water | some | dont_mind) · `surface` (paths | any) · `turns` · `familiar` (favor | some | new)

New: `start_place`, `end_place`, `via_places` (place refs: places like `place:"Penn Station"`, saved places like `saved:home`, and geocoded addresses like `address:"11 Madison Ave"`, each with its borough) · `hills` (avoid | dont_mind) · `reuse_route_id`, `reverse` · `planned` (a second run, D6). `distance_mi` is optional when the start, via and end define the route (R10).

---

## Rules
**Parsing**
- **R1. Claude extracts, code expands.** Claude returns what the runner said plus a mode. Code fills in the presets and defaults, and writes every chip, question and can't-do line from templates. Claude never writes text the runner sees, except place names it echoes back.
- **R2. Hard limits are never guessed.** Distance comes from the request, the usual distance or the route's places. The start comes from the request, location, a saved place or a question.
- **R3. At most one question,** only for a missing, ambiguous or impossible hard limit or place. It can come from the parser, the place lookup or the engine, and it carries up to 4 tap options. Preferences never trigger a question.
- **R4. Unsupported asks are kept** as `cant` lines. Caveats go in `note`.
- **R5. Times** (D4): no time means now. "Morning" means the usual time (07:00), lunch 12:00, after work 18:30, tonight 20:00, all labeled default. "In 30" means now plus 30 min (said). A day with no hour gets the usual time. Times resolve to the next occurrence.
- **R6. Effort words set nothing** (easy, chill, recovery, quick). Exception: "long run" with no distance asks, because the usual distance is wrong for a long run. Workout words (tempo, intervals, 4xmile, race pace) set `mode=training`. Sightseeing words (scenic, showing someone around) set `mode=exploring`. Novelty words (new, different, haven't tried) set `familiar=new`. "New to this area" sets `mode=exploring`.
- **R7. Distance limits** (D5): 0.5–30 mi. Outside them, ask and offer the likely typo.
- **R8. Health mentions** shape this request only. They're never saved to a profile or a saved route, and never repeated back. Raw request logs (`llm_calls`) are private, never in git, and deleted after 30 days (decision 025).
- **R9. The parser doesn't know geography.** Whether a route is feasible (too far, closed, gapped) is the engine's call, and the engine may ask.
- **R10. "Loop"** (D1): plain "loop" means `shape=any`. "Real loop", "circle" or "no out and back" means `loop`. Out-and-back words mean `out_and_back`. When the start, via and end define the route, distance may be left out.
- **R11. "No lights", "uninterrupted" and "hate waiting at lights"** mean `lights=waits`. `zigzags` only when said.

**Places** (D2, D3)
- **R12. Lookup, never invention.** Claude normalizes the name ("penn" → "Penn Station"). The places table (built from our OSM extract) resolves it. One match: use it, trust listed. Several: pick by borough (R19), otherwise ask with the options. None: ask for an address. Claude never outputs coordinates.
- **R13. "The park"** means the nearest major park within about 1 mi, shown on the chip. If there's none, ask "Which park?" (Code proposes the major-park list.)
- **R14. Subjective picks** ("best Italian spot", "a good coffee place") ask for the specific place. Loop doesn't rank businesses.
- **R15. Streets in avoids** mean don't run *along* them. Crossing is allowed.
- **R16. Start default:** a run today starts from the current location. A later day starts from `saved:home`, otherwise ask. Location off or outside NYC: `saved:home`, otherwise ask. "From home" or "from the office" means that saved place, otherwise ask.
- **R19. Same name or address in several boroughs** (decision 026; replaces decision 005's "always ask"), for addresses and place names alike:
  1. Prefer the match in the reference borough: the runner's current borough for a start today, the saved start's borough for a later day, the route's start borough for an end or via point.
  2. Otherwise, the nearest match within 3 km when the others are farther.
  3. Otherwise, ask.

  The chip always names the borough.
- **R20. Around or through** (decision 035). Claude records the runner's word for each via (`word`); code sets the mode. "Around", "loop of" and "lap of" mean a full lap (`mode=around`). "Through", "in", "along" and "past" mean `through`. A known running loop named on its own means its lap: the Reservoir ("Central park reservor") and each loop's own name ("the Prospect Park loop", "McCarren track"). Anything else is `through`. An around via with no distance said sets no distance, not the usual one: the lap and the way there set it. A lap Loop can't run (McCarren's track) or a place with no loop to run (a street) is passed instead, with a can't-do line (`gap: "lap"`).

**Past routes and planned runs**
- **R17. Past routes come only from the recent-routes list.** Match by date or name. Several matches: ask. None: say so. "My usual" means the most-run route, rebuilt for now. Without one, it means usual distance plus `familiar=favor`.
- **R18. Two runs in one request** (D6): build the soonest now. The other comes back as `planned`, built for its own day and saved.

---

## Cases
IDs keep their draft numbers. R = real phrasing, H = past-route phrasing Jared endorsed.

### A. Bare and vague
**P01** · C1 · `run`
PARSE · `distance_mi=3.1 (usual)` · `use_my_location (default)` · `start_time=now (default)` · `shape=any (default)`
Must not: ask.

**P04** · C1 · `kip bay 3 mi`
PARSE · `distance_mi=3 (said)` · `use_my_location (said: Kips Bay; you're in Kips Bay)`
Must not: send "kip bay" to the lookup as a start address.

**R05** · C2 · `New to this area and want to find a good route - what do you suggest` *(Jared)*
PARSE · `mode=exploring (said)` · `distance_mi=3.1 (usual)` · `use_my_location (default)`
Must not: ask, or reply to "what do you suggest" with text. The routes are the answer.

**R06** · C3 · same text as R05 *(Jared)*
ASK (distance, parser) · "How far?" · options `3 mi · 5 mi · 10 mi` · keep `mode=exploring`, `use_my_location`
Must not: use a default distance.

### B. Distance and units
**P05** · C1 · `3 mi loop`
PARSE · `distance_mi=3 (said)` · `shape=any (said "loop", R10)`

**P09** · C1 · `half marathon training, 13 today`
PARSE · `distance_mi=13 (said)`
Must not: round to 13.11, or set `mode=training` from "training".

**P10** · C1 · `3-4 miles`
PARSE · `distance_mi=3.5 (said)` · `tolerance_pct≈14.3 (said)`

**P11** · C1 · `45 min run`
ASK (distance, parser) · "About how many miles is 45 minutes for you?" · allow_text
Must not: assume a pace.

### C. Time
**R04** · C1 · `Heading out for a run in 30 - thinking 5 miles, low pedestrian areas` *(Jared)*
PARSE · `start_time=07:10 (said)` · `distance_mi=5 (said)` · `crowds=avoid (said)` · `use_my_location (default)`
note: crowds near schools and ferry landings are estimated for 07:10; other path stretches aren't scored.

**P14** · C1 · `4 mi tonight, somewhere well lit, running alone`
PARSE + CANT · `start_time=20:00 (default: tonight)` · `distance_mi=4 (said)` · `cant: street lighting and safety (G9)`
Must not: describe a route as well lit or safe.

**P24** · C1 · `leaving 7:45, steer clear of schools at drop off`
PARSE · `start_time=07:45 (said)` · `crowds=avoid (said)`
note: school drop-off crowds are estimated (crowd pulses, decision 022).
Must not: add a can't-do line. This is covered now.

### D. Start, end and places
**R01** · C1 · `Today, we're doing 8 miles on the water, ending at McCarren Park` *(R2)* · [lookup] [engine]
PARSE · `distance_mi=8 (said)` · `scenery=park_or_water (said)` · `end_place=place:"McCarren Park" (said)` · `use_my_location (default)` · `start_date=today (said)`

**R02** · C1 · `Central park reservor, starting at 86th st and ending at central park south` *(Jared)* · [lookup]
ASK (start, places) · "Which 86th St?" · options `East side (5th Ave) · West side (Central Park West)` · keep `via_places=[place:"Central Park Reservoir", around]`, `end_place=place:"Central Park South"`
Must not: ask for a distance (R10). The Reservoir named on its own is its running track (R20); end to end, the route is a full Reservoir lap between 86th St (west) and Central Park South.

**R03** · C1 · `Chill run on the west side highway, 3 easy miles` *(Jared)* · [lookup] [engine]
PARSE · `distance_mi=3 (said)` · `via_places=[place:"Hudson River Greenway"] (said)` · `use_my_location (default)`
Must not: set a mode from "chill" or "easy". End-to-end, the engine asks (the greenway is far for 3 mi from Kips Bay).

**R10** · C1 · `5 miles, finishing at the best italian spot you can find` *(Jared)*
ASK (end, parser) · "Which spot should it finish at?" · allow_text · keep `distance_mi=5`
Must not: pick a restaurant (R14).

**P15** · C1 · `lunch run from the office 3mi`
ASK (start, parser) · "What's the office's address?" · keep `start_time=12:00 (default)`, `distance_mi=3`

**P16** · C1 · `5 mi from 11 madison ave` · [lookup]
PARSE · `start_place=address:"11 Madison Ave" (Manhattan, said)` · `distance_mi=5 (said)`
The runner is in Manhattan, so R19 picks the Manhattan address. The chip names the borough.

**P17** · C1 · `start at 1st and 23rd, 4 mi` · [lookup]
PARSE · `start_place=place:"1st Ave & E 23rd St" (said)` · `distance_mi=4 (said)`
If the lookup finds the same crossing in several boroughs, ASK (start, places) also passes.

**P18** · C1 · `6 from penn station` · [lookup]
PARSE · `start_place=place:"Penn Station" (said)` · `distance_mi=6 (said)`

**P19** · C1 · `5 mi from hoboken path` · [lookup]
ASK (start, places) · "Loop only covers New York City. Where should it start?"
Must not: start in New Jersey.

**P20** · C1 · `start at the park, 3 mi`
ASK (start, places) · "Which park?" with the nearest parks as options (no major park within about 1 mi of Kips Bay, R13)

**P46** · C1 · `run to work, 5 mi, office is 120 broadway` · [lookup]
PARSE · `end_place=address:"120 Broadway" (Manhattan, said)` · `distance_mi=5 (said)` · `use_my_location (default)`
The route starts in Manhattan, so R19 picks the Manhattan address. The chip names the borough.

**P50** · C2 · `Loop of Prospect Park from Grand Army Plaza` *(Jared, 2026-11-09)* · [lookup] [engine]
PARSE · `start_place=place:"Grand Army Plaza" (Brooklyn, said)` · `via_places=[place:"Prospect Park", around] (said)` · `scenery=park_or_water (said)`
Must not: use the usual 3.1 mi; the lap sets the length (R20). End to end, a full lap of the Prospect Park drive and back to the plaza.

### E. Avoid
**R07** · C1 · `I want to head out for a run, please avoid the chaos of 42nd st` *(Jared)* · [lookup] [engine]
PARSE · `avoid_places=["42nd St" (along)] (said)` · `crowds=avoid (said)` · `distance_mi=3.1 (usual)` · `use_my_location (default)`
Must not: block crossing 42nd St (R15).

**P23** · C1 · `6 miles, avoid 1st ave by the hospitals` · [engine]
PARSE · `distance_mi=6 (said)` · `avoid_places=[1st Ave (along), a stretch inside E 23rd–E 34th St] (said)`
Must not: avoid all of 1st Ave. Loosened 2026-11-08: where the hospital stretch starts is a judgment (the VA is at E 23rd–25th St, Bellevue from E 26th).

**P25** · C1 · `5mi no bike lanes`
PARSE + CANT · `distance_mi=5 (said)` · `cant: avoiding bike lanes`
Becomes PARSE with a field if Code finds the bike-lane rule has landed.

**P27** · C1 · `something new, so sick of the east river`
PARSE + CANT · `familiar=new (said)` · `cant: steering away from the East River path without banning it (G3)`
Must not: add the East River path to `avoid_places`.

### F. Preferences
**P28** · C1 · `no lights if possible, i'll stop if i have to`
PARSE · `lights=waits (said)`

**P29** · C1 · `i dont stop for lights, i just zig zag. 5`
PARSE · `lights=zigzags (said)` · `distance_mi=5 (said)`

**P31** · C1 · `crowds dont bother me, just want water views`
PARSE · `crowds=dont_mind (said)` · `scenery=park_or_water (said)`

**P32** · C1 · `soft surface pls, knees r sore. 4`
PARSE · `surface=paths (said)` · `distance_mi=4 (said)`
Must not: store or repeat the knee detail.

**P33** · C1 · `6mi flat` · [engine]
PARSE · `distance_mi=6 (said)` · `hills=avoid (said)`

**P34** · C1 · `6, need a bathroom around mile 3`
PARSE · `distance_mi=6 (said)` · `amenities=[restroom @ 3] (said)`

**P35** · C1 · `8 miles, need water halfway`
PARSE · `distance_mi=8 (said)` · `amenities=[water @ 4] (said)`
note: fountains are listed only (2024 data, no seasonal status), and many may be off in November.

### G. Training, Exploring and novelty
**P36** · C1 · `tempo 6, need long stretches w no lights`
PARSE · `mode=training (said)` · `distance_mi=6 (said)` · `lights=waits (said)`

**P38** · C1 · `5k at race pace, needs to be uninterrupted`
PARSE · `mode=training (said)` · `distance_mi=3.11 (said)` · `lights=waits (said)`

**R11** · C1 · `4xmile workout - avoid hills` *(Jared)* · [engine]
ASK (distance, parser) · "How far in total, warm-up and cool-down included?" · options `6 mi · 7 mi · 8 mi` · keep `mode=training`, `hills=avoid` · `cant: routes built around workout segments (G8)`

**R08** · C1 · `Create a route that is new from everything else I have tried` *(Jared)*
PARSE · `familiar=new (said)` · `distance_mi=3.1 (usual)`
Must not: also set `mode` (R6).

**R09** · C2 · `Long run today - I want to get a few miles in the park` *(Jared)* · [lookup]
ASK (distance, parser) · "How far today?" · options `6 mi · 8 mi · 10 mi` · keep `via_places=[place:"Prospect Park"] (said "the park", R13)`, `scenery=park_or_water`
Must not: use the usual 3.1 mi (R6).

**P39** · C1 · `scenic 7 miler, showing a friend around, bridges would be cool`
PARSE + CANT · `mode=exploring (said)` · `distance_mi=7 (said)` · `cant: preferring bridges in general (G1)`

### H. Past routes
**H01** · C1 · `same as Tuesday`
PARSE · `reuse_route_id=rt_a (said)`, rebuilt for now
Must not: take today (also a Tuesday) as the one meant.

**H02** · C1 · `my usual but longer`
ASK (distance, parser) · "How much longer?" · options `+1 mi · +2 mi` · keep `reuse_route_id=rt_a (usual)`

**H03** · C1 · `the river one, other direction`
PARSE · `reuse_route_id=rt_a (said)` · `reverse=true (said)`

**H04** · C1 · `last week's route but skip the ferry part`
ASK (reuse, parser) · "Which one?" · options `Tue · East River esplanade out-and-back · Thu · Gramercy street rectangle` · keep `avoid_places=["E 34th St ferry landing"]`

**H05** · C1 · `my usual` *(Jared)*
PARSE · `reuse_route_id=rt_a (usual)`, rebuilt for now

### I. Multi-part and contradictory
**P42** · C1 · `out and back loop 5mi`
PARSE · `shape=out_and_back (said)` · `distance_mi=5 (said)`

**P44** · C1 · `no lights but i wanna take 2nd ave the whole way`
PARSE + CANT · `lights=waits (said)` · `cant: staying on one street the whole way (G1)`

**P45** · C1 · `5k tonight and a 10 miler sat`
PARSE · `distance_mi=3.11 (said)` · `start_time=20:00 (default)` · `use_my_location (default)` · `planned={distance_mi=10, start_date=2026-11-07, start_time=07:00 (usual), start_place=saved:home (default)}`

### J. Impossible and feasibility
**P47** · C1 · `100 mile loop`
ASK (distance, parser) · "Did you mean 10 miles?" · options `10 mi`, allow_text

**P48** · C1 · `0.3 mi loop`
ASK (distance, parser) · "Loop builds runs from 0.5 mi. Make it 0.5 mi?" · options `0.5 mi`, allow_text

**P49** · C1 · `15 miles staying on the east river path the whole time` · [engine]
PARSE + CANT · `distance_mi=15 (said)` · `surface=paths (said)` · `via_places=[place:"East River Greenway"]` · `cant: staying on one path the whole way (G1)`

---

## Coverage
| Category | Cases | Asks | Real or endorsed |
|---|---|---|---|
| A. Bare and vague | 4 | 1 | 2 |
| B. Distance and units | 4 | 1 | 0 |
| C. Time | 3 | 0 | 1 |
| D. Start, end and places | 12 | 5 | 4 |
| E. Avoid | 4 | 0 | 1 |
| F. Preferences | 7 | 0 | 0 |
| G. Training, Exploring and novelty | 6 | 2 | 3 |
| H. Past routes | 5 | 2 | 5 |
| I. Multi-part and contradictory | 3 | 0 | 0 |
| J. Impossible and feasibility | 3 | 2 | 0 |
| **Total** | **51** | **13** | **16** |

The set was capped at 50; P50 joined as the 51st at Jared's request (2026-11-09, decision 035). Each diary phrasing replaces the synthetic case closest to it.

Cut from the draft: P02, P03, P06, P07, P08, P12, P13, P21, P22, P26, P30, P37, P40, P41 and P43. Each was covered by a real phrasing or another case, or was changed by a decision.

## Grading
A case passes when:
1. The outcome matches (PARSE, PARSE + CANT, ASK).
2. Every listed field matches: distance within 0.05 mi, times to the minute, and the chip source matches.
3. No unlisted field is set beyond code-filled defaults.
4. Every `cant` and `note` listed is present, matched by gap id or note key, not by wording.
5. For an ASK: exactly one question; `about` and `from` match; the options match where listed; no routing call is made.
6. No "must not" is violated. Any violation fails the case.
7. Every text the runner sees comes from the templates (R1).
8. Spans (2026-11-09): every chip whose source is `said` has a span, the request's own words at its positions; every other chip has `span: null`; and the question's `chip_id` is a chip in the event, or null.
9. Via modes (2026-11-09, R20): each listed via has the listed `mode`, `through` when none is listed.

Cases marked [lookup] run against the places table. Cases marked [engine] also have an end-to-end check in Phase 3's route evals.

---

## Gaps
| ID | Gap | Status |
|---|---|---|
| G1 | Run along or through a named place | **Phase 3** (`via_places`). "The whole way" stays can't do; so does preferring bridges in general |
| G2 | A specific past run | **Phase 3**, routes saved in Loop only |
| G3 | Something new; soft avoid | `familiar=new` exists. Soft avoid stays can't do |
| G4 | Distance range | Exists (`tolerance_pct`) |
| G5 | Minutes instead of miles | Can't do (no pace). Asks for miles |
| G6 | Ending somewhere else (A to B) | **Phase 3** (`end_place`) |
| G7 | Flat or hilly | **Phase 3** (`hills`) |
| G8 | Routes built for workout segments | Can't do. Roadmap |
| G9 | Lighting and safety | Can't do |
| G10 | Timed avoids | Mostly covered by crowd pulses (schools, ferries, decision 022) |
| G11 | Two runs in one request | **Phase 3** (`planned`) |

## Decisions applied (2026-11-05, borough rule 2026-11-06)
D1: "loop" means any route back to the start. D2/D3: places and intersections come from the OSM places table, and anything unclear gets a question. D4: default hours as proposed. D5: 0.5–30 mi. D6: build both runs and save the later one. Also: the start defaults to the current location; `lights=waits` for "no lights"; `hills`, `via_places`, `end_place`, past routes and minimal storage are in Phase 3. Borough rule (2026-11-06): R19; P16 and P46 now PARSE.
