# 052 · Pencil, then ink: how a route arrives

*2026-11-13 · branch `ios-ink-polish`*

## Decision
While Loop is still looking, everything on the map is pencil. When the route settles (the provisional flag, decision 018),
the winner is inked. This replaces the earlier arrival, where the leading route drew in its final colours from the first
moment and the settle was one ring pulse and one light tap.

- **Before the flag:** the candidate lines and the current best are graphite, in the `ink` token, each with a second,
  thinner stroke a hair to one side so it reads as sketched. The current best is heavier than the candidates. No mile
  marks and no turnaround ring yet: nothing is promised.
- **At the flag:** the route's own line (casing, street, path and waterfront styling, as before) sweeps along the pencil
  from the start. The pencil stays under it until the ink is dry, then goes.
- **With the ink:** mile marks and "Turn" land like stamps as the ink passes them, the distance on the card rolls up
  from zero and lands with the last stroke, and the turnaround ring pulses when the ink arrives, not when it starts.
  The direction chevrons (decision 053) come in with the last of the ink; a pencil sketch has none.
- **In the hand:** one Core Haptics pattern for the whole move (a low hum that rises, a tick at each mile, a soft knock
  at the end) in place of the single settle tap.

This is the base version of signature moment D (`signature-moments-v1.md`). It is the app's behaviour, not a setting.

## Choices worth knowing
- **Meaning first.** Pencil means "still deciding", ink means "this is the route". The engine's provisional flag is the
  only thing that turns pencil into ink, so the picture never claims more than the engine does (rule 1: the app draws
  what the engine sent; no geometry or number is made up for the animation).
- **Duration: 0.75 s plus 0.08 s a mile, never more than 1.5 s.** A 3 mile route inks in about a second. The sweep
  eases in and out (smoothstep); mile ticks are timed from the same curve, so a tick lands when the ink reaches that mile.
- **The rolling distance is display only.** It counts up to the route's distance and stops there. An estimated
  distance ("≈") does not roll: it shows as it always did.
- **Stamps only during the ink.** A mark that appears later (a zoom, another of the three routes) just appears.
- **Reduce Motion: none of it moves.** The route is inked whole at the flag, the marks and the distance are simply
  there, and the phone gives the old single tap. Pencil before the flag stays, because it is a state, not a motion.
- **A route that is already settled** (opened from Saved or History, or drawn at launch) is ink from the first frame.
  Switching between the three routes after `final` morphs as before and is not re-inked.
- **A touch before the flag** still cancels the haptic and the ring (decision 018's rule); the ink itself still runs.
- **Night:** graphite is the `ink` token, which is light on the Night map. The old Night-only boost for candidate
  lines is gone; pencil lines are drawn at 1.5 times their faint opacity in both themes.
- **Where it lives:** `ios/Loop/Screen/InkMoment.swift` (timing, the frame change, haptics, the rolling number, the
  stamp), two pencil layers and a second candidate stroke in `RouteMapView.swift`, `RouteFrame.pencil`.

## Not done
- **Tilt, paper grain and sound** (the wildcard, D+). Left out on purpose.
- **No setting to turn it off**, beyond Reduce Motion.
- **The haptic pattern has not been felt.** It was written in the simulator, which has no haptic engine. Its
  strengths and timings are first picks to tune on a phone.
- **Not checked against the live server.** With the bundled demo data the pencil phase lasts about 2.5 seconds. On a
  live build it lasts as long as the search, and a new leader before the flag morphs in pencil; that path is covered
  by unit tests on the frame, not by eye.
