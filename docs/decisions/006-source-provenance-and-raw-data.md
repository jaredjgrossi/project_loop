# 006: Provenance on every row; raw downloads stay out of git

**Status:** accepted (Phase 1)

- Every row in `parks`, `drinking_fountains` and `public_restrooms` carries `source_dataset_id`, `source_row_id` (Socrata `:id`), `source_updated_at` (row-level), `loaded_at`, and `raw` (the untouched source row as JSONB). That is what lets any later claim link back to its source (product rule 2).
- Downloads go to `etl/data/raw/` with a `.meta.json` sidecar (fetch time, publisher's last-updated time, row count). The folder is git-ignored; `python -m etl.load_all --refresh` re-fetches.
- Loading is truncate-and-reload in one transaction, so it can be re-run safely.
- Rows are labeled, not dropped: fountains get `usable` and `skip_reason`, so the rule can change without a re-download. Rows that cannot be placed (no or implausible coordinates) are rejected and counted in the output; none were in the 2026-10-30 data.
- 14 of 2,061 park polygons had self-intersecting rings, which break area and overlap math. They are repaired with `ST_MakeValid` and flagged `geom_was_invalid`.
