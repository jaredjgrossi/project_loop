# 060: Demo mode, a self-playing script behind the Debug flag

**Status:** accepted (2026-11-16). Milestone 2 of the Phase 4 plan, part C; the demo brief's step 2 (`loop-design/planning/brief-v1.md`). Debug builds only; nothing in this note ships.

## Context
The demo video is one screen recording of the real app on a real iPhone, about 52 seconds, showing the range of what
Loop does. A finger-driven recording can't hit the brief's timings, shows no touches, and risks something personal
on screen. The brief asked for a demo mode that plays the sequence by itself from staged state at a public start,
with the routes, numbers and copy coming from the live engine.

## Decision
1. **Everything lives in `ios/Loop/Demo/` under `#if DEBUG`,** plus small hooks in the views. On with
   `-LoopDemoMode [A-G]` (from the Mac) or a two-second press on the wordmark, which arms it for the next launch
   (the hidden trigger on the phone). With neither, the app behaves exactly as before. The Release build has no
   demo code: checked by `strings` on the Release binary (zero matches for the demo's type names, launch arguments,
   file names and copy; the only "demo" the binary knows is Mapbox's `MapCenterAltitudeMode` and the pre-existing
   `demoTyping` field name).
2. **The script (`DemoDriver`) plays segments A to G** (the 2026-11-17 cut; see the sequence below). Every wait is
   tied to the thing it waits for (the parse, the card, the final, the landing, a view's frame), never a fixed
   sleep; the holds run as long as a screen takes to read (`readCard`, `readSheet`, `readQuestion`), and the edit
   decides the cut. Starting at a later segment plays the earlier ones first with holds skipped, then holds two
   seconds still. Taps are marked with a
   soft dot (`TapDots`: a 44 pt disc in the action blue at 16%, a 1.5 pt ring at 45%, 500 ms); where a tap lands
   comes from the view itself, registered by name (`.demoTarget`), so the dot follows layout.
3. **The clock is the app's own, pinned.** `LoopClock.now()` replaces every `Date()` that reaches the server
   (`client.now`), a date label, the weather line or the return prompt. Demo mode pins it to Tuesday 2026-11-17
   (a school day) at 6:52; it ticks on from there (9:40 for the return prompt, while the script had one). 6:52, not the brief's
   7:02: "at 7" after seven in the morning parses as 7 pm (decision 020; issue #32). In Release `LoopClock.now()`
   is `Date()`.
4. **Staged, so the post can say so:** the clock; the location (the Kips Bay Library stand-in, `LocationProvider.
   simulate`, Core Location never asked); the weather reading (46°, cloud and sun, fresh on the pinned clock); the
   sample history (`DemoSampleRuns`: 14 runs, about 48 miles, four weeks, two named saved routes, three recents, in
   the demo's own `demo-runs.json`, never the real store), every run a real engine route built from a public start on
   2026-11-16 and simplified to 8 m); the
   opening drift (3 s over the grid at zoom 15.35); the hero map's draw-in (added: the profile's hero map didn't
   animate, so in demo mode the runs appear oldest first over about two seconds). Also forced: the Paper theme, a
   hidden status bar, no "Replay build" control.
5. **Not staged:** the requests' routes, names, distances, reason lines, crowd lines, the rebuild for 8 am in B, the
   two laps in C and D, the engine's question in D, and every number on the profile in E.

## The sequence as built (2026-11-17)
Every request is typed with "7am", not "7". A `3 miles by the water at 7am` from the library: the real open, the drift,
the bar rises and types at real speed, the build, the collapsed card, then the sheet opens on the three stats and the
crowd line (the 7:06 ferry) · B a tap on the route at a mile on the esplanade (the mile chip), routes #2 and #3, back
to #1, the bookmark · C tap the sentence, tap "at 7am", four taps on + (7 → 8 am), Done; the rebuild for 8 am; the
sheet opens on the new crowd line (the 8:05 ferry) · D home, the location moves to 5th Ave & E 86th St, `a lap of the
Reservoir at 7am`, the build, the card · E home, the location moves to Grand Army Plaza, `3 miles around Prospect
Park at 7am`; the engine asks for the lap and the way there (decision 061's number) and the script taps the answer;
the build, the card · F 9:40, back at the library: the return prompt for A's route, "I ran it" (the app draws the
route and opens its card into the rating, its own flow), "Good", the run at the top of History · G You: hero,
numbers, 8 weeks, hero. F runs before G so the profile's numbers and hero map include A's run. No hold has a fixed
length for the cut's sake: each runs as long as its screen takes to read, and the edit decides.

Dropped on 2026-11-16: Union Square and the Hudson. The eyebrow shows the pool again ("1 OF 3 · BEST OF 35", PR #52)
so the first card proves decision 020's Best of N. The time editor writes the new time the way it was typed
("at 8am", PR #54), so C's header matches A's.

Starts are a short list of named public places (`DemoMode.starts`: the library, 5th Ave & E 86th St, Grand Army
Plaza), each with the opening drift's camera points derived from it. The sample history and the Home default stay at
the library whatever the segment's start. A question card's first option is a tap target, so a segment can answer;
the time editor's + is one, so a segment can move 7 am to 8 am; a phrase of the header's sentence is found by
measuring the words with the request type style (`phrasePoint`).

## Also in this change
- `MainModel.outsideCoverageName` read a Debug-only property outside `#if DEBUG`, so the Release configuration did
  not compile at all (issue #39). Split so Release builds; Debug behaviour unchanged.

## Not done
- No capture from the simulator is the deliverable; the test capture and the three takes come from the real phone
  (brief step 3), where the Mapbox map and the ink run at full speed.
- The sample runs' names are Loop's own ("East River out-and-back"); the two saved names ("Long river run",
  "Saturday 4") are placeholders for Jared to change.
