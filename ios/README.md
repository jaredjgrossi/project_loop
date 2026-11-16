# Loop for iPhone

SwiftUI, iPhone only, iOS 17+, Mapbox Maps. The app sends the runner's sentence to the Loop API and draws what comes
back as it streams: the parsed request, a question when one is needed, the top three routes as they improve, and the
final route files with names, reasons, trust words and turn-by-turn directions. It also keeps saved routes and history,
shares a route as GPX, and records "I ran it" with a rating. How it talks to the server is in
[`docs/phase3/ios-wiring.md`](../docs/phase3/ios-wiring.md) and the contract in
[`docs/phase3/parse-contract-v1.md`](../docs/phase3/parse-contract-v1.md); the choices are in `docs/decisions/` from 024 on.

The server runs on the owner's Mac for now (`make serve`); the phone reaches it over a private network. Without a base
URL the app runs on the bundled route file (`Fixtures/kips3-ui.json`), which is enough to check layout.

## Set up
```bash
brew install xcodegen
cp ios/Config/Secrets.example.xcconfig ios/Config/Secrets.xcconfig   # Mapbox pk. token, team ID, optional API base URL
cd ios && xcodegen
open Loop.xcodeproj
```
`Loop.xcodeproj` is generated and git-ignored: edit `project.yml`, then run `xcodegen` again.
Without a Mapbox token the app runs on a plain paper background with the route only.
`Secrets.xcconfig` is git-ignored and holds the server's address: never commit it or put the address in a committed file.
The Loop token is pasted into the app on first launch and kept in the Keychain.

A free Personal Team works for installing on your own phone; the install lasts 7 days.

## Test
```bash
cd ios && xcodebuild -project Loop.xcodeproj -scheme Loop \
  -destination 'platform=iOS Simulator,name=iPhone 17' test
```
Unit tests are in `LoopTests/`, UI tests in `LoopUITests/`. Neither runs in CI.

## Demo mode (debug builds only)
The app can play the demo video's sequence by itself from staged state at the public start (decision 060). It is
compiled out of Release. From the Mac, with the simulator booted or the phone plugged in:
```bash
xcrun simctl launch booted com.jaredgrossi.loop -LoopDemoMode A
```
`A` to `F` picks the segment to start from (earlier ones are staged first). On the phone, a two-second press on the
wordmark arms it for the next launch. The driver logs `Loop demo: …` lines to the system log.

## Fonts
Fraunces and Instrument Sans (variable TTFs from google/fonts), each under the
SIL Open Font License 1.1. The licence files sit beside the fonts and ship in the app bundle.
