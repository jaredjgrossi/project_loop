# 060: Demo mode, a self-playing script behind the Debug flag

**Status:** accepted (2026-11-16). Milestone 2 of the Phase 4 plan, part C; the demo brief's step 2 (`loop-design/planning/brief-v1.md`). Debug builds only; nothing in this note ships.

## Context
The demo video is one screen recording of the real app on a real iPhone, about 52 seconds, showing the range of what
Loop does. A finger-driven recording can't hit the brief's timings, shows no touches, and risks something personal
on screen. The brief asked for a demo mode that plays the sequence by itself from staged state at a public start,
with the routes, numbers and copy coming from the live engine.

## Decision
1. **Everything lives in `ios/Loop/Demo/` under `#if DEBUG`,** plus small hooks in the views. On with
   `-LoopDemoMode [A-F]` (from the Mac) or a two-second press on the wordmark, which arms it for the next launch
   (the hidden trigger on the phone). With neither, the app behaves exactly as before. The Release build has no
   demo code: checked by `strings` on the Release binary (zero matches for the demo's type names, launch arguments,
   file names and copy; the only "demo" the binary knows is Mapbox's `MapCenterAltitudeMode` and the pre-existing
   `demoTyping` field name).
2. **The script (`DemoDriver`) plays segments A to G** (the brief's A to F with two range beats in place of Union Square), segment B in its fallback form (Look Around out,
   decision 2026-11-14): a second mile on the strip, then routes #2 and #3. Every wait is tied to the thing it waits
   for (the parse, the card, the final, the landing, a view's frame), never a fixed sleep. Starting at a later
   segment plays the earlier ones first with holds skipped, then holds two seconds still. Taps are marked with a
   soft dot (`TapDots`: a 44 pt disc in the action blue at 16%, a 1.5 pt ring at 45%, 500 ms); where a tap lands
   comes from the view itself, registered by name (`.demoTarget`), so the dot follows layout.
3. **The clock is the app's own, pinned.** `LoopClock.now()` replaces every `Date()` that reaches the server
   (`client.now`), a date label, the weather line or the return prompt. Demo mode pins it to Tuesday 2026-11-17
   (a school day) at 6:52 for segments A to D and 9:40 for E and F; it ticks on from there. 6:52, not the brief's
   7:02: "at 7" after seven in the morning parses as 7 pm (decision 020; issue #32). In Release `LoopClock.now()`
   is `Date()`.
4. **Staged, so the post can say so:** the clock; the location (the Kips Bay Library stand-in, `LocationProvider.
   simulate`, Core Location never asked); the weather reading (46°, cloud and sun, fresh on the pinned clock); the
   sample history (`DemoSampleRuns`: 14 runs, about 53 miles, four weeks, two named saved routes, three recents, in
   the demo's own `demo-runs.json`, never the real store), every run a real engine route built from a public start on
   2026-11-16 and simplified to 8 m; segment E's return prompt (the route segment A built, viewed at 7:09); the
   opening drift (3 s over the grid at zoom 15.35); the hero map's draw-in (added: the profile's hero map didn't
   animate, so in demo mode the runs appear oldest first over about two seconds). Also forced: the Paper theme, a
   hidden status bar, no "Replay build" control.
5. **Not staged:** the requests' routes, names, distances, reason lines, crowd lines, the three routes in B, the
   rebuild in C, the Union Square run in D, the History row in E and every number on the profile after E.

## The sequence as built
A `3 miles by the water at 7` from the library · B strip, two miles, #2, #3, bookmark · C edit 3 → 4 (two taps on +,
Done), rebuild, sheet open on the crowd line · D home, the location moves to 5th Ave & E 86th St, `a lap of the
Reservoir at 7`, typed, six seconds · E home, the location moves to Grand Army Plaza, `3 miles around Prospect Park at
7`; the engine asks for 4.3 mi and the script taps the first answer; six seconds · F back at the library, later the
same morning: prompt → I ran it → Good → History · G You: hero, numbers, 8 weeks, hero. (Decided from the casting page
on 2026-11-16: Union Square and the Hudson are out.)

Starts are a short list of named public places (`DemoMode.starts`: the library, 5th Ave & E 86th St, Grand Army
Plaza), each with the opening drift's camera points derived from it. The sample history and the Home default stay at
the library whatever the segment's start. A question card's first option is a tap target, so a segment can answer.

## Also in this change
- `MainModel.outsideCoverageName` read a Debug-only property outside `#if DEBUG`, so the Release configuration did
  not compile at all (issue #39). Split so Release builds; Debug behaviour unchanged.

## Not done
- No capture from the simulator is the deliverable; the test capture and the three takes come from the real phone
  (brief step 3), where the Mapbox map and the ink run at full speed.
- The sample runs' names are Loop's own ("East River out-and-back"); the two saved names ("Long river run",
  "Saturday 4") are placeholders for Jared to change.
