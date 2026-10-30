# 003: GraphHopper (self-hosted) for routing

**Status:** accepted (Phase 1)

## Why GraphHopper
Open source, runs on a small instance, supports round-trip routing, and lets us change how it values paths with JSON "custom models" (Phase 2: favor parks and waterfront). The NYC graph imports in about 10 seconds; the container used about 830 MB when measured (JVM heap capped at 2 GB).

## How it runs
- No official Docker image exists, so `routing/Dockerfile` runs the official 11.1 release jar on `eclipse-temurin:21-jre`, pinned by SHA-256.
- Round trips do not work with contraction hierarchies (GraphHopper's speed-up index), so `profiles_ch` is empty. Fine at NYC's size.
- `import.osm.ignored_highways` is a required key in 11.1. It is set to empty (keep everything); the foot model already excludes unwalkable roads.
- The graph cache lives in `routing/graph-cache/foot-v2` (git-ignored). We have not relied on GraphHopper noticing config or map changes, so after changing either, delete that folder (or bump the suffix) to force a re-import.

## Things that did not match the first idea
- **The stock `foot` profile routes the Staten Island Ferry** (a Whitehall-to-St. George "walk" came back as 5.3 miles). A run cannot include a ferry. `routing/custom_models/loop_foot.json` is the stock foot model plus `road_environment == FERRY -> multiply_by 0`; the same trip now returns "connection not found". The file can't be named `foot.json` because GraphHopper reserves that name for its built-in.
- Round-trip distance is only approximate; see 007.
