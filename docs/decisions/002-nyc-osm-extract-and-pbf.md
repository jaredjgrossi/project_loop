# 002: NYC-only OpenStreetMap extract

**Status:** accepted (Phase 1)

## What a `.pbf` is
OpenStreetMap is a giant database of streets, paths, crossings and signals. A `.pbf` ("Protocolbuffer Binary Format") is a compressed binary snapshot of part of it. GraphHopper reads one to build its routing graph. Geofabrik publishes a `.pbf` per region, refreshed daily.

## Decision
`python -m routing.prepare_osm` downloads the New York State extract (498 MB, Geofabrik snapshot of 2026-10-28) and clips it with `osmium extract` to the five boroughs, giving `routing/data/nyc.osm.pbf` (91 MB). The boundary is NYC DCP **Borough Boundaries (water areas included)**, dataset `wh2p-dxnf`. Both `.pbf` files and the boundary are git-ignored and rebuildable.

## Things that did not match the first idea
- The first boundary I reached for, `gthc-hcne`, is the **water-excluded** version. Clipping to it would cut piers, esplanades and greenway sections built over water, which are exactly where people run. `wh2p-dxnf` avoids that.
- `osmium` keeps whole ways that cross the boundary (`complete_ways`, its default). The clipped file's bounding box still reaches Montauk (lon -70.55) because a few long ways, mainly ferry lines, extend far outside the city. Routing from points out there fails ("Cannot find point"), so the graph is NYC-only for practical purposes, but it is not a strict clip. Ferries are excluded from routing (see 003).
