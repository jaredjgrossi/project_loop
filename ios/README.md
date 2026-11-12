# Loop for iPhone (first slice)

SwiftUI, iPhone only, iOS 17+. The main screen in two states against a saved route
(`Fixtures/kips3-ui.json`), with a "play the build" replay. No networking to the engine.

## Set up
```bash
brew install xcodegen
cp ios/Config/Secrets.example.xcconfig ios/Config/Secrets.xcconfig   # add your Mapbox pk. token and team ID
cd ios && xcodegen
open Loop.xcodeproj
```
`Loop.xcodeproj` is generated and git-ignored: edit `project.yml`, then run `xcodegen` again.
Without a Mapbox token the app runs on a plain paper background with the route only.

## Test
```bash
cd ios && xcodebuild -project Loop.xcodeproj -scheme Loop \
  -destination 'platform=iOS Simulator,name=iPhone 17' test
```

## Fonts
Fraunces and Instrument Sans (variable TTFs from google/fonts), each under the
SIL Open Font License 1.1. The licence files sit beside the fonts and ship in the app bundle.

## Design lab (branch `design-explore-first-week`, never merged)
Three explorations from `design-review-v1.md`, each behind its own switch so old and new can be
compared on the phone. Debug builds only; with every switch off the app behaves as `main` does.

- Switches: **You → Design lab** (kept in UserDefaults).
- **A · Asking:** the field grows to three lines and has a send arrow; a runner with no runs of
  their own sees examples to try (`Screen/Composer.swift`). "A · As a new runner" shows that home
  sheet on a phone that already has runs.
- **B · The wait:** the camera holds the reach ring until the settle, a new leader waits a second
  before the line morphs, and a line under the sentence counts the routes looked at
  (`MainModel.holdForDwell`, `waitLine`).
- **C · Reading the route:** the other two routes stay on the map with a distance pill and can be
  opened; the card says "1 OF 3 · OUT AND BACK" and names the route; the open sheet lists the way;
  climb is in feet (`Screen/RouteChoices.swift`).
- Screenshots: `-LoopLab composer,calmWait,routes` turns the named ones on for one launch.

## Signature moments (branch `design-explore-signature`, never merged)
Three moments from `signature-moments-v1.md`, each with a wildcard, behind Debug switches in
**You → Design lab** (off by default; off is the app as it is on `main`). Code in `Loop/Signature/`.

- **D · Pencil, then ink** (`InkMoment.swift`): candidates and the current best are graphite; at
  the flag the winner is inked, mile marks stamp in, the distance rolls up, and one Core Haptics
  pattern plays for the whole move. **D+** adds a tilted camera at the settle, paper grain and sound.
- **E · Fly the route** (`Flyover.swift`): a play button on the card flies the route in 3D, lit for
  the planned hour, with a caption that counts and names. **E+** adds drag to scrub, tap to pause
  and a cream paper-model city.
- **F · The run joins your map** (`Arrival.swift`): after a rating, the run draws over every run so
  far and the totals roll. **F+** adds a shareable poster (each run's first and last 200 m left off).
- Recordings: `-LoopLab ink,flyover,arrival` (or `inkWild`, `flyoverWild`, `arrivalWild`); `-LoopFly`
  starts the flight and `-LoopArrive` marks the route run and rates it.
