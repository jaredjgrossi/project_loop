# 062: "I ran it" from the return prompt rates in place, then goes to the profile

**Status:** accepted (2026-11-17). Found in the demo cut (decision 060, segment F).

## Context
The return prompt sits at the top of the home sheet: "Did you run the East River out-and-back route this morning?",
Not today, I ran it. Until now "I ran it" opened the route (the map panned, the route drew in pencil and ink, the
card appeared with its distance counting up) and only then turned the card into "How was it?". After "Good" the
card came back. Between the prompt and the rating the runner watched about four seconds of a route they had just
run, and after the rating they were left on a card with nothing left to do on it.

## Decision
1. **"I ran it" on the prompt marks the run and turns the home sheet into "How was it?" where it stands.** The
   route is not drawn first: the runner knows which route it was, the prompt names it and shows its shape, and
   the rating repeats the name and distance. The sheet fits the rating the way the route card does
   (`RatingState.fromPrompt`; `LandingSheet` hosts `RatingContent`).
2. **A rating goes on to the You sheet.** After Good, or Done after "Not for me", the profile opens: the run is now
   at the top of History and in this week's miles, which is where the runner would look next. "Not now" leaves the
   run marked and brings the home sheet back.
3. **A rating from the route card is unchanged:** the card comes back, as before.

`openRoute` no longer takes a completion (`afterSettle` is gone): opening a kept route to rate it was its only use.

## Not done
- The demo script's F follows this flow (prompt, rating, You, History) and G stays on the You sheet; the hero map's
  draw-in plays once, when the sheet first appears.
