"""Every build, stored in Postgres (Phase 3, step 7; decision 030).

`saved_routes` keeps one row per build: the route id, what kind of request it was (text, an answer or a chip edit),
its parse id and clock, the RunConstraints, and the `final` payload, so `GET /v1/routes/{id}` works after a restart.

What it never keeps (rule R8, the brief's privacy rule):
- the raw request text, which can hold health details. It stays only in llm_calls, for 30 days, without location.
- the phone's location, profile and recent routes. Those live on the phone and are sent with each request.

The route's own line still starts where the runner starts. It is the product, and it lives only in this local
Postgres, never exported or committed.

Storing never breaks a build: if Postgres can't be reached, that is said once on stderr and the build still streams.
"""

import sys
import threading

import psycopg
from psycopg.types.json import Jsonb

DDL = """
CREATE TABLE IF NOT EXISTS saved_routes (
    route_id     text        PRIMARY KEY,           -- r_xxxxxxxx; its routes are r_xxxxxxxx.N
    created_at   timestamptz NOT NULL DEFAULT now(),
    request      jsonb       NOT NULL,              -- {v, kind, parse_id, client: {now, tz}}: no text, no location
    constraints  jsonb       NOT NULL,              -- RunConstraints, as built
    final        jsonb       NOT NULL               -- the final event's payload, as streamed
);
CREATE INDEX IF NOT EXISTS saved_routes_created_at_idx ON saved_routes (created_at);
"""


def stored_request(request: dict, kind: str, parse_id: str | None) -> dict:
    """What saved_routes keeps of a request: its version, kind, parse id and clock. Nothing the runner typed, and
    nothing from where they are."""
    client = request.get("client") or {}
    return {"v": request.get("v", 1), "kind": kind, "parse_id": parse_id,
            "client": {"now": client.get("now"), "tz": client.get("tz")}}


class PgRouteStore:
    """saved_routes in the local Postgres. The table is created on first use, once per process."""

    def __init__(self):
        self._ready = False
        self._lock = threading.Lock()
        self._warned = False

    def _connect(self):
        from etl.load import database_url
        conn = psycopg.connect(database_url(), connect_timeout=2, autocommit=True)
        if not self._ready:
            with self._lock:
                if not self._ready:
                    conn.execute(DDL)
                    self._ready = True
        return conn

    def _warn(self, exc: Exception) -> None:
        if not self._warned:
            print(f"saved_routes: not stored or read ({exc.__class__.__name__}: {exc})", file=sys.stderr)
            self._warned = True

    def save(self, route_id: str, request: dict, constraints: dict, final: dict) -> bool:
        try:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO saved_routes (route_id, request, constraints, final) VALUES (%s, %s, %s, %s)
                       ON CONFLICT (route_id) DO UPDATE SET request = EXCLUDED.request,
                           constraints = EXCLUDED.constraints, final = EXCLUDED.final""",
                    (route_id, Jsonb(request), Jsonb(constraints), Jsonb(final)))
            return True
        except psycopg.Error as exc:
            self._warn(exc)
            return False

    def load(self, route_id: str) -> dict | None:
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT final FROM saved_routes WHERE route_id = %s", (route_id,)).fetchone()
            return row[0] if row else None
        except psycopg.Error as exc:
            self._warn(exc)
            return None
