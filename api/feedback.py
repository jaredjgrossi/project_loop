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


# ---- the iPhone app's "I ran it" and rating (Phase 3, decision 043) -------------------------------------------------

Verdict = Literal["good", "not_for_me"]
Reason = Literal["crowded", "lights", "water", "safety", "other"]  # keys, never wording: the app words them


class AppFeedback(BaseModel):
    """`POST /v1/routes/{id}/feedback`. A later post from the same install replaces the earlier one (a changed
    rating). `rating` may be left out after "I ran it" and given later."""
    model_config = ConfigDict(extra="forbid")

    ran: bool
    ran_at: datetime | None = None
    rating: Verdict | None = None
    reasons: list[Reason] = Field(default_factory=list, max_length=5)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _rating_goes_with_the_run(self) -> "AppFeedback":
        if self.rating is not None and not self.ran:
            raise ValueError("a rating needs the run: set ran")
        if self.reasons and self.rating is None:
            raise ValueError("reasons go with a rating")
        return self


# Phase 2's table took a 1-5 rating with every run and nothing else. The app's rating is a verdict, given when the
# runner wants, from one install, and may change: these columns and the relaxed check let both live in one table.
MIGRATE = """
ALTER TABLE route_feedback ADD COLUMN IF NOT EXISTS install_id text;
ALTER TABLE route_feedback ADD COLUMN IF NOT EXISTS verdict text;
ALTER TABLE route_feedback ADD COLUMN IF NOT EXISTS reasons text[] NOT NULL DEFAULT '{}';
ALTER TABLE route_feedback ADD COLUMN IF NOT EXISTS updated_at timestamptz;
ALTER TABLE route_feedback DROP CONSTRAINT IF EXISTS route_feedback_check;
ALTER TABLE route_feedback DROP CONSTRAINT IF EXISTS route_feedback_ran_check;
ALTER TABLE route_feedback ADD CONSTRAINT route_feedback_ran_check
    CHECK ((rating IS NULL AND verdict IS NULL) OR ran_it);
ALTER TABLE route_feedback DROP CONSTRAINT IF EXISTS route_feedback_verdict_check;
ALTER TABLE route_feedback ADD CONSTRAINT route_feedback_verdict_check
    CHECK (verdict IS NULL OR verdict IN ('good', 'not_for_me'));
CREATE UNIQUE INDEX IF NOT EXISTS route_feedback_route_install_idx ON route_feedback (route_id, install_id)
    WHERE install_id IS NOT NULL;
"""

_GENERATED = """
INSERT INTO generated_routes (id, constraints, rank, method, kind, label, score, metrics, dimensions, stretches,
                              elevation, timing, geom)
VALUES (%(id)s, %(constraints)s, %(rank)s, 'phase3', %(kind)s, %(label)s, %(score)s, '{}', '[]', %(stretches)s,
        %(elevation)s, NULL, ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s), 4326))
ON CONFLICT (id) DO NOTHING
"""

_UPSERT = """
INSERT INTO route_feedback (route_id, install_id, ran_it, ran_at, verdict, reasons, note, updated_at)
VALUES (%(route_id)s, %(install_id)s, %(ran)s, %(ran_at)s, %(verdict)s, %(reasons)s, %(note)s, now())
ON CONFLICT (route_id, install_id) WHERE install_id IS NOT NULL DO UPDATE SET
    ran_it = EXCLUDED.ran_it, ran_at = coalesce(EXCLUDED.ran_at, route_feedback.ran_at),
    verdict = EXCLUDED.verdict, reasons = EXCLUDED.reasons, note = EXCLUDED.note, updated_at = now()
RETURNING created_at, updated_at, xmax <> 0
"""


def generated_row(route_id: str, final: dict, constraints: dict) -> dict | None:
    """The generated_routes row a Phase 3 route needs before feedback can point at it: its line, kind, label and
    score from the stored `final`, and the #1's stretches when it is the #1."""
    from psycopg.types.json import Jsonb
    entry = next((r for r in final.get("routes") or [] if r.get("id") == route_id), None)
    if entry is None:
        build, _, n = route_id.partition(".")
        entry = next((r for r in final.get("routes") or [] if str(r.get("rank")) == (n or "1")), None)
    if entry is None or not entry.get("geometry"):
        return None
    feature = ((final.get("route") or {}).get("features") or [{}])[0] if entry.get("rank") == 1 else {}
    props = feature.get("properties") or {}
    return {"id": route_id, "constraints": Jsonb(constraints or {}), "rank": entry.get("rank") or 1,
            "kind": entry.get("kind") or "loop", "label": entry.get("label") or "", "score": entry.get("score") or 0,
            "stretches": Jsonb(props.get("stretches") or []), "elevation": Jsonb(props.get("elevation")),
            "geom": json.dumps({"type": "LineString", "coordinates": [c[:2] for c in entry["geometry"]["coordinates"]]})}


class PgFeedbackStore:
    """route_feedback in the local Postgres, migrated on first use."""

    def __init__(self):
        self._ready = False

    def _connect(self):
        import psycopg

        from etl.load import database_url
        conn = psycopg.connect(database_url(), connect_timeout=2, autocommit=True)
        if not self._ready:
            conn.execute(MIGRATE)
            self._ready = True
        return conn

    def save(self, route_id: str, install_id: str, fb: AppFeedback, final: dict, constraints: dict) -> dict:
        """Store (or update) one install's feedback on one route. Returns {created_at, updated_at, updated}."""
        row = generated_row(route_id, final, constraints)
        if row is None:
            raise LookupError(route_id)
        with self._connect() as conn:
            conn.execute(_GENERATED, row)
            created, updated_at, was_update = conn.execute(_UPSERT, {
                "route_id": route_id, "install_id": install_id, "ran": fb.ran, "ran_at": fb.ran_at,
                "verdict": fb.rating, "reasons": list(fb.reasons), "note": fb.note}).fetchone()
        return {"created_at": created.isoformat(), "updated_at": updated_at.isoformat(), "updated": bool(was_update)}

    def load(self, route_id: str, install_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("""SELECT ran_it, ran_at, verdict, reasons, note FROM route_feedback
                                  WHERE route_id = %s AND install_id = %s""", (route_id, install_id)).fetchone()
        if row is None:
            return None
        return {"ran": row[0], "ran_at": row[1].isoformat() if row[1] else None, "rating": row[2],
                "reasons": list(row[3]), "note": row[4]}
