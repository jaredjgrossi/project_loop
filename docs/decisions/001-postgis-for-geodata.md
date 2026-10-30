# 001: Postgres + PostGIS for NYC geodata

**Status:** accepted (Phase 1)

## Context
Scoring a route means geometry questions: how much of this line lies inside a park polygon, which fountains are within 150 m of mile 3, how many signalized crossings does it touch. These need spatial indexes and functions (`ST_Intersection`, `ST_DWithin`, `ST_LineLocatePoint`), not loops in Python.

## Decision
Postgres 16 with PostGIS. Store geometry as SRID 4326 (lon/lat). For distance and area math, project to EPSG:2263 (NY State Plane, feet) so results are in real units and accurate at NYC's latitude.

## Consequences
- The official `postgis/postgis` image is Intel-only (checked 2026-10-30). On Apple Silicon we use the community multi-arch `imresamu/postgis:16-3.5-bookworm`, pinned by tag. Hosted Postgres (Neon, Supabase) supports PostGIS, so this carries to deployment.
- SQLite/SpatiaLite was the alternative; it is fine for a prototype but is weaker for the spatial joins Phase 2 needs and is a poorer fit for a hosted API.
