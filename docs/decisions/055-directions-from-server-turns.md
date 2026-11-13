# 055 — Directions read the server's turns

**Status:** accepted · builds on 053 (Directions list) and the server's 054 (`summary.steps`)

## Decision
When a route's file carries `summary.steps`, the Directions list is built from it: "Turn left onto
East 33rd Street", "Bear right", "Turn sharp right onto East River Esplanade", "Continue onto X", the
turnaround, the finish. A turn with a null street reads without "onto" (the server says the runner is already
on that street). The turnaround line reads "Turn around, head back on X" and carries the distance to the next step.

When the key is absent (routes that weren't routed: run-again and stored lines, older files) the list is the
stretch version from 053, unchanged.

## Why
053 could only say "Continue onto" at a change of street because the files carried no left/right. The server now
sends GraphHopper's maneuvers, measured and tiled to the route, with short noise folded away. The phone adds no
geometry or numbers: it only phrases what the file says.

## Not done
- Steps are not yet tied to the map (tap a step to centre on `point`).
- Street names are only as good as the stretch labels (nearest named street within 30 m), so an avenue leg can
  carry a cross street's name or none.
