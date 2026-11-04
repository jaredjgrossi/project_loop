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
Fraunces, Instrument Sans and JetBrains Mono (variable TTFs from google/fonts), each under the
SIL Open Font License 1.1. The licence files sit beside the fonts and ship in the app bundle.
