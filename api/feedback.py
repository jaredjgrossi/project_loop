"""Feedback on a generated route (decision 014): "I ran it", a 1-5 rating, and what went wrong, overall or on a
stretch. Ratings are the signal the provisional weights get tuned with (decisions 010, 011).

No GPS track is accepted here: a recorded run is personal data, handled only under decision 011's privacy rules.
The tables are generated_routes and route_feedback in etl/sql/schema.sql.
"""

import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Issue = Literal[
    "crowded", "closed_or_blocked", "too_many_lights", "unsafe_crossing", "bad_surface", "ran_in_the_roadway",
    "too_long", "too_short", "not_what_i_asked", "restroom_missing", "water_missing", "other",
]


class StretchIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stretch: int = Field(ge=0)  # index into the route's stretch features (api/segments.py)
    issue: Issue


class RouteFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_id: str = Field(min_length=1, max_length=64)
    ran_it: bool
    rating: int | None = Field(default=None, ge=1, le=5)
    ran_at: datetime | None = None
    issues: list[Issue] = Field(default_factory=list)
    stretch_issues: list[StretchIssue] = Field(default_factory=list)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _rating_goes_with_the_run(self) -> "RouteFeedback":
        if self.ran_it and self.rating is None:
            raise ValueError("a run needs a rating from 1 to 5")
        if not self.ran_it and self.rating is not None:
            raise ValueError("a rating needs the run: set ran_it")
        return self


def _by_stretch(features: list[dict]) -> dict[int, dict]:
    """Stretch features by index. Route pieces (decision 023) carry their stretch's index too and are skipped, so a
    report on a stretch gets the stretch's name and whole line, not one piece's."""
    return {f["properties"]["stretch"]: f for f in features
            if f["properties"].get("feature", "stretch") == "stretch" and "stretch" in f["properties"]}


def crowd_report_rows(feedback: RouteFeedback, stretches: list[dict], start: datetime | None) -> list[dict]:
    """Rows for crowd_reports (decision 016): each "crowded" report, for the whole route or a stretch, with the crowd
    level the route showed there and the hour it was run (ran_at, else the requested start). Kept to calibrate crowd
    levels later; nothing reads them yet."""
    when = feedback.ran_at or start
    hour, weekday = (when.hour, when.weekday()) if when else (None, None)
    by_index = {i: s["properties"] for i, s in _by_stretch(stretches).items()}
    rows = []
    if "crowded" in feedback.issues:
        rows.append({"route_id": feedback.route_id, "stretch": None, "stretch_name": None, "level_shown": None,
                     "band": None, "hour": hour, "weekday": weekday})
    for si in feedback.stretch_issues:
        if si.issue != "crowded":
            continue
        props = by_index.get(si.stretch, {})
        crowd = props.get("crowd") or {}
        rows.append({"route_id": feedback.route_id, "stretch": si.stretch, "stretch_name": props.get("name"),
                     "level_shown": crowd.get("value"), "band": crowd.get("band"), "hour": hour, "weekday": weekday})
    return rows


def save_crowd_reports(conn, rows: list[dict]) -> None:
    """Insert crowd_report_rows into crowd_reports (etl/sql/schema.sql)."""
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO crowd_reports (route_id, stretch, stretch_name, level_shown, band, hour, weekday)
               VALUES (%(route_id)s, %(stretch)s, %(stretch_name)s, %(level_shown)s, %(band)s, %(hour)s, %(weekday)s)""",
            rows)


def closure_report_rows(feedback: RouteFeedback, stretches: list[dict]) -> list[dict]:
    """Rows for closure_reports (decision 017): each "closed or blocked" report, with the stretch's geometry as the
    route showed it, so a reviewer can confirm it into a closure (api/closures.py: confirm_report). A whole-route
    report has no place and is kept without geometry."""
    by_index = _by_stretch(stretches)
    base ={"route_id": feedback.route_id, "ran_at": feedback.ran_at, "note": feedback.note}
    rows = []
    if "closed_or_blocked" in feedback.issues:
        rows.append({**base, "stretch": None, "stretch_name": None, "geom": None})
    for si in feedback.stretch_issues:
        if si.issue != "closed_or_blocked":
            continue
        feature = by_index.get(si.stretch)
        rows.append({**base, "stretch": si.stretch, "stretch_name": feature["properties"].get("name") if feature else None,
                     "geom": json.dumps(feature["geometry"]) if feature else None})
    return rows


def save_closure_reports(conn, rows: list[dict]) -> None:
    """Insert closure_report_rows into closure_reports (etl/sql/schema.sql)."""
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO closure_reports (route_id, stretch, stretch_name, ran_at, note, geom)
               VALUES (%(route_id)s, %(stretch)s, %(stretch_name)s, %(ran_at)s, %(note)s,
                       ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s), 4326))""",
            rows)
