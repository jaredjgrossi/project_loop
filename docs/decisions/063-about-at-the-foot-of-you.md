# 063: About sits at the foot of "You", and the install id copies bare

**Status:** accepted (2026-11-23). Needed by the public privacy page, which tells runners how to ask for their
data to be deleted.

## Context
Loop has no accounts. The server tells one phone from another by a random install id (decision 043,
`X-Loop-Install`), made on first launch and kept in `runs.json`. The privacy page says a runner can have their data
deleted by sending that id, but the app showed it nowhere, and there is no Settings or About screen to show it on.
The only settings-like surface is the token paste on first launch.

## Decision
1. **About is a section at the foot of "You", not a screen of its own.** "You" is already the one place for
   the runner's own things (defaults, history, saved routes); a separate Settings screen for two rows would be a
   screen the runner opens once. A hairline, the ABOUT eyebrow, then two rows: Version (`0.1.0 (1)`, from the
   bundle) and Install id.
2. **Tapping the install id row copies the bare id.** The pasteboard gets the UUID and nothing else, so it pastes
   straight into an email. "Copy" becomes "Copied" for 1.6 s and the row keeps its place. The line under it says
   what the id is for in one sentence: no account, this is all Loop knows you by, send it to have your runs deleted.
3. **The path is Loop → You (the route-L button, top right) → About, at the bottom.** There is no Settings
   screen; copy that says "Settings → You → About" should say "You → About" (or "the L button, top right").

All text uses the sheet's existing styles (eyebrow, body, body-strong, label) and tokens; nothing new.

## Not done
- No Settings screen. If one appears later, About moves there and this note is superseded.
- The id is not shown anywhere else (not on the token screen, not in the GPX).
