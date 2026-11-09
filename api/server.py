"""The Loop API (Phase 3, step 5; contract docs/phase3/parse-contract-v1.md; decision 029).

    make serve            # uv run uvicorn api.server:app, on 127.0.0.1:8000

- `POST /v1/runs` streams server-sent events: `parsed`, then `top3` (as the leader changes), `provisional` and
  `final`, then `done`; or `error`. A question ends the stream after `parsed` (and `done`); the answer comes back as
  a new POST with `answer`, which resumes the pending parse with no second Claude call. A chip edit sends
  `constraints` and skips Claude.
- `GET /v1/routes/{id}`: a built result, the same payload as `final`, from saved_routes (decision 030).
- `GET /v1/health`: the server is up, and whether the engine, the database and the parser key are ready.

Every route but health needs `Authorization: Bearer <LOOP_TOKEN>`; the token lives in .env, never in git or the
app's source. The Claude key never leaves the server. Request bodies aren't logged: they hold the runner's location.
"""

import asyncio
import os
import secrets
import threading
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime
from typing import Literal

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from starlette.concurrency import run_in_threadpool

from api.constraints import RunConstraints
from api.copy import render
from api.engine import (BadStart, Engine, EngineQuestion, EngineUnavailable, before_build, end_for, graphhopper_ready,
                        new_route_id, start_for)
from api.parse import Context, DbPlaces, answer_overrides, parse, parsed_for_constraints, resume
from api.pending import Pending, PendingStore
from api.saved_routes import PgRouteStore, stored_request

MAX_TEXT = 500  # characters; a run request is a sentence or two
MAX_ROUTES_KEPT = 50  # the latest builds, also kept in memory; every build is in saved_routes (step 7)


# ---- the request (contract: POST /v1/runs) -----------------------------------------------------------------------


class _Loose(BaseModel):
    model_config = ConfigDict(extra="ignore")  # a newer app may send more; a breaking change bumps "v"


class Location(_Loose):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy_m: float | None = None


class ClientInfo(_Loose):
    now: str
    tz: str = "America/New_York"
    location: Location | None = None

    @field_validator("now")
    @classmethod
    def _iso(cls, v: str) -> str:
        datetime.fromisoformat(v)
        return v


class SavedPlace(_Loose):
    id: str
    label: str | None = None
    lat: float | None = None
    lon: float | None = None


class Profile(_Loose):
    usual_distance_mi: float | None = None
    usual_time: str | None = None
    saved_places: list[SavedPlace] = []


class RecentRoute(_Loose):
    id: str
    date: str
    name: str
    distance_mi: float | None = None
    times_run: int | None = None


class Answer(_Loose):
    parse_id: str
    question_id: str
    option_id: str | None = None
    text: str | None = Field(default=None, max_length=MAX_TEXT)


class RunRequest(_Loose):
    v: Literal[1]
    text: str | None = Field(default=None, max_length=MAX_TEXT)
    answer: Answer | None = None
    constraints: dict | None = None
    client: ClientInfo
    profile: Profile = Profile()
    recent_routes: list[RecentRoute] = []

    @model_validator(mode="after")
    def _exactly_one(self) -> "RunRequest":
        given = [k for k in ("text", "answer", "constraints") if getattr(self, k) is not None]
        if len(given) != 1:
            raise ValueError("exactly one of text, answer or constraints")
        if self.text is not None and not self.text.strip():
            raise ValueError("empty text")
        return self

    def context_request(self) -> dict:
        """The shape parse() reads: text, client, profile and recent routes."""
        return self.model_dump(mode="json", include={"text", "client", "profile", "recent_routes"})


# ---- events ------------------------------------------------------------------------------------------------------


def _event(payload: dict) -> ServerSentEvent:
    return ServerSentEvent(event=payload["event"], data=payload)


def _error(code: str) -> ServerSentEvent:
    return _event({"event": "error", "v": 1, "code": code, "text": render(f"error.{code}")})


DONE = {"event": "done", "v": 1}


class _Fail(Exception):
    def __init__(self, code: str):
        self.code = code


# ---- the app -----------------------------------------------------------------------------------------------------


def _db_places() -> Callable:
    @contextmanager
    def opened():
        from etl.load import database_url
        with psycopg.connect(database_url()) as conn:
            yield DbPlaces(conn)

    return opened


def _health_checks() -> dict:
    out = {"engine": graphhopper_ready(), "database": False, "parser": bool(os.environ.get("ANTHROPIC_API_KEY"))}
    try:
        from etl.load import database_url
        with psycopg.connect(database_url(), connect_timeout=2) as conn:
            out["database"] = conn.execute("SELECT to_regclass('places') IS NOT NULL").fetchone()[0]
    except psycopg.Error:
        pass
    return out


def create_app(*, token: str | None = None, parse_fn: Callable | None = None, places: Callable | None = None,
               engine: Engine | None = None, store: PendingStore | None = None,
               route_store=None, health_fn: Callable[[], dict] = _health_checks, warm: bool = True) -> FastAPI:
    """The app. Tests pass fakes; `uvicorn api.server:app` uses the real parser, places table and engine."""
    from api.env import load_env

    load_env()
    token = token or os.environ.get("LOOP_TOKEN")
    if not token:
        raise RuntimeError("LOOP_TOKEN isn't set. Add a line LOOP_TOKEN=<random> to .env (see docs/phase3/ios-wiring.md).")
    parse_fn = parse_fn or parse
    places = places or _db_places()
    engine = Engine() if engine is None else engine
    store = PendingStore() if store is None else store
    route_store = PgRouteStore() if route_store is None else route_store
    routes: OrderedDict[str, dict] = OrderedDict()
    routes_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(_app):
        if warm:  # the scoring processes take a few seconds to start; not on the first request's clock
            from api import scoring_pool
            threading.Thread(target=scoring_pool.warm, daemon=True).start()
        yield

    app = FastAPI(title="Loop", version="1", lifespan=lifespan)

    def check_token(authorization: str | None = Header(default=None)) -> None:
        given = (authorization or "").removeprefix("Bearer ").strip()
        if not given or not secrets.compare_digest(given.encode(), token.encode()):
            raise HTTPException(status_code=401, detail="unauthorized")

    def keep_route(final: dict) -> None:
        with routes_lock:
            routes[final["route_id"]] = final
            while len(routes) > MAX_ROUTES_KEPT:
                routes.popitem(last=False)

    def from_text(req: RunRequest) -> tuple[dict, dict, dict]:
        """(parsed, trace, the request to keep if it asks): one Claude call, then the rules."""
        raw = req.context_request()
        try:
            out = parse_fn(raw)
        except psycopg.Error as exc:
            raise _Fail("engine_unavailable") from exc
        if "error" in out:
            raise _Fail(out["error"] if out["error"] in ("parse_failed", "bad_request") else "parse_failed")
        return out["parsed"], out["trace"], raw

    def from_answer(req: RunRequest) -> tuple[dict, dict, dict]:
        """Resume the pending parse with the answer: the rules again, no Claude call."""
        a = req.answer
        pending = store.take(a.parse_id)
        if pending is None:
            raise _Fail("expired")
        if a.question_id != pending.question_id:
            raise _Fail("bad_request")
        ctx = Context.from_request(pending.request)
        settled = answer_overrides(pending.answer_map, a.option_id, a.text, ctx)
        if settled is None:
            raise _Fail("bad_request")
        if not pending.ext and pending.constraints is not None:  # the engine asked about a chip edit's constraints
            c = dict(pending.constraints)
            if "distance" in settled:
                c["distance_mi"] = settled["distance"]
                c["sources"] = {k: v for k, v in (c.get("sources") or {}).items() if k != "distance_mi"}  # said
            try:
                return parsed_for_constraints(c, ctx, None), {}, pending.request
            except ValidationError as exc:
                raise _Fail("bad_request") from exc
        try:
            with places() as p:
                out = resume(pending.ext, ctx, p, {**pending.answers, **settled})
        except psycopg.Error as exc:
            raise _Fail("engine_unavailable") from exc
        if "error" in out:
            raise _Fail("parse_failed")
        out["trace"]["extraction"] = pending.ext
        return out["parsed"], out["trace"], pending.request

    def from_constraints(req: RunRequest) -> tuple[dict, dict, dict]:
        raw = req.context_request()
        try:
            parsed = parsed_for_constraints(req.constraints, Context.from_request(raw), None)
        except ValidationError as exc:
            raise _Fail("bad_request") from exc
        return parsed, {}, raw

    def location_and_saved(raw: dict) -> tuple[dict | None, dict]:
        client, profile = raw.get("client") or {}, raw.get("profile") or {}
        return client.get("location"), {p["id"]: p for p in profile.get("saved_places") or []}

    def build_planned(rc: RunConstraints, planned: dict, kept: dict, location, saved) -> dict:
        """The `planned` event (contract; D6): the second run built for its day, from its own start (home on a
        later day, R16), stored like any build so its route_id works later. Built quietly: only `planned` is
        streamed. If it can't be built now, the event still carries its day and constraints, with a note, and the
        app builds it when the runner opens it."""
        p = rc.planned
        pid = new_route_id()
        chips = parsed_for_constraints(planned, Context.from_request(kept), None)["chips"]
        event = {"event": "planned", "v": 1, "parse_id": f"p_{secrets.token_hex(4)}", "route_id": None,
                 "date": p.start_date.isoformat(), "chips": chips, "constraints": planned,
                 "summary": {"distance_mi": p.distance_mi,
                             "start_time": p.start_time},
                 "notes": []}
        try:
            final = engine.build(p, start_for(p, location, saved), lambda e: None, pid, end=end_for(p, saved))
        except (EngineQuestion, EngineUnavailable, BadStart):
            final = None
        if final is None or not final["routes"]:
            day = p.start_date.strftime("%A")
            event["notes"] = [{"id": "n_pl1", "key": "planned_not_built", "trust": "listed",
                               "text": render("note.planned_not_built", day=day)}]
            return event
        keep_route(final)
        route_store.save(pid, stored_request(kept, "planned", event["parse_id"]), planned, final)
        event["route_id"] = pid
        event["summary"]["distance_mi"] = final["routes"][0]["distance"]["value"]
        return event

    async def stream(req: RunRequest) -> AsyncIterator[ServerSentEvent]:
        kind = "text" if req.text is not None else "answer" if req.answer is not None else "constraints"
        step = {"text": from_text, "answer": from_answer, "constraints": from_constraints}[kind]
        try:
            parsed, trace, kept = await run_in_threadpool(step, req)
        except _Fail as f:
            yield _error(f.code)
            return
        if parsed.get("question"):
            q = parsed["question"]
            store.put(Pending(parse_id=parsed["parse_id"], question_id=q["id"], ext=trace.get("extraction") or {},
                              request=kept, answers=trace.get("answers") or {}, answer_map=trace.get("answer_map")))
            yield _event(parsed)
            yield _event(DONE)
            return
        try:
            rc = RunConstraints.model_validate(parsed["constraints"])
        except ValidationError:
            yield _error("parse_failed")
            return
        lines, blocked = before_build(rc)
        n = len(parsed["cant"])
        parsed["cant"] = parsed["cant"] + [{"id": f"k_{n + i}", "gap": x["gap"], "text": x["text"]}
                                           for i, x in enumerate(lines, 1)]
        yield _event(parsed)
        if blocked:
            yield _event(DONE)
            return
        location, saved = location_and_saved(kept)
        try:
            start = start_for(rc, location, saved)
            end = end_for(rc, saved)
        except BadStart:
            yield _error("bad_request")
            return

        # The engine's worker threads call `send`; the events cross into this loop through the queue.
        loop, queue = asyncio.get_running_loop(), asyncio.Queue()
        route_id = new_route_id()

        def send(ev: dict) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, ev)

        def work() -> None:
            try:
                final = engine.build(rc, start, send, route_id, end=end)
                keep_route(final)  # kept even if the phone has gone, for GET /v1/routes/{id}
                # Stored before the phone gets final, so the id it holds always works, after a restart too.
                # No text and no location (decision 030); a few ms for the insert.
                stored = {k: v for k, v in parsed["constraints"].items() if k != "spans"}  # spans are the runner's words
                route_store.save(route_id, stored_request(kept, kind, parsed["parse_id"]), stored, final)
                send(final)
                if rc.planned is not None:  # D6, step 11: the second run, built for its own day, after the first
                    send(build_planned(rc, stored.get("planned") or {}, kept, location, saved))
            except EngineQuestion as q:  # e.g. the end is farther than the distance: ask, and keep the parse open
                pid = f"p_{secrets.token_hex(4)}"
                store.put(Pending(parse_id=pid, question_id=q.question["id"], ext=trace.get("extraction") or {},
                                  request=kept, answers=trace.get("answers") or {}, answer_map=q.answer_map,
                                  constraints=parsed["constraints"]))
                send({"event": "question", "v": 1, "parse_id": pid, **q.question})
            except EngineUnavailable:
                send({"event": "error", "v": 1, "code": "engine_unavailable",
                      "text": render("error.engine_unavailable")})
            except Exception:  # noqa: BLE001 - the stream must end; the traceback goes to the server log
                import traceback
                traceback.print_exc()
                send({"event": "error", "v": 1, "code": "engine_unavailable",
                      "text": render("error.engine_unavailable")})

        threading.Thread(target=work, name=f"build-{route_id}", daemon=True).start()
        last = ("planned",) if rc.planned is not None else ("final",)
        while True:
            ev = await queue.get()
            yield _event(ev)
            if ev["event"] in (*last, "question", "error"):
                break
        if ev["event"] in ("final", "planned", "question"):
            yield _event(DONE)

    async def raw_body(request: Request) -> bytes:
        """Read before the stream starts: FastAPI runs an SSE endpoint in its own task once the response has begun,
        and reading the body from there waits forever."""
        return await request.body()

    @app.post("/v1/runs", response_class=EventSourceResponse, dependencies=[Depends(check_token)])
    async def runs(raw: bytes = Depends(raw_body)) -> AsyncIterator[ServerSentEvent]:
        try:
            req = RunRequest.model_validate_json(raw)
        except ValidationError:  # bad JSON or a bad shape: the stream says so, as any error
            yield _error("bad_request")
            return
        async for ev in stream(req):
            yield ev

    @app.get("/v1/routes/{route_id}", dependencies=[Depends(check_token)])
    def get_route(route_id: str) -> dict:
        with routes_lock:
            found = routes.get(route_id)
        if found is None:
            found = route_store.load(route_id)  # an older build, or one from before a restart
        if found is None:
            raise HTTPException(status_code=404, detail="no such route")
        return found

    @app.get("/v1/health")
    def health() -> dict:
        checks = health_fn()
        return {"v": 1, "ok": all(checks.values()), **checks}

    return app


def __getattr__(name: str):
    """`uvicorn api.server:app` builds the real app on first use, so importing this module needs no token."""
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)
