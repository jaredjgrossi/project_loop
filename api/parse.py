"""Parse a plain-English run request (Phase 3, step 4; decisions 025, 028).

One Claude call records what the runner said through a single strict tool, `record_request`. Its schema holds the
runner's words (a distance and its unit, a place name, a time word), never RunConstraints and never coordinates.
Deterministic code then applies the eval rules (docs/phase3/parse-evals-v1.md, R1–R19):
- resolves places through the places table and the geocoder (R12, R13, R16, R19)
- turns times, days, units, ranges and fractions into values (R5, R7)
- fills defaults and usual values, each labeled with its source (R2, R6, R17)
- builds RunConstraints, the chips, can't-do lines and notes, or the one question (R3, R4)

Every string the runner sees comes from api/copy.py (R1). Claude receives the text, the local time, saved-place
labels and recent-route names; never a coordinate. Each call is logged in llm_calls (api/llm_log.py).

`parse(request)` returns {"parsed": <contract parsed event>, "trace": {...}} or {"error": key, "text": ...}. The
trace is for the evals and the server, never sent to the phone: each field's source, the lookups made, the routing
calls made (always 0 here), and the template key behind every string.
"""

import json
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from api.constraints import PREFERENCES, PRESETS, PlaceRef, RunConstraints
from api.copy import render
from api.places import is_streetlike, normalize

PROMPT_VERSION = "parse_v3"  # earlier versions stay in api/prompts/: their calls are in llm_calls by version
PROMPT = (Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.md").read_text()
DEFAULT_MODEL = "claude-haiku-5-5"
DEFAULT_EFFORT = "low"
DEFAULT_THINKING = "adaptive"  # or "off" (Haiku 5.5 accepts thinking off at effort high or below)

# $ per million tokens: input, output, cache write, cache read. Haiku 5.5's cache rates are assumed at the usual
# 1.25x and 0.1x of input; check against the pricing page before quoting costs outside the evals.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50, 0.125, 0.01),
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.20),
    "claude-opus-5-5": (4.00, 20.00, 5.00, 0.20),
}

MIN_MI, MAX_MI = 0.5, 30.0  # D5: the engine's bounds
SCHEMA_RETRIES = 1  # a tool input that doesn't fit the schema is asked for once more (both calls are logged)
KM_TO_MI = 0.621371
HALF_MARATHON_MI, MARATHON_MI = 13.11, 26.22
DEFAULT_HOURS = {"lunch": "12:00", "after_work": "18:30", "tonight": "20:00"}  # D4; morning is the usual time
FALLBACK_USUAL_TIME = "07:00"
ASK_HOW_FAR = (3, 5, 10)  # R06: no usual distance
ASK_LONG_RUN = (6, 8, 10)  # R6: "long run" with no distance
ASK_WORKOUT = (6, 7, 8)  # R11: total distance for a workout
ASK_LONGER = (1, 2)  # H02: "but longer"
MAX_OPTIONS = 4
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
CANT = {  # what Claude flags -> (gap id, copy key)
    "lighting_safety": ("G9", "cant.G9"),
    "bike_lanes": ("bike_lanes", "cant.bike_lanes"),
    "bridges_in_general": ("G1", "cant.G1.bridges"),
    "whole_way": ("G1", "cant.G1.whole_way"),
    "workout_segments": ("G8", "cant.G8"),
    "soft_avoid": ("G3", "cant.G3"),
}

# ---- the extraction tool ----------------------------------------------------------------------------------------


# Nothing here is nullable: "not said" is "none" for an enum, "" for a string, 0 for a number, and kind "none" for an
# object; _clean turns those back into None. The tool isn't strict: strict mode allows 16 nullable parameters and
# rejected this schema's compiled grammar as too large (2026-11-06). _conform checks the input against the schema
# instead, filling what the model left out with "not said" and refusing wrong types.


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_ENUM = lambda *v: {"type": "string", "enum": list(v)}  # noqa: E731
_OPT = lambda *v: _ENUM("none", *v)  # noqa: E731
_STR, _NUM, _BOOL = {"type": "string"}, {"type": "number"}, {"type": "boolean"}
_DISTANCE = _obj({"value": _NUM, "unit": _ENUM("mi", "km", "half_marathon", "marathon"), "max_value": _NUM})
_TIME = _obj({"kind": _OPT("clock", "in_minutes", "morning", "lunch", "after_work", "tonight"),
              "clock": _STR, "minutes": _NUM})
_DAY = _obj({"kind": _OPT("today", "tomorrow", "weekday", "date"), "weekday": _OPT(*WEEKDAYS), "date": _STR})
_PLACE = _obj({"kind": _OPT("place", "address", "saved", "here", "neighborhood", "the_park",
                            "subjective"),
               "name": _STR, "saved_id": _STR, "outside_nyc": _BOOL})
_PREFS = {
    "mode": _OPT("training", "exploring"), "lights": _OPT("waits", "zigzags"),
    "crowds": _OPT("avoid", "some", "dont_mind"), "scenery": _OPT("park_or_water", "some", "dont_mind"),
    "surface": _OPT("paths", "any"), "turns": _OPT("fewer", "dont_mind"), "familiar": _OPT("favor", "some", "new"),
    "hills": _OPT("avoid", "dont_mind"), "shape": _OPT("loop_word", "real_loop", "out_and_back"),
}
TOOL = {
    "name": "record_request",
    "description": "Record what the runner's request says, field by field. Call exactly once.",
    "input_schema": _obj({
        "distance": _DISTANCE,
        "minutes": _NUM,
        "long_run": _BOOL,
        "workout": _BOOL,
        "time": _TIME,
        "day": _DAY,
        "start": _PLACE,
        "end": _PLACE,
        "via": {"type": "array", "items": _obj({"name": _STR, "kind": _ENUM("place", "the_park"),
                                                "whole_way": _BOOL})},
        "avoid": {"type": "array", "items": _obj({"name": _STR, "how": _ENUM("along", "area")})},
        **_PREFS,
        "amenities": {"type": "array", "items": _obj({"kind": _ENUM("restroom", "water"), "at_mile": _NUM,
                                                      "at_fraction": _NUM})},
        "reuse": _obj({"kind": _OPT("usual", "weekday", "date", "name", "last_week", "last"),
                       "weekday": _OPT(*WEEKDAYS), "date": _STR, "name_words": _STR, "longer": _BOOL,
                       "reverse": _BOOL}),
        "second_run": _obj({"present": _BOOL, "distance": _DISTANCE, "day": _DAY, "time": _TIME, "start": _PLACE}),
        "cant": {"type": "array", "items": _ENUM(*CANT)},
    }),
}


class SchemaError(ValueError):
    """The tool input doesn't fit the schema."""


def _conform(v, schema: dict, path: str = "input", dropped: list | None = None):
    """The tool input checked against TOOL's schema, without strict mode's guarantee. Tidied deterministically:
    missing fields become "not said", extra fields are dropped, quotes and spaces around a choice are stripped, a
    number written as text is read, and an unknown item in a list of choices is dropped (and listed in `dropped`).
    Anything else that doesn't fit raises SchemaError."""
    kind = schema.get("type")
    if kind == "object":
        if v is None or v in ("", "none", 0):  # an unsaid object written as empty: not said
            v = {}
        if not isinstance(v, dict):
            raise SchemaError(f"{path}: expected an object")
        return {k: _conform(v.get(k), sub, f"{path}.{k}", dropped) for k, sub in schema["properties"].items()}
    if kind == "array":
        if v is None:
            return []
        if not isinstance(v, list):
            raise SchemaError(f"{path}: expected a list")
        items = schema["items"]
        if "enum" in items:  # a list of choices: keep the known ones
            keep = [str(x).strip().strip('"').strip() for x in v if isinstance(x, str)]
            if dropped is not None:
                dropped += [f"{path}: {x!r}" for x in keep if x not in items["enum"]]
            return [x for x in keep if x in items["enum"]]
        return [_conform(x, items, f"{path}[{i}]", dropped) for i, x in enumerate(v)]
    if kind == "string":
        if v is None:
            return "none" if "none" in schema.get("enum", []) else ""
        if not isinstance(v, str):
            raise SchemaError(f"{path}: expected text")
        if "enum" in schema:
            v = v.strip().strip('"').strip("'").strip()
        if "enum" in schema and v not in schema["enum"]:
            raise SchemaError(f"{path}: {v!r} is not one of {schema['enum']}")
        return v
    if kind == "number":
        if v is None or (isinstance(v, str) and v.strip().casefold() in ("", "none", "null")):
            return 0
        if isinstance(v, str):
            try:
                return float(v.strip())
            except ValueError:
                raise SchemaError(f"{path}: expected a number") from None
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise SchemaError(f"{path}: expected a number")
        return v
    if kind == "boolean":
        if v is None:
            return False
        if not isinstance(v, bool):
            raise SchemaError(f"{path}: expected true or false")
        return v
    raise SchemaError(f"{path}: unknown schema type {kind}")


def _clean(v, key: str = ""):
    """Tool sentinels -> None: "none", "", 0 for numbers, kind "none", a distance of 0, an absent second run."""
    if isinstance(v, dict):
        if v.get("kind") == "none" or ("present" in v and not v["present"]):
            return None
        if "unit" in v and not v.get("value"):
            return None
        return {k: _clean(x, k) for k, x in v.items() if k != "present"}
    if isinstance(v, list):
        return [_clean(x, key) for x in v]
    if v in ("none", ""):
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v == 0 and key in (
            "minutes", "max_value", "at_mile", "at_fraction", "value"):
        return None
    return v


# ---- places, as the parser needs them ---------------------------------------------------------------------------


class Places(Protocol):
    def lookup(self, name: str, near=None) -> list: ...
    def pick(self, matches: list, ref_borough: str | None): ...
    def borough_at(self, lat: float, lon: float) -> str | None: ...
    def in_neighborhood(self, name: str, lat: float, lon: float) -> bool: ...
    def park_around(self, match): ...
    def major_parks_near(self, lat: float, lon: float) -> list: ...
    def parks_near(self, lat: float, lon: float) -> list: ...
    def geocode(self, address: str, borough: str | None): ...  # -> (GeocodeResult | None, [boroughs])


class DbPlaces:
    """Places backed by the places table (decision 026) and NYC GeoSearch (decision 005)."""

    def __init__(self, conn):
        self.conn = conn

    def lookup(self, name, near=None):
        from api.places import lookup
        return lookup(name, near=near, conn=self.conn)

    def pick(self, matches, ref_borough):
        from api.places import pick_by_borough
        return pick_by_borough(matches, ref_borough)

    def borough_at(self, lat, lon):
        from api.places import borough_at
        return borough_at(lat, lon, conn=self.conn)

    def in_neighborhood(self, name, lat, lon):
        from api.places import in_neighborhood
        return in_neighborhood(name, lat, lon, conn=self.conn)

    def park_around(self, match):
        from api.places import park_around
        return park_around(match, conn=self.conn)

    def major_parks_near(self, lat, lon):
        from api.places import major_parks_near
        return major_parks_near(lat, lon, conn=self.conn)

    def parks_near(self, lat, lon):
        from api.places import parks_near
        return parks_near(lat, lon, conn=self.conn)

    def geocode(self, address, borough):
        from api.geocoding import AmbiguousAddressError, GeocodeError, geocode
        try:
            return geocode(f"{address}, {borough}" if borough else address), []
        except AmbiguousAddressError as exc:
            return None, list(exc.boroughs)
        except GeocodeError:
            return None, []


# ---- the request's context --------------------------------------------------------------------------------------


@dataclass
class Context:
    text: str
    now: datetime  # local, naive
    location: tuple[float, float] | None
    usual_mi: float | None
    usual_time: str | None
    saved: dict  # id -> {"label", "lat", "lon"}
    recent: list[dict]

    @classmethod
    def from_request(cls, req: dict) -> "Context":
        client, profile = req.get("client") or {}, req.get("profile") or {}
        now = datetime.fromisoformat(client["now"]).replace(tzinfo=None)
        loc = client.get("location")
        return cls(text=(req.get("text") or "").strip(), now=now, location=(loc["lat"], loc["lon"]) if loc else None,
                   usual_mi=profile.get("usual_distance_mi"), usual_time=profile.get("usual_time"),
                   saved={p["id"]: p for p in profile.get("saved_places") or []},
                   recent=list(req.get("recent_routes") or []))

    def for_claude(self, text: str) -> str:
        """The user message: no coordinates, ever."""
        return json.dumps({
            "request": text,
            "now": f"{self.now:%A %Y-%m-%d %H:%M}",
            "location_known": self.location is not None,
            "saved_places": [{"id": i, "label": p.get("label")} for i, p in sorted(self.saved.items())],
            "recent_routes": [{"id": r["id"], "date": r["date"], "weekday": _weekday_of(r["date"]), "name": r["name"],
                               "distance_mi": r.get("distance_mi"), "times_run": r.get("times_run")}
                              for r in self.recent],
        }, ensure_ascii=False)


def _weekday_of(iso: str) -> str:
    return WEEKDAY_NAMES[date.fromisoformat(iso).weekday()]


# ---- the result being built -------------------------------------------------------------------------------------


class _Ask(Exception):
    """Raised by a rule that needs the one question."""

    def __init__(self, question: dict):
        self.question = question


@dataclass
class _Build:
    ctx: Context
    places: Places
    constraints: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)
    cant: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    lookups: list = field(default_factory=list)
    texts: list = field(default_factory=list)
    start_borough: str | None = None
    start_point: tuple[float, float] | None = None

    def say(self, key: str, **values) -> str:
        text = render(key, **values)
        self.texts.append({"text": text, "key": key})
        return text

    def set(self, name: str, value, source: str, prefix: str = "") -> None:
        if prefix:
            self.constraints.setdefault("planned", {})[name] = value
        else:
            self.constraints[name] = value
        self.sources[prefix + name] = source

    def ask(self, about: str, frm: str, key: str, options: list[tuple[str, dict]] = (), allow_text: bool = True,
            **values):
        q = {"id": "q_1", "about": about, "from": frm, "text": self.say(key, **values),
             "options": [{"id": chr(97 + i), "text": self.say(k, **v)} for i, (k, v) in enumerate(options[:MAX_OPTIONS])],
             "allow_text": allow_text}
        raise _Ask(q)


def _miles(d: dict | None) -> tuple[float, float | None] | None:
    """(miles, tolerance %) from the extracted distance; a range is its middle, with the tolerance to reach both ends."""
    if not d:
        return None
    per = {"mi": 1, "km": KM_TO_MI, "half_marathon": HALF_MARATHON_MI, "marathon": MARATHON_MI}[d["unit"]]
    low = round(d["value"] * per, 2)
    if d.get("max_value") and d["max_value"] > d["value"]:
        high = round(d["max_value"] * per, 2)
        mid = round((low + high) / 2, 2)
        return mid, round((high - low) / 2 / mid * 100, 1)
    return low, None


def _fmt(miles: float) -> str:
    return f"{miles:g}"


def _clock(t: datetime) -> str:
    return f"{t:%H:%M}"


def _resolve_day(day: dict | None, today: date) -> date | None:
    if not day:
        return None
    if day["kind"] == "today":
        return today
    if day["kind"] == "tomorrow":
        return today + timedelta(days=1)
    if day["kind"] == "weekday" and day.get("weekday"):
        ahead = (WEEKDAYS.index(day["weekday"]) - today.weekday()) % 7
        return today + timedelta(days=ahead)
    if day["kind"] == "date" and day.get("date"):
        try:
            return date.fromisoformat(day["date"])
        except ValueError:
            return None
    return None


def _resolve_time(b: _Build, t: dict | None, day: date | None) -> tuple[str, str]:
    """(HH:MM, source) for a time word (R5, D4). A later day with no hour gets the usual time."""
    ctx = b.ctx
    if t:
        if t["kind"] == "clock" and t.get("clock") and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t["clock"]):
            return t["clock"], "said"
        if t["kind"] == "in_minutes" and t.get("minutes") is not None:
            return _clock(ctx.now + timedelta(minutes=t["minutes"])), "said"
        if t["kind"] == "morning":
            return (ctx.usual_time, "usual") if ctx.usual_time else (FALLBACK_USUAL_TIME, "default")
        if t["kind"] in DEFAULT_HOURS:
            return DEFAULT_HOURS[t["kind"]], "default"
    if day is not None and day > ctx.now.date():
        return (ctx.usual_time, "usual") if ctx.usual_time else (FALLBACK_USUAL_TIME, "default")
    return _clock(ctx.now), "default"


def _time_and_day(b: _Build, t: dict | None, d: dict | None, prefix: str = "") -> None:
    day = _resolve_day(d, b.ctx.now.date())
    hhmm, tsrc = _resolve_time(b, t, day)
    b.set("start_time", hhmm, tsrc, prefix)
    if day is None:  # the next time that clock time comes round (decision 020)
        at = datetime.strptime(hhmm, "%H:%M").time()
        day = b.ctx.now.date() if at >= b.ctx.now.time().replace(second=0, microsecond=0) \
            else b.ctx.now.date() + timedelta(days=1)
        b.set("start_date", day.isoformat(), "default", prefix)
    else:
        b.set("start_date", day.isoformat(), "said", prefix)


# ---- places -----------------------------------------------------------------------------------------------------


def _ref(m, source="OpenStreetMap") -> dict:
    return PlaceRef(kind="place", name=m.matched, borough=m.borough, lat=m.lat, lon=m.lon,
                    source=getattr(m, "source", source), trust="listed").model_dump(exclude_none=True)


def _saved_ref(b: _Build, saved_id: str) -> dict:
    p = b.ctx.saved[saved_id]
    ref = {"kind": "saved", "id": saved_id, "name": p.get("label"), "source": "profile"}
    if p.get("lat") is not None:
        ref |= {"lat": p["lat"], "lon": p["lon"], "borough": b.places.borough_at(p["lat"], p["lon"])}
    return PlaceRef(**ref).model_dump(exclude_none=True)


def _options(matches) -> list[tuple[str, dict]]:
    with_at = [m for m in matches if getattr(m, "at", None)]
    if len(with_at) == len(matches) == 2:  # "86th St" at Central Park: by side, then the crossing street
        east, west = sorted(matches, key=lambda m: -m.lon)
        return [("option.side", {"side": "East", "at": east.at}), ("option.side", {"side": "West", "at": west.at})]
    return [("option.place", {"name": m.matched, "borough": m.borough}) for m in matches]


def _resolve_place(b: _Build, spec: dict, role: str, ref_point, ref_borough, near_area=None) -> dict | None:
    """A place ref for a start, end or via spec, or a question (R12, R13, R14, R19)."""
    kind, name = spec["kind"], (spec.get("name") or "").strip()
    about = role if role in ("start", "end") else "via"
    if spec.get("outside_nyc"):
        b.ask(about, "places", "question.place.outside_nyc_end" if role == "end" else "question.place.outside_nyc")
    if kind == "subjective":
        b.ask(about, "parser", f"question.{'end' if role == 'end' else 'start'}.subjective")
    if kind == "saved":
        sid = spec.get("saved_id") or name or "home"
        if sid in b.ctx.saved:
            return _saved_ref(b, sid)
        b.ask(about, "parser", "question.place.saved_unknown", word=sid)
    if kind == "the_park":
        point = ref_point or b.ctx.location
        major = b.places.major_parks_near(*point) if point else []
        if major:
            return _ref(major[0])
        options = [("option.place", {"name": p.name, "borough": p.borough})
                   for p in (b.places.parks_near(*point) if point else [])]
        b.ask(about, "places", "question.place.which_park", options, allow_text=True)
    if kind == "address":
        b.lookups.append({"name": name, "role": role, "via": "geocoder"})
        hit, boroughs = b.places.geocode(name, None)
        if hit is None and boroughs:
            if ref_borough in boroughs:  # R19 step 1; addresses carry no distance, so step 2 can't apply
                hit, _ = b.places.geocode(name, ref_borough)
            else:
                b.ask(about, "places", "question.place.which", [("option.borough", {"borough": x}) for x in boroughs],
                      name=name)
        if hit is None:
            b.ask(about, "places", "question.place.not_found", name=name)
        return PlaceRef(kind="address", name=name, borough=hit.borough, lat=hit.lat, lon=hit.lon,
                        source="NYC GeoSearch", trust="listed").model_dump(exclude_none=True)
    # A named place (R12)
    b.lookups.append({"name": name, "role": role})
    found = b.places.lookup(name, near=near_area or ref_point)
    if not found and re.match(r"\d+[A-Za-z]?\s+\S", name):  # "11 Madison Ave" recorded as a place: it's an address
        return _resolve_place(b, spec | {"kind": "address"}, role, ref_point, ref_borough)
    if not found:
        b.ask(about, "places", "question.place.not_found", name=name)
    chosen = found[0] if len(found) == 1 else b.places.pick(found, ref_borough)
    if chosen is None:
        b.ask(about, "places", "question.place.which", _options(found), name=name)
    return _ref(chosen)


# ---- the rules --------------------------------------------------------------------------------------------------


# R6: sightseeing words set mode=exploring, never scenery. The prompt says so; Haiku doesn't always hold it
# (eval P39, 2026-11-06), so code enforces it: scenery from a request whose only cue is sightseeing is dropped.
SIGHTSEEING = re.compile(r"\b(scenic|sightsee\w*|show(?:ing)? (?:\w+ ){0,2}around|tourist\w*)\b", re.I)
SCENERY_CUES = re.compile(r"\b(water\w*|river\w*|harbou?r|park|parks|views?|green\w*|trees|esplanade|beach\w*|ocean|"
                          r"lake|pond|shore\w*|pier\w*)\b", re.I)


def scenery_from_sightseeing_only(text: str) -> bool:
    return bool(SIGHTSEEING.search(text)) and not SCENERY_CUES.search(text)


def _prefs(b: _Build, ext: dict) -> None:
    if ext.get("scenery") and scenery_from_sightseeing_only(b.ctx.text):
        ext = {**ext, "scenery": None}
    for name in ("mode", *PREFERENCES):
        if ext.get(name):
            b.set(name, ext[name], "said")
    shape = {"loop_word": "any", "real_loop": "loop", "out_and_back": "out_and_back"}.get(ext.get("shape") or "")
    if shape:  # D1, R10: a plain "loop" is any route back to the start
        b.set("shape", shape, "said")
    else:
        b.set("shape", "any", "default")


def _cant(b: _Build, ext: dict) -> None:
    # G8 follows the workout flag, so the line and the question agree (a tempo run is no workout)
    flags = [f for f in ext.get("cant") or [] if f != "workout_segments"]
    if ext.get("workout"):
        flags.append("workout_segments")
    if any(v.get("whole_way") for v in ext.get("via") or []):
        flags.append("whole_way")
    seen = set()
    for f in flags:
        gap, key = CANT[f]
        if key not in seen:
            seen.add(key)
            b.cant.append({"id": f"k_{len(b.cant) + 1}", "gap": gap, "text": b.say(key)})


def _start(b: _Build, ext: dict, vias: list) -> None:
    """R16: today from the current location; a later day from home; otherwise ask. Named starts resolve (R12)."""
    spec = ext.get("start")
    day = b.constraints.get("start_date")
    later = day is not None and date.fromisoformat(day) > b.ctx.now.date()
    loc = b.ctx.location
    loc_borough = b.places.borough_at(*loc) if loc else None
    if spec is None or spec["kind"] == "here":
        said = "said" if spec else "default"
        if not later and loc and loc_borough:
            b.set("use_my_location", True, said)
            b.start_point, b.start_borough = loc, loc_borough
            return
        if "home" in b.ctx.saved:
            ref = _saved_ref(b, "home")
            b.set("start_place", ref, "default")
            b.start_point = (ref["lat"], ref["lon"]) if "lat" in ref else None
            b.start_borough = ref.get("borough")
            return
        b.ask("start", "parser", "question.start.where")
    if spec["kind"] == "neighborhood":
        b.lookups.append({"name": spec.get("name") or "", "role": "neighborhood"})
        if loc and b.places.in_neighborhood(spec.get("name") or "", *loc):
            b.set("use_my_location", True, "said")
            b.start_point, b.start_borough = loc, loc_borough
            return
        b.ask("start", "parser", "question.place.neighborhood", name=spec.get("name") or "")
    ref_borough = loc_borough
    if later and "home" in b.ctx.saved:
        ref_borough = _saved_ref(b, "home").get("borough")
    # "Starting at 86th st" on a run through the Reservoir: the street where it meets the park around that place.
    near_area = None
    if spec["kind"] == "place" and vias and is_streetlike(normalize(spec.get("name") or "")) \
            and vias[0][1].kind in ("park", "water"):
        near_area = b.places.park_around(vias[0][1])
    ref = _resolve_place(b, spec, "start", loc, ref_borough, near_area=near_area)
    b.set("start_place", ref, "said")
    b.start_point = (ref["lat"], ref["lon"]) if "lat" in ref else loc
    b.start_borough = ref.get("borough", ref_borough)


def _vias(b: _Build, ext: dict) -> list:
    """Resolve via places near the runner first (the start may depend on them). Returns (spec, match) pairs."""
    out = []
    point = b.ctx.location
    borough = b.places.borough_at(*point) if point else None
    for v in ext.get("via") or []:
        if v["kind"] == "the_park":
            major = b.places.major_parks_near(*point) if point else []
            if not major:
                opts = [("option.place", {"name": p.name, "borough": p.borough})
                        for p in (b.places.parks_near(*point) if point else [])]
                b.ask("via", "places", "question.place.which_park", opts)
            out.append((v, major[0]))
            continue
        b.lookups.append({"name": v["name"], "role": "via"})
        found = b.places.lookup(v["name"], near=point)
        if not found:
            b.ask("via", "places", "question.place.not_found", name=v["name"])
        chosen = found[0] if len(found) == 1 else b.places.pick(found, borough)
        if chosen is None:
            b.ask("via", "places", "question.place.which", _options(found), name=v["name"])
        if v.get("whole_way") and chosen.kind == "street":
            continue  # "2nd Ave the whole way": a street isn't a via target; the can't-do line says so (G1)
        out.append((v, chosen))
    return out


def _distance(b: _Build, ext: dict) -> None:
    """R2, R6, R7, R10, R11, R17: from the request, the usual distance, the route's places, or a question."""
    got = _miles(ext.get("distance"))
    if got:
        miles, tol = got
        if miles > MAX_MI:
            guess = round(miles / 10, 2)
            if MIN_MI <= guess <= MAX_MI:
                b.ask("distance", "parser", "question.distance.typo", [("option.miles", {"miles": _fmt(guess)})],
                      miles=_fmt(guess))
            b.ask("distance", "parser", "question.distance.too_long", [("option.miles", {"miles": _fmt(MAX_MI)})])
        if miles < MIN_MI:
            b.ask("distance", "parser", "question.distance.too_short", [("option.miles", {"miles": _fmt(MIN_MI)})])
        b.set("distance_mi", miles, "said")
        if tol is not None:
            b.set("tolerance_pct", min(tol, 25.0), "said")
        return
    if "end_place" in b.constraints or "reuse_route_id" in b.constraints:
        return  # the end or the reused route sets the length (R10, R17)
    if ext.get("minutes"):
        b.ask("distance", "parser", "question.distance.minutes", minutes=f"{ext['minutes']:g}")
    if ext.get("workout"):
        b.ask("distance", "parser", "question.distance.workout",
              [("option.miles", {"miles": _fmt(m)}) for m in ASK_WORKOUT])
    if ext.get("long_run"):
        b.ask("distance", "parser", "question.distance.long_run",
              [("option.miles", {"miles": _fmt(m)}) for m in ASK_LONG_RUN])
    if b.ctx.usual_mi:
        b.set("distance_mi", b.ctx.usual_mi, "usual")
        return
    b.ask("distance", "parser", "question.distance.how_far", [("option.miles", {"miles": _fmt(m)}) for m in ASK_HOW_FAR])


def _reuse(b: _Build, ext: dict) -> None:
    """R17: past routes come only from the recent-routes list."""
    r = ext.get("reuse")
    if not r:
        return
    recent = sorted(b.ctx.recent, key=lambda x: x["date"], reverse=True)
    today = b.ctx.now.date()
    before = [x for x in recent if date.fromisoformat(x["date"]) < today]
    options = [("option.route", {"weekday": _weekday_of(x["date"]), "name": x["name"]}) for x in recent]
    source = "said"
    if r["kind"] == "usual":
        if not recent:
            b.set("familiar", "favor", "usual")
            return
        hits, source = [max(recent, key=lambda x: (x.get("times_run") or 0, x["date"]))], "usual"
    elif r["kind"] == "weekday" and r.get("weekday"):
        same = [x for x in before if _weekday_of(x["date"]).casefold() == r["weekday"]]
        hits = same[:1]  # the most recent such day, never today
    elif r["kind"] == "date" and r.get("date"):
        hits = [x for x in recent if x["date"] == r["date"]]
    elif r["kind"] == "name" and r.get("name_words"):
        words = [w for w in re.findall(r"\w+", r["name_words"].casefold()) if w not in ("the", "one", "route", "run")]
        hits = [x for x in recent if words and all(w in x["name"].casefold() for w in words)]
    elif r["kind"] == "last_week":
        monday = today - timedelta(days=today.weekday())
        hits = [x for x in recent if monday - timedelta(days=7) <= date.fromisoformat(x["date"]) < monday]
    else:
        hits = before[:1]
    if not hits:
        b.ask("reuse", "parser", "question.reuse.none", options)
    if len(hits) > 1:
        b.ask("reuse", "parser", "question.reuse.which",
              [("option.route", {"weekday": _weekday_of(x["date"]), "name": x["name"]}) for x in hits])
    b.set("reuse_route_id", hits[0]["id"], source)
    if r.get("reverse"):
        b.set("reverse", True, "said")
    if r.get("longer"):
        b.ask("distance", "parser", "question.distance.longer",
              [("option.plus_miles", {"miles": _fmt(m)}) for m in ASK_LONGER])


def _avoid_and_stops(b: _Build, ext: dict) -> None:
    if ext.get("avoid"):
        b.set("avoid_places", [{"name": a["name"], "how": a["how"]} for a in ext["avoid"]], "said")
    stops = []
    for a in ext.get("amenities") or []:
        mile = a.get("at_mile")
        if mile is None and a.get("at_fraction") is not None and b.constraints.get("distance_mi"):
            mile = round(a["at_fraction"] * b.constraints["distance_mi"], 2)
        if mile is not None:
            stops.append({"kind": a["kind"], "at_mile": mile})
    if stops:
        b.set("amenities", stops, "said")


def _planned(b: _Build, ext: dict) -> None:
    """R18, D6: the later run, built for its own day. Its start is home (R16: a later day)."""
    s = ext.get("second_run")
    if not s:
        return
    got = _miles(s.get("distance"))
    if got:
        b.set("distance_mi", got[0], "said", prefix="planned.")
    _time_and_day(b, s.get("time"), s.get("day"), prefix="planned.")
    spec = s.get("start")
    if spec and spec["kind"] != "here":
        ref = _resolve_place(b, spec, "start", b.ctx.location, b.start_borough)
        b.set("start_place", ref, "said", prefix="planned.")
    elif "home" in b.ctx.saved:
        b.set("start_place", _saved_ref(b, "home"), "default", prefix="planned.")
    else:
        b.ask("start", "parser", "question.start.where")


def _notes(b: _Build) -> None:
    mode = b.constraints.get("mode")
    crowds = b.constraints.get("crowds") or (PRESETS[mode]["crowds"] if mode else None)
    if crowds == "avoid" and b.constraints.get("start_time"):
        b.notes.append({"id": f"n_{len(b.notes) + 1}", "key": "crowds_estimated", "trust": "estimate",
                        "text": b.say("note.crowds_estimated", time=b.constraints["start_time"])})
    if any(a["kind"] == "water" for a in b.constraints.get("amenities") or []):
        b.notes.append({"id": f"n_{len(b.notes) + 1}", "key": "fountains_seasonal", "trust": "listed",
                        "text": b.say("note.fountains_seasonal")})


def _chip(b: _Build, cid: str, fieldname: str, key: str, source: str, **values) -> dict:
    return {"id": cid, "field": fieldname, "text": b.say(key, **values), "source": source, "editable": True}


def _chips(b: _Build) -> list[dict]:
    """One chip per thing said, plus the defaults that matter, in the contract's order."""
    c, src = b.constraints, b.sources
    chips = []
    if c.get("use_my_location"):
        chips.append(_chip(b, "c_start", "start", "chip.start.my_location", src["use_my_location"]))
    elif c.get("start_place"):
        p = c["start_place"]
        key = "chip.start.saved" if p["kind"] == "saved" else "chip.start.place"
        chips.append(_chip(b, "c_start", "start", key, src["start_place"], name=p.get("name") or p.get("id"),
                           borough=p.get("borough")) | {"place": _chip_place(p)})
    if c.get("end_place"):
        p = c["end_place"]
        key = "chip.end.saved" if p["kind"] == "saved" else "chip.end.place"
        chips.append(_chip(b, "c_end", "end", key, src["end_place"], name=p.get("name") or p.get("id"),
                           borough=p.get("borough")) | {"place": _chip_place(p)})
    for i, p in enumerate(c.get("via_places") or []):
        chips.append(_chip(b, f"c_via_{i + 1}", "via", "chip.via.place", src["via_places"], name=p["name"],
                           borough=p["borough"]) | {"place": _chip_place(p)})
    if c.get("distance_mi") is not None:
        if "tolerance_pct" in c:  # a range said as "3-4 miles" (decision 025: one chip)
            d, t = c["distance_mi"], c["tolerance_pct"] / 100
            chips.append(_chip(b, "c_distance", "distance", "chip.distance.range", src["distance_mi"],
                               low=_fmt(round(d * (1 - t), 1)), high=_fmt(round(d * (1 + t), 1))))
        else:
            chips.append(_chip(b, "c_distance", "distance", "chip.distance", src["distance_mi"],
                               miles=_fmt(c["distance_mi"])))
    elif c.get("end_place"):
        chips.append(_chip(b, "c_distance", "distance", "chip.distance.shortest", "default"))
    elif c.get("reuse_route_id"):
        chips.append(_chip(b, "c_distance", "distance", "chip.distance.reused", "default"))
    if c.get("start_time"):
        srcs = {src.get("start_time"), src.get("start_date")}
        source = "said" if "said" in srcs else "usual" if "usual" in srcs else "default"
        day = date.fromisoformat(c["start_date"]) if c.get("start_date") else b.ctx.now.date()
        is_now = c["start_time"] == _clock(b.ctx.now) and src.get("start_time") == "default"
        if day == b.ctx.now.date():
            key = ("chip.time.today_now" if src.get("start_date") == "said" else "chip.time.now") if is_now \
                else "chip.time.today"
            chips.append(_chip(b, "c_time", "time", key, source, time=c["start_time"]))
        else:
            chips.append(_chip(b, "c_time", "time", "chip.time.day", source, day=WEEKDAY_NAMES[day.weekday()],
                               time=c["start_time"]))
    chips.append(_chip(b, "c_shape", "shape", f"chip.shape.{c.get('shape', 'any')}", src.get("shape", "default")))
    if c.get("mode"):
        chips.append(_chip(b, "c_mode", "mode", f"chip.mode.{c['mode']}", src["mode"]))
    for name in PREFERENCES:
        if c.get(name):
            chips.append(_chip(b, f"c_{name}", name, f"chip.{name}.{c[name]}", src[name]))
    for i, a in enumerate(c.get("avoid_places") or []):
        chips.append(_chip(b, f"c_avoid_{i + 1}", "avoid", f"chip.avoid.{a['how']}", src["avoid_places"],
                           name=a["name"]))
    for i, a in enumerate(c.get("amenities") or []):
        chips.append(_chip(b, f"c_amenity_{i + 1}", "amenity", f"chip.amenity.{a['kind']}", src["amenities"],
                           mile=_fmt(a["at_mile"])))
    if c.get("reuse_route_id"):
        route = next((r["name"] for r in b.ctx.recent if r["id"] == c["reuse_route_id"]), c["reuse_route_id"])
        chips.append(_chip(b, "c_reuse", "reuse", "chip.reuse", src["reuse_route_id"], route=route))
    if c.get("reverse"):
        chips.append(_chip(b, "c_reverse", "reverse", "chip.reverse", src["reverse"]))
    return chips


def _chip_place(p: dict) -> dict | None:
    if p.get("lat") is None:
        return None
    return {"name": p.get("name"), "lat": p["lat"], "lon": p["lon"], "borough": p.get("borough"),
            "trust": p.get("trust", "listed"), "from": p.get("source")}


def build(ext: dict, ctx: Context, places: Places) -> dict:
    """The deterministic half: extraction + context -> the parsed event and its trace."""
    b = _Build(ctx, places)
    _cant(b, ext)
    _prefs(b, ext)
    asked: list[dict] = []
    vias: list = []

    def step(fn):
        """Run one rule; a question doesn't stop the others, so what can be resolved is kept (R3: the first
        question, in this order, is the one asked)."""
        try:
            return fn()
        except _Ask as a:
            asked.append(a.question)

    def end():
        if ext.get("end"):
            b.set("end_place", _resolve_place(b, ext["end"], "end", b.start_point, b.start_borough), "said")

    step(lambda: _time_and_day(b, ext.get("time"), ext.get("day")))
    step(lambda: _reuse(b, ext))
    vias = step(lambda: _vias(b, ext)) or []
    step(lambda: _start(b, ext, vias))
    if vias:
        b.set("via_places", [_ref(m) for _, m in vias], "said")
        if "scenery" not in b.constraints and any(m.kind in ("park", "water") for _, m in vias):
            b.set("scenery", "park_or_water", "said")  # "a few miles in the park" asks for park scenery
    if b.start_borough is None and ctx.location:
        b.start_point, b.start_borough = ctx.location, places.borough_at(*ctx.location)
    step(end)
    step(lambda: _distance(b, ext))
    step(lambda: _avoid_and_stops(b, ext))
    step(lambda: _planned(b, ext))
    question = asked[0] if asked else None
    if asked:  # only the asked question's strings reach the runner
        shown = {question["text"], *(o["text"] for o in question["options"])}
        dropped = {q["text"] for q in asked[1:]} | {o["text"] for q in asked[1:] for o in q["options"]}
        b.texts = [t for t in b.texts if t["text"] in shown or t["text"] not in dropped]
    if question is None:
        try:
            rc = RunConstraints(**b.constraints, sources={k: v for k, v in b.sources.items()
                                                          if "." not in k and v != "said"})
        except ValidationError as exc:
            return {"error": "parse_failed", "text": render("error.parse_failed"), "detail": str(exc)}
        b.constraints = rc.model_dump(mode="json", exclude_defaults=True)
        b.constraints["shape"] = rc.shape
    _notes(b) if question is None else None
    chips = _chips(b)
    parsed = {"event": "parsed", "v": 1, "parse_id": f"p_{secrets.token_hex(4)}", "chips": chips,
              "question": question, "cant": b.cant, "notes": b.notes, "constraints": b.constraints}
    trace = {"sources": dict(b.sources), "lookups": b.lookups, "routing_calls": 0, "texts": b.texts}
    return {"parsed": parsed, "trace": trace}


# ---- the Claude call --------------------------------------------------------------------------------------------


def cost_usd(model: str, usage) -> float:
    pin, pout, pwrite, pread = PRICES.get(model, PRICES[DEFAULT_MODEL])
    return ((usage.input_tokens or 0) * pin + (usage.output_tokens or 0) * pout
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0) * pwrite
            + (getattr(usage, "cache_read_input_tokens", 0) or 0) * pread) / 1e6


def extract(text: str, ctx: Context, client, model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT,
            thinking: str = DEFAULT_THINKING, log=None) -> tuple[dict | None, dict]:
    """Claude's half: the runner's words -> the record_request input. Returns (extraction or None, call stats)."""
    import anthropic

    t0 = time.perf_counter()
    stats = {"purpose": "parse", "prompt_version": PROMPT_VERSION, "model": model, "effort": effort,
             "thinking": thinking, "request_text": text}
    extra = {"thinking": {"type": "disabled"}} if thinking == "off" else {}
    ext = None
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=4000,
            system=[{"type": "text", "text": PROMPT, "cache_control": {"type": "ephemeral"}}],
            tools=[TOOL],
            tool_choice={"type": "auto"},  # forced tool choice is a 400 on Sonnet 5.5 / Opus 5.5
            output_config={"effort": effort},
            messages=[{"role": "user", "content": ctx.for_claude(text)}],
            **extra,
        )
        u = msg.usage
        stats |= {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                  "cache_read_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
                  "cache_write_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
                  "cost_usd": round(cost_usd(model, u), 8), "stop_reason": msg.stop_reason,
                  "request_id": getattr(msg, "_request_id", None)}
        if msg.stop_reason == "refusal":
            stats["error"] = "refusal"
        else:
            ext = next((blk.input for blk in msg.content
                        if blk.type == "tool_use" and blk.name == TOOL["name"]), None)
            if ext is None:
                stats["error"] = "no tool call"
    except anthropic.APIError as exc:
        stats["error"] = f"{exc.__class__.__name__}: {getattr(exc, 'message', exc)}"
    stats["latency_ms"] = round((time.perf_counter() - t0) * 1000)
    if log is not None:
        log(stats)
    return ext, stats


def parse(request: dict, *, client=None, places: Places | None = None, model: str = DEFAULT_MODEL,
          effort: str = DEFAULT_EFFORT, thinking: str = DEFAULT_THINKING, log=None) -> dict:
    """A contract request with `text` -> {"parsed", "trace"} or {"error", "text"}. See the module docstring."""
    text = (request.get("text") or "").strip()
    if not text:
        return {"error": "bad_request", "text": render("error.bad_request")}
    ctx = Context.from_request(request)
    own = None
    if client is None:
        import anthropic

        from api.env import load_env
        load_env()
        client = anthropic.Anthropic()
    if places is None:
        import psycopg

        from etl.load import database_url
        own = psycopg.connect(database_url())
        places = DbPlaces(own)
    if log is None:
        from api.llm_log import log_call
        log = log_call
    try:
        for attempt in range(1 + SCHEMA_RETRIES):
            ext, stats = extract(text, ctx, client, model=model, effort=effort, thinking=thinking, log=log)
            if ext is None:
                return {"error": "parse_failed", "text": render("error.parse_failed"), "stats": stats}
            dropped: list = []
            try:
                ext = _clean(_conform(ext, TOOL["input_schema"], dropped=dropped))
                if dropped:
                    stats["dropped"] = dropped
                stats["attempts"] = attempt + 1
                break
            except SchemaError as exc:  # a malformed tool call (no strict mode): ask once more
                stats["error"] = f"schema: {exc}"
        else:
            return {"error": "parse_failed", "text": render("error.parse_failed"), "stats": stats}
        out = build(ext, ctx, places)
        out.setdefault("trace", {})["stats"] = stats
        out["trace"]["extraction"] = ext
        return out
    finally:
        if own is not None:
            own.close()
