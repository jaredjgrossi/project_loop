# 009: Routes are ranked against the runner's preferences; GraphHopper stays as the path-finder

**Status:** accepted (Phase 2, 2026-10-30). Refines 008: shape becomes one scored dimension, and rectangles become one candidate generator among several.

## Context
After 008, shape was the whole score. From the Kips Bay review start, two of six loops passed within 14 m of Times Square, one of them ranked 2 with a shape score of 95. No runner would choose that loop. The shape score also has one opinion about turns, while runners don't: one runner waits at a light to keep running straight, another zig-zags with whatever is green. For the zig-zagger, the 13.5 turns-per-mile loop that 008 rejected might be fine.

## Decision

**1. The runner's preferences are the input.** `RunConstraints` (`api/constraints.py`) holds the hard limits (distance, start, shape, no-go places, an amenity at a mile) and the soft preferences:
- lights (waits or zig-zags), crowds, scenery (park and water), surface (paths or streets), turns
- Training vs. Exploring, which is a preset that fills those in. It does not add another dimension.

Claude parses a request into this schema, and the parsed result is shown to the runner so they can correct it (product rule 4). Deterministic code does everything after that.

**2. Every dimension is scored by code, as far as the data allows, and each value says how it was produced.** `measured` means it comes straight from geometry or a dataset: distance, signal count, park share. `estimate` means it comes from a model with assumptions: expected wait at lights, crowding. Estimates are labeled as estimates wherever they appear, and the explanation step may not call one a fact. A dimension with no data yet is reported as `not_scored`. It is never silently treated as zero.

**3. Weights come from the preferences.** For example, turns per mile costs a lot for a runner who waits for lights and nearly nothing for a zig-zagger. On a grid, every staircase between two corners that never doubles back has the same length, so a zig-zagger who turns at each red still runs the planned distance.

**4. Candidates come from several generators, and none of them decides the answer.**
- Generators: grid rectangles (008), round trips, corridor routes (greenways, park drives) and waypoints placed through parks or along water.
- Hard rules reject candidates outright: no-go zones, closures, ferries, the distance limit and ribbons.
- The preference-weighted score ranks what's left. If the best candidate still misses a limit, we say so (product rule 3).

**5. GraphHopper stays the path-finder, with a custom model built per request.** Some factors change which path to take between two points, so they belong inside the router: areas to avoid, the signal penalty, and a preference for greenways. Everything that is a property of the whole route (turns, shape, straight runs, the estimates) is scored over candidates in our code.

## Router test (2026-10-30)
This was run on a temporary GraphHopper 11.1 on port 8999. The config was `routing/config.yml` plus the `crossing` and `orientation` encoded values and foot `turn_costs` with `allow_turn_penalty_in_request`. Without contraction hierarchies, requests can carry their own custom model. Each request took 15–270 ms.

| Test | Result |
|---|---|
| OSM signal data | 104,057 crossing ways; 47,362 tagged `crossing=traffic_signals`. GraphHopper's `crossing` value reads them |
| Signal penalty, Kips Bay → 72nd & York | Signalized crossings 40 → 35 → 21 → 13 at priority ×1, ×0.5, ×0.2, ×0.05; distance 2.60 → 3.43 mi |
| Avoid an area, 3 routes passing Times Square | 11–13 route points inside the polygon by default, 0 with the area at priority 0; costs 0.08–0.16 mi |
| Signal penalty, sidewalk share | 96% footway by default, 98% with signals ×0.1 |
| Turn penalty, Union Sq → Columbus Circle | Turns 26 → 8, but footway share fell from 96% to 24%: the route moved onto road centerlines |

**Why turn penalties fail:** NYC sidewalks are mapped as separate ways, so every street crossing on the sidewalk graph is two 90° turns. A turn penalty therefore prices crossings as turns and pushes the runner into the roadway. That is the 3rd Ave bike-lane problem in another form, and it also hides signals, since a centerline has no crossing way to count. So **turn and straightness preferences are not given to GraphHopper**. They are handled by where candidate waypoints go and by route-level scoring.

**Why not our own routing graph now:** areas, signal penalties and path-type boosts all work per request in GraphHopper, which removes the main reason to switch. Revisit if crowding by time of day, or modeling a zig-zagger's choices at each intersection, needs intersection-level costs a custom model can't express.

## Consequences
- `routing/config.yml` gains the `crossing` encoded value, which needs a re-import. `orientation` and turn costs are not needed.
- Signal counts for scoring come from our own geometry checks against the OSM crossing ways and road signal nodes, not only from GraphHopper's path details. Those details miss signals whenever a route uses a road centerline.
- The share of a route on roadway where a separate sidewalk exists is a new check. It's the general form of the bike-lane rule.
- Review process: a fixed set of test starts is rendered after every change to scoring or generation. Every route the reviewer rejects becomes a failing eval in `evals/routes/`, which stays red until the generator stops producing that route.
