# 059: The crowd line names its cause, and every trust word explains itself on tap

**Status:** accepted (2026-11-16). Server half in this note's PR; app half in the iOS PR that follows. No ranking weight,
prompt or generator changed; the 30 pinned top-3 rows are unchanged.

## Context
Decision 022 gives every path sample inside a ferry or school window a `high` level with the cause as its `basis`
("SeaStreak arrival 08:00 at East 35th St (window -2/+8 min assumed, estimate)"). The app's card never said why: its
crowd line read only each stretch's level ("Busier on the esplanade around 8."). Checking the demo's routes on
2026-11-16 (Kips Bay Library stand-in, Tuesday 2026-11-17, 7:00 and 8:00) found a second problem: the #1 route's
esplanade is one 3,360 m stretch, and the SeaStreak 08:00 arrival, the UNIS school arrival (twice) and the NYC Ferry
08:24 arrival together cover about 400 m of it, so the stretch's majority level is `not_scored` and the card shows no
crowd line at all, at either hour. The pulses were in the route's busy share (9.1%) but nowhere the runner could read.

Parsing the `basis` prose in the app was the alternative. It would have worked only where a stretch is mostly pulse
(the #2 route at 7:00), and the landing names come in two spellings ("East 34th Street", "East 35th St").

## Decision
1. **`Window` carries the cause in parts** (`api/pulses.py`): `cause` (`ferry` or `school`), `name` (the operator or
   the school), `place` (the landing, ferries only), `arrival` (the clock, ferries only), `event` (`arrival` or
   `dismissal`, schools only). `basis` is unchanged and still names each stretch.
2. **`route_crowds` returns `pulses`** (`api/crowds.py`): one entry per window the route meets, in route order, with
   the parts above, `from_mile` and `to_mile` (first and last sample met, so an out-and-back lists a school once),
   `meters`, `at` (the clock when the run first meets it, at the engine's assumed 10 min/mi), `status: estimate` and
   the window's prose as `source`. It travels on `ContextScores.crowd_pulses` to **`summary.crowds.pulses`**
   (`api/summary.py`): empty when none are met, absent when crowds aren't scored. Additive; nothing else in the stream
   moves. Contract: `docs/phase3/parse-contract-v1.md`.
3. **The app's crowd line is written from the first pulse** (`CardText.crowdSentence`, iOS PR): "≈ Busy near the
   E 34th St ferry around 8:05." for a ferry, "≈ Busy near a school at drop-off around 8:11." for a school arrival
   (pick-up for a dismissal), with the clock from `at`. With no pulse the line falls back to the stretch sentence it
   showed before, and shows nothing when no stretch is moderate or busy. The "≈" is the estimate mark; the trust word
   and source stay one tap away, as for every number (UI review, 2026-11-09).
4. **All five trust words get a one-line description on tap** (iOS PR): measured, estimate, listed, verified ("checked
   on the ground by a runner"), not scored. The app had no words for `verified`; it would have shown the bare word.
   Today nothing on the server writes `verified` into the stream (the verified NYU Langone driveway closure, decision
   017, steers routing and is never a fact or note), but the contract allows it on `place.trust`, so the app handles it.

## Consequences
- From the Kips Bay Library stand-in the top 3 and their order are the same at 7:00 and 8:00 (decision 022 recorded
  this: Kips Bay kept its #1; only Upper East Side 3 mi and Williamsburg 4 mi flipped). The demo's 7→8 beat is
  dropped from this start (Jared, 2026-11-16); the card at 8:00 now says why the esplanade is busier instead.
- Clients that don't read `pulses` see no change.
