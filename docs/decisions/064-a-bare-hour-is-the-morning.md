# 064: A bare hour is the morning

**Status:** accepted (2026-11-23). Fixes issue #32, found in milestone 2. Builds on decision 020 (a said clock time
is the next time it comes round) and decision 028 (the model extracts, code decides).

## The bug
"3 miles by the water at 7", typed at 07:02, built for 19:00. The prompt asks the model to read am or pm "from the
words and the current time", and once the clock is past seven, the next seven is tonight. A runner typing "at 7" a
few minutes after seven in the morning means this morning.

## Decision
When the request gives a clock hour with **no am, pm or time-of-day word** anywhere in it ("at 7", "7ish", "7:30",
"at seven"; not "7am", "at 7 tonight", "7 this morning"), code decides what the hour means, whatever the model
returned (`bare_hour` and `_bare_morning` in `api/parse.py`):

- **A bare 4 to 11 is the morning.** Typed before noon, it is this morning, even when that time passed in the last
  60 minutes ("at 7" at 07:40 is 07:00 today). Further past than that, it is tonight ("at 7" at 11:30 is 19:00).
  Typed from noon on, it is the next time the clock reads it, as before (at 14:00, "at 7" is 19:00; at 20:00 it is
  07:00 tomorrow). With a said day ("at 7 tomorrow"), it is the morning of that day.
- **A bare 12, 1, 2 or 3 is unchanged:** the next time the clock reads it ("at 3" in the morning is 15:00; "at 12"
  is noon). Runs at one, two or three in the morning are rare enough that a question would cost more than it saves,
  and 12 is almost always noon.
- The rule lives in code, not the prompt: `parse_v7` is untouched, the model's clock is used only to confirm it read
  the same hour, and the day it implies is overridden. `start_time` keeps its source `said`; `start_date` is
  `default` unless a day was said.

## What it is not
- Not a question. Issue #32 suggested asking; a bare morning hour is unambiguous enough that asking every time
  would be noise.
- Not a change to said times ("7 pm", "7 in the morning", "tonight at 7") or to "in 30".

## Evals
Context C4 (C1 at 07:02) and cases P63–P66 in `evals/parse/cases/`: the issue's request, the same with "pm", a bare
hour on a said day, and a bare 3. Unit tests in `api/tests/test_parse.py` cover the clocks the live contexts can't
(07:40, 11:30, 14:00, 20:00) and both extractions the model might return (07:00 or 19:00). The pinned top 3 are
not touched: no request in `evals/routes` carries a bare hour.
