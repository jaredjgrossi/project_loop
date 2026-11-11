# iPhone type audit

Every text element on every screen of the iPhone app, against the design system's twelve type
styles. Sizes are point size / line height; weights are the variable-font `wght` value.

**The twelve styles:** the brief's (`ios-build-brief-v1.md`, "Type styles") without `data` and
`data-strong` (JetBrains Mono left the app in the calm pass), plus `field` (Fraunces 18/24) and
`numeral-s` (Fraunces 18/22) from the UI review. Tracking on numeral-xl (−0.02 em), wordmark
(−0.01 em) and body-strong (0.01 em) comes from the D mockup.

`TypeStyle`'s initializer is private to `Typography.swift`, so a view can only use these twelve
and an off-list size or family doesn't compile. `TypeStyleTests` pins all twelve and checks the
temperature reads quieter than the wordmark.

## History
- **2026-11-09, audit:** seven off-list sizes replaced; the style lock added.
- **2026-11-09, UI review:** `field` and `numeral-s` added for the landing field and the temperature.
- **2026-11-09, calm pass:** JetBrains Mono removed (font file and licence too). Everything that
  used `data` or `data-strong` now uses `label`, mostly in ink-muted. Trust words are hidden by
  default (a tap shows them), the crowd line became one `body` sentence, and the strip legend and
  the "Loop filled in" and source words are gone.

## Every text element

| Screen | Element | Style | Font, size/line, weight, colour |
|---|---|---|---|
| Landing | Wordmark "Loop" | wordmark | Fraunces 22/26, 600, ink |
| Landing | Temperature "48°" | numeral-s | Fraunces 18/22, 400, ink-soft |
| Landing | "· Mon 7:02" | body | Instrument Sans 16/22, 400, ink-muted |
| Landing | Field placeholder, typed text, launch example | field | Fraunces 18/24, 400 |
| Landing | "YOUR RUNS", "RECENT" | eyebrow | Instrument Sans 11.5/14, 600, 0.12 em, capitals |
| Landing | Tile name ("Usual", "3 mi from here"), "Save" | label | Instrument Sans 12.5/16, 500 |
| Landing | Tile distance ("3.0 mi") | label | Instrument Sans 12.5/16, 500, ink-muted |
| Landing | Recent request | body | Instrument Sans 16/22, 400 |
| Landing | Recent day ("Today") | label | Instrument Sans 12.5/16, 500, ink-muted |
| Wait, card | Sentence (and while editing) | request | Fraunces 27/31, 400 |
| Map | START, TURN | map-label | Instrument Sans 11/14, 500, 0.22 em, capitals |
| Map | Mile marks | label | Instrument Sans 12.5/16, 500 (was data) |
| Map | Selected mile | stretch-name | Instrument Sans 12/16, 600 (was data-strong) |
| Map | Selection chip ("East River Esplanade · 1.0 mi · Look around") | label | Instrument Sans 12.5/16, 500 |
| Map | "A better route came in" | label | Instrument Sans 12.5/16, 500 |
| Card | Eyebrow ("TRAINING · BEST OF 31") | eyebrow | Instrument Sans 11.5/14, 600 |
| Card | Distance "3.03" ("≈ 3.03" if an estimate) | numeral-xl | Fraunces 56/56, 380 |
| Card | "mi" | numeral-l | Fraunces 24/26, 400 |
| Card | Trust word beside "mi" | removed | shown on tap instead |
| Card | Reason sentence | body | Instrument Sans 16/22, 400 |
| Card | Can't-do line | label | Instrument Sans 12.5/16, 500 |
| Card | "Send to watch" | body-strong | Instrument Sans 16/22, 600 |
| Card, open | Strip legend | removed | |
| Card, open | Strip mile axis ("0", "1", "turn") | label | Instrument Sans 12.5/16, 500, ink-muted (was data) |
| Card, open | Stat values ("3.6", "51%", "≈ 8 m") | numeral-l | Fraunces 24/26, 400 |
| Card, open | Stat labels ("lights a mile") | label | Instrument Sans 12.5/16, 500, ink-soft |
| Card, open | Stat trust words | removed | shown on tap instead |
| Card, open | Crowd sentence ("Busier on E 31st St around 7."), only when moderate or busy | body | Instrument Sans 16/22, 400, ink-soft (was data, two lines) |
| Trust popover | Trust word ("Estimate") | label | Instrument Sans 12.5/16, 500, ink |
| Trust popover | Source (the file's own words) | label | Instrument Sans 12.5/16, 500, ink-muted |
| How Loop read it | "HOW LOOP READ IT" | eyebrow | Instrument Sans 11.5/14, 600 |
| How Loop read it | Can't-do lines | body | Instrument Sans 16/22, 400 |
| How Loop read it | "Loop filled in" heading, source words | removed | |
| How Loop read it | Filled-in rows ("Training: fewer lights, crowds and turns") | body | Instrument Sans 16/22, 400 |
| How Loop read it | Row detail ("Kips Bay Library") | label | Instrument Sans 12.5/16, 500, ink-muted |
| How Loop read it | "Notes" heading | label | Instrument Sans 12.5/16, 500, ink-muted (was data) |
| How Loop read it | Note text (trust word on tap) | label | Instrument Sans 12.5/16, 500, ink-soft (was data) |
| Chip editor | Title ("DISTANCE · YOU SAID") | eyebrow | Instrument Sans 11.5/14, 600 |
| Chip editor | Stepper value ("3 mi") | numeral-l | Fraunces 24/26, 400 |
| Chip editor | Options | label | Instrument Sans 12.5/16, 500 |
| Chip editor | Start note | body + label | Instrument Sans 16/22 and 12.5/16 (was body + data) |
| Chip editor | "Cancel" / "Done" | body / body-strong | Instrument Sans 16/22, 400 / 600 |
| Look Around | Title ("East River Esplanade · 1.0 mi") | label | Instrument Sans 12.5/16, 500 |
| Look Around | "Apple Look Around imagery" | label | Instrument Sans 12.5/16, 500, ink-muted (was data) |
| Errors | "Couldn't read the saved route", "Details for this route aren't in the saved file." | body, label | Instrument Sans |
| Debug only | "Replay build" | label | Instrument Sans 12.5/16, 500 (was data) |

Not ours, left as they are: Mapbox's logo and attribution (hidden while the sheet is expanded past
its open state), Apple's own Look Around controls, and the system keyboard.

Icons, not text: SF Symbols for the magnifier, preferences, close (×), plus, chevron, checkmark,
binoculars and the weather glyph.

No system-font text anywhere. The question screen (one question with tap options) isn't built yet.
