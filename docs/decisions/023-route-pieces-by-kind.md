# 023: The route line in pieces by kind, so a stretch's caption hides nothing

**Status:** accepted and implemented (Phase 2, 2026-11-04). Extends 020. No ranking weights or ranking inputs changed.

## Context
The iPhone app colors the route line by kind. A stretch has one `kind`, which is a caption (020), but its composition can mix kinds. On the Kips Bay 3 mi #1 (after the NYU Langone driveway closure, 2026-11-04), the East River Esplanade stretch holds 265 m of path and 116 m of street, and the first FDR Drive stretch holds 79 m of waterfront. Coloring by stretch would hide them.

## Decision
1. **Pieces** (`route_context.pieces_by_range`). The route line is cut wherever the 5 m sample class (waterfront, park, path, street; 020) or the stretch changes. Each piece has one kind, the stretch it sits in, where it starts and ends, and its line. Neighbors share an end point, so the pieces draw the whole route without gaps.
2. **Meters that add up.** A piece's `length_m` weighs each sample the way the stretch compositions do. A stretch's pieces add up to its composition, within 0.1 m of rounding, and so to the summary's shares.
3. **GeoJSON** (`segments.piece_features`). There's one `"feature": "piece"` per piece, after the stretches, with `kind`, `length_m`, `from_mile`, `to_mile`, `stretch`, `stretch_name`, `status: measured` and a source. The route line and the stretches stay as they were.
4. **Pieces are kept apart from stretches.** `route_stretches` still returns stretches only. `make_loop` adds the pieces through `route_stretches_and_pieces`. The summary and the feedback rows skip pieces. Feedback matters most here: a piece carries its stretch's index, and without the skip, a report on a stretch would store one piece's line.
5. **No smoothing.** Short pieces stay, so the meters add up. On the Kips Bay #1, 5 of 25 pieces are under 20 m, 48 m in all. The app can merge them for drawing.
6. **Top 3 distances** (`api/scripts/ui_fixture.py`). Each of the top 3 carries its summary `distance` object, with unit, `measured` and source, in place of a bare `distance_mi`. The script that writes `out/fixtures/kips3-ui.json` is now in the repo.

## Limits
- **Equal sample weights skew the meters.** Every 5 m sample counts the same, but samples are closer together where the line has many short segments, which is mostly on streets. On the Kips Bay #1, a piece's meters and its drawn length differ by up to 22 m. By kind, street counts 43.3% weighted against 41.8% drawn, and waterfront 51.2% against 52.8%. The summary's shares and the ranking's waterfront input (`shares`) carry the same skew. Fixing it would change the ranking input, so it isn't fixed here.
