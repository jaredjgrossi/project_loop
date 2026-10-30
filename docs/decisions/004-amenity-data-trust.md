# 004: What the real amenity data can and cannot support

**Status:** accepted (Phase 1 findings, rules to be implemented in Phase 2)

Checked against the live datasets on 2026-10-30. This changes some trust-label assumptions in the project plan.

## Drinking fountains (`qnv7-p7a2`)
- Last updated by the publisher **2024-07-15** (837 days before load). The loader prints a warning for any dataset older than a year.
- All 3,849 rows say `featuresta = Active`; there is no operating status and **no seasonal field**.
- 543 rows are indoor, 1 is a dog fountain, 1 a sink or cooler; 3,304 are `usable`. Troughs, "Monument" and "Other" types are kept; whether they suit runners is unconfirmed.
- Hudson River Park fountains are not in this dataset.
- **Rule:** a fountain can be `listed` at best, never `verified`. "In season" cannot be established from this data. Phase 2 may add a documented seasonal rule (for example, assume off from November to March) and show that as `seasonal_or_closed`.

## Restrooms (`i7jb-7jku`)
Updated the day of load; 1,100 rows including Hudson River Park piers, libraries and plazas. Labels come from two fields, `status` and `open`, plus the free-text `hours_of_operation` (stored verbatim; 90 rows have none, and formats vary widely):

| status | open | label |
|---|---|---|
| Not Operational, Closed, Closed for Construction | any | `seasonal_or_closed` (not offered as a stop) |
| Operational | Year Round | `verified` only if the posted hours cover the planned run time, otherwise `listed` |
| Operational | Seasonal | `listed`; season dates are not in the data, so Phase 2 needs a documented rule |
| any | Future | `seasonal_or_closed` |
| Operational | blank | `listed` |

613 rows read "8am-4pm, Open later seasonally", which is why early-morning runs need the flag.

## Parks Properties (`enfh-gkve`)
- The `waterfront` flag (178 true, 1 null) is a **scoring input**, not the whole answer. It is inconsistent (two "North Shore Esplanade" rows disagree).
- **Hudson River Park and Governors Island are not in this dataset** (managed by trusts, not DPR). Waterfront and greenway share must also come from OSM geometry, as the plan already allowed.
- Includes 356 triangles/plazas and 351 gardens alongside real parks. Park-share scoring should weight by `typecategory`.
- 14 polygons arrive self-intersecting; see 006.
