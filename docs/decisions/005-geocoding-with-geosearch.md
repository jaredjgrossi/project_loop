# 005: Geocoding with NYC Planning Labs GeoSearch, with verification

**Status:** accepted (Phase 1). Partly replaced by 026 (2026-11-06): when the same address is in several boroughs,
the borough rule (R19) picks one before Loop asks.

## Decision
Use GeoSearch (`geosearch.planninglabs.nyc/v2/search`): free, no key, built on the city's own address points (PAD). Nothing better is needed for Phase 1. It is a public service without an uptime guarantee, so it sits behind `api/geocoding.py`, which is easy to swap.

## What the real service does (tested live and recorded as fixtures)
- Every address comes back as `layer: venue`, `source: nycpad`. There is **no `address` layer**: `layers=address` returns nothing. (An early idea, pinning the search to the address layer, was wrong.)
- Valid street addresses come back as `confidence 0.8, match_type fallback`. Confidence cannot be a quality signal.
- Real hazards:
  - The same number and street exists in several boroughs, and the service ranks one arbitrarily. Bare "11 Madison Ave" returns Staten Island first.
  - A wrong house number still returns an answer ("100 Main St" returns 190C Main Street, Bronx).
  - Place names resolve to an arbitrary building ("Union Square" returns 5 Union Square).

## Behavior
The wrapper checks the answer against the query: house number and street must match; a number+street present in more than one borough raises `AmbiguousAddressError` unless a borough or zip is given; place names raise `NotAnAddressError`; a mismatch raises `LowConfidenceError` naming what was offered instead. It never picks quietly. Phase 1 therefore needs a street address with a number; named places (parks, landmarks) are a later feature.
