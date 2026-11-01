# Discovery Summary — v1
*Status: interim. 3 runners; 1 direct source and 2 relayed. Update to v2 when direct notes from Runners 1–2 and more runners come in.*

## Sources
| ID | Source type | Profile |
|---|---|---|
| Runner 0 | Direct (founder) | Competitive. Runs most mornings, 3–10 mi. Goal: build speed and endurance. Lives in a Manhattan neighborhood with no nearby park (previously Upper East Side). Tracks with a watch; keeps a running log; no Strava. |
| Runner 1 | Relayed by Runner 0 | Competitive. Lives near Astor Place. Runs at variable times, often at night. Prefers the West Side Highway / Hudson River Greenway. Uses a watch and Strava. |
| Runner 2 | Relayed by Runner 0 | Casual. Lives in Williamsburg. Enjoys waterfront paths and bridges, and doesn't mind pedestrians. Uses a watch and Strava. |

**Evidence caveats:** Runner 0 is the founder, so the strongest source and also the most biased. Runners 1–2 are paraphrased secondhand. Treat every theme below as a hypothesis until direct sources confirm it.

---

## Themes, ranked
| # | Theme | Runners | Strength |
|---|---|---|---|
| 1 | **Good routes depend on the neighborhood.** Park access and path quality vary block by block | 0, 1, 2 | Strong |
| 2 | **Crowds and pedestrian traffic**, especially for competitive runners | 0, 1 (+ general) | Strong |
| 3 | **Timing changes the route:** time of day, school days, day of week | 0, 1 | Medium |
| 4 | **Path gaps and closures:** discontinuous paths, construction, sinkholes | 0 | Medium (1 runner, very specific) |
| 5 | **Seasonal crowding:** marathon season and marathon prep | 0 | Medium |
| 6 | **Stoplights / street crossings** | 0 (general complaint) | Medium |
| 7 | **Bike lanes aren't usable for runners** | 0 (general complaint) | Low–Medium |
| 8 | **Run clubs and structured workouts** | 0, 1, 2 (relayed) | Low (exploratory) |

### 1. Good routes depend on the neighborhood
- On the Upper East Side, Runner 0 had Central Park and a good stretch of the East River, with plenty of options. After moving to a park-poor neighborhood, building a long run "that doesn't involve traffic and hospitals" became really difficult.
- Runner 2 (Williamsburg) finds runs much more enjoyable: waterfront, solid paths, bridges.
- Runner 1 (Astor Place) has to commute to the West Side Highway to get a good run.
- **Implication:** Loop's value is highest where options are worst. Positioning candidate: *"the best run from a neighborhood that doesn't have one."*

### 2. Crowds and pedestrian traffic
- Runners 0 and 1 are competitive, so pedestrians cost them pace. Runner 2 is casual and flexible about it.
- Runner 1 says the West Side Highway is "swarmed and overrun" at certain times, sometimes so badly a run doesn't work at all.
- **Implication:** competitive and casual runners weight factors differently. A simple **"Training vs. Exploring"** mode could change how routes get scored.

### 3. Timing changes the route
- On the Upper East Side, Runner 0 mentally planned around school days (drop-off times, steering away from blocks with schools on the second half of a run) and how busy routes would be.
- Runner 1's best route is only good at certain hours.
- **Implication:** the same route can be great or bad depending on when it's run. Possible data inputs: school locations plus the school calendar, hospital zones, and NYC DOT greenway counters as a rough crowding signal. All need checking.

### 4. Path gaps and closures
- The East River path is a series of short stretches, unlike the continuous West Side Highway path. It has sinkholes and closed sections.
- Runner 0's current options: short segments around the 17th–42nd St stretch, or First Ave north to the 40s, then the path up to about 71st, where it cuts off.
- **Implication:** sending a runner into a closed section breaks trust right away. OpenStreetMap likely won't show temporary closures, so this needs a closures layer: official sources where they exist, plus user reports ("path closed here"). User reports would also be a reason to come back.

### 5. Seasonal crowding
- Central Park in October is hard to enjoy because of marathon training crowds.
- **Implication:** same "timing" theme on a longer timescale. Future feature, not v1.

### 6–7. Stoplights; bike lanes
- These are general NYC complaints. Stoplights are already in the v1 plan. Bike lanes confirm a routing rule: never route runners into bike lanes.

### 8. Run clubs and structured workouts
- All three runners occasionally join run clubs; some clubs have set weekly sessions with prescribed workouts.
- Asked for: tracking runs and workouts to stay on a plan.
- **Implication, split in two:**
  - *Training-plan tracking:* **parking lot.** It's a different product in a crowded space (Strava, Garmin Connect, training-plan apps).
  - *Routes built for a workout:* **keep on the roadmap.** "Find me a mile with no crossings within a mile of home" for tempo or interval work only works because of Loop's crossing data.
  - *Run clubs as a channel:* clubs need group-run routes and are a way to reach users beyond friends.

---

## Tools and habits
- All three track runs with a **watch (Garmin or Apple Watch)**. Runners 1 and 2 use **Strava**; Runner 0 doesn't.
- All three keep **running logs**.
- **Implications:** GPX export is confirmed for v1. A Strava or Garmin connection is a strong later feature. Watch use supports a native iOS app with Apple Watch support later.

## Before vs. during the run
- So far the evidence is almost entirely about **choosing a route before the run**: which route, when and avoiding what.
- Nothing yet shows strong demand for live guidance mid-run.
- **Read:** the web app is enough for v1. Revisit iOS timing once direct sources weigh in. **Ask about this directly.**

---

## Fit with the v1 plan
| Plan item | Discovery says |
|---|---|
| Park/waterfront share | ✅ Confirmed (themes 1, 2) |
| Fewer crossings | ✅ Confirmed (theme 6) |
| Bathrooms and water near mile X | ⚠️ **Not mentioned by anyone yet.** Keep it, but ask directly before investing more |
| GPX export | ✅ Confirmed (watch use) |
| "I ran it" plus a rating | Neutral; fits the running-log habit |
| Building stories / tours (v2) | ⚠️ **Not mentioned.** Possible fit for casual runners (Runner 2); unproven |
| **Missing from the plan** | Timing and crowds (time of day, school days, seasons); path gaps and closures; competitive vs. casual modes; bike-lane rule |

## Suggested plan changes (for review, not applied)
1. **Add a "Training vs. Exploring" preference** that changes scoring weights. Small cost, likely v1.
2. **Add a bike-lane rule** to the GraphHopper foot profile. Small cost, v1.
3. **Add a path-closures layer.** Start with known gaps in the East River path and a "report closed path" button. v1 or v1.5.
4. **Add the timing layer to the roadmap:** time-of-day and school-day avoidance first, seasonal later. Phase 3 or v1.5, after checking the data.
5. **Add workout-friendly routes to the roadmap:** uninterrupted stretches for tempo and intervals. v1.5–v2.
6. **Downgrade bathrooms and water** from a headline v1 feature to a supporting one until runners confirm they care.
7. **Revisit positioning** around park-poor neighborhoods.
8. **Parking lot:** training-plan tracking and compliance.

## Open questions for the next interviews
1. What time do you usually run? Does your route change by time of day, weekday vs. weekend, or season?
2. What do you do when your usual route is too crowded or closed?
3. Have you moved neighborhoods? How long did it take to find good routes?
4. What's the longest run you can do from your door without hating it?
5. Do bathrooms or water ever decide your route? *(Unprompted mentions count for more.)*
6. Would you want help **during** a run, or only for picking the route beforehand?
7. For run club members: how do you find routes for workouts?
