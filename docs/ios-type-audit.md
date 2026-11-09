# iPhone type audit (2026-11-09)

Every text element on every screen of the iPhone app, against the twelve type styles in
`ios-build-brief-v1.md` ("Type styles"). Sizes are point size / line height; weights are the
variable-font `wght` value. Tracking on numeral-xl (−0.02 em), wordmark (−0.01 em) and body-strong
(0.01 em) comes from the D mockup.

Since this audit, `TypeStyle`'s initializer is private to `Typography.swift`: a view can only use
the twelve styles, so an off-list size or family no longer compiles. `TypeStyleTests` pins the
twelve to the brief.

| Screen | Element | Style now | Font, size/line, weight | Before |
|---|---|---|---|---|
| Landing | Wordmark "Loop" | wordmark | Fraunces 22/26, 600 | same |
| Landing | Temperature "48°" | numeral-l | Fraunces 24/26, 400 | off-list: Fraunces 18/22 |
| Landing | "· Mon 7:02" | body | Instrument Sans 16/22, 400, ink-muted | off-list: Instrument Sans 15/20 |
| Landing | Field placeholder, typed text, launch example | numeral-l | Fraunces 24/26, 400 | off-list: Fraunces 20/24 |
| Landing | "YOUR RUNS", "RECENT" | eyebrow | Instrument Sans 11.5/14, 600, 0.12 em, capitals | same |
| Landing | Tile name ("Usual", "3 mi from here") | label | Instrument Sans 12.5/16, 500 | off-list: Instrument Sans 14/18, 500 |
| Landing | Tile distance ("3.0 mi") | label | Instrument Sans 12.5/16, 500 | same |
| Landing | "Save" | label | Instrument Sans 12.5/16, 500 | off-list: Instrument Sans 14/18, 500 |
| Landing | Recent request | body | Instrument Sans 16/22, 400 | same |
| Landing | Recent day ("Today") | label | Instrument Sans 12.5/16, 500 | off-list: Instrument Sans 14/18, 400 |
| Wait, card | Sentence | request | Fraunces 27/31, 400 | same |
| Wait, card | Sentence while editing (text field) | request | Fraunces 27/31, 400 | same |
| Map | START, TURN | map-label | Instrument Sans 11/14, 500, 0.22 em, capitals | same |
| Map | Mile marks | data | JetBrains Mono 11/14, 400 | same |
| Map | Selected mile | data-strong | JetBrains Mono 12/16, 500 | same |
| Map | Selection chip ("East River Esplanade · 1.0 mi · Look around") | label | Instrument Sans 12.5/16, 500 | same |
| Map | "A better route came in" | label | Instrument Sans 12.5/16, 500 | same |
| Card, collapsed | Eyebrow ("TRAINING · BEST OF 31") | eyebrow | Instrument Sans 11.5/14, 600 | same |
| Card, collapsed | Distance "3.03" | numeral-xl | Fraunces 56/56, 380 | same |
| Card, collapsed | "mi" | numeral-l | Fraunces 24/26, 400 | off-list: Fraunces 22/26 (the mockup's size) |
| Card, collapsed | Trust ("measured") | data | JetBrains Mono 11/14, 400 | same |
| Card, collapsed | Reason sentence | body | Instrument Sans 16/22, 400 | same |
| Card, collapsed | Can't-do line ("Street lighting isn't planned yet") | label | Instrument Sans 12.5/16, 500 | off-list: Instrument Sans 13.5/18, 400 |
| Card | "Send to watch" | body-strong | Instrument Sans 16/22, 600 | same |
| Card, open | Profile legend and mile axis | data | JetBrains Mono 11/14, 400 | same |
| Card, open | Stat values ("3.6", "51%", "8 m") | numeral-l | Fraunces 24/26, 400 | same |
| Card, open | Stat labels ("lights a mile") | label | Instrument Sans 12.5/16, 500 | same |
| Card, open | Stat trust ("measured", "estimate") | data | JetBrains Mono 11/14, 400 | same |
| Card, open | Crowd sentence | data | JetBrains Mono 11/14, 400 | same |
| How Loop read it | "HOW LOOP READ IT" | eyebrow | Instrument Sans 11.5/14, 600 | same |
| How Loop read it | Can't-do lines | body | Instrument Sans 16/22, 400 | same |
| How Loop read it | "Loop filled in", "Notes" | data | JetBrains Mono 11/14, 400 | same |
| How Loop read it | Filled-in line | body | Instrument Sans 16/22, 400 | same |
| How Loop read it | Its source ("preset", "default"), notes | data | JetBrains Mono 11/14, 400 | same |
| Chip editor | Title ("DISTANCE · YOU SAID") | eyebrow | Instrument Sans 11.5/14, 600 | same |
| Chip editor | Stepper value ("3 mi") | numeral-l | Fraunces 24/26, 400 | same |
| Chip editor | Options | label | Instrument Sans 12.5/16, 500 | same |
| Chip editor | Start note | body + data | as listed | same |
| Chip editor | "Cancel" / "Done" | body / body-strong | Instrument Sans 16/22, 400 / 600 | same |
| Look Around | Title ("East River Esplanade · 1.0 mi") | label | Instrument Sans 12.5/16, 500 | same |
| Look Around | "Apple Look Around imagery" | data | JetBrains Mono 11/14, 400 | same |
| Errors | "Couldn't read the saved route" | body | Instrument Sans 16/22, 400 | same |
| Debug only | "Replay build" | data | JetBrains Mono 11/14, 400 | same |

Not ours, left as they are: Mapbox's logo and attribution, Apple's own Look Around controls (the
Maps logo and "Look Around" label inside Apple's view), and the system keyboard.

Icons, not text: SF Symbols for the magnifier, preferences, close (×), plus, chevron, checkmark,
binoculars and the weather glyph. They are sized in points like icons and draw no text.

No system-font text anywhere. Unused style: stretch-name (nothing uses it yet). The question screen
(one question with tap options) isn't built yet, so it has no text to audit.
