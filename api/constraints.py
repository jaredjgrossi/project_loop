"""What the runner asked for: the RunConstraints schema (decisions 009, 027).

Claude's parse step fills this in from plain English; validation failures become a clarifying question, never a
guess (product rule 4). The parsed result is shown back to the runner as chips, so they can correct it. Everything
downstream (routing, scoring, ranking) reads this schema and nothing else from the request.

Hard limits (distance, shape, start, end, via, places to avoid, amenities) are checked and reported when missed.
Preferences are soft: they set the ranking weights. A preference left unstated comes from the Training or Exploring
preset, or from a neutral default, and `resolve_preferences` records which.

Where each value came from is part of the data (decision 027), in the contract's words: "said", "preset", "default"
or "usual" (from the runner's profile or recent routes). A field passed in counts as "said" unless `sources` says
otherwise; `sources` travels with the constraints, so a chip edit sent back from the phone keeps it. `api/copy.py`
turns these keys into display words.

Phase 3 adds fields the engine can't build yet; `unsupported` lists them so a caller says so instead of quietly
dropping them (product rule 3).
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from api.copy import render, source_word


class Mode(StrEnum):
    TRAINING = "training"  # competitive: pace matters, so crowds, lights and turns cost more
    EXPLORING = "exploring"  # casual: scenery matters more than pace


class Lights(StrEnum):
    WAITS = "waits"  # stops at a red to keep going straight
    ZIGZAGS = "zigzags"  # turns with whatever is green


Source = Literal["said", "preset", "default", "usual"]
Trust = Literal["verified", "listed", "seasonal_or_closed"]
Crowds = Literal["avoid", "some", "dont_mind"]
Scenery = Literal["park_or_water", "some", "dont_mind"]
Surface = Literal["paths", "any"]
Turns = Literal["fewer", "dont_mind"]
Familiar = Literal["favor", "some", "new"]  # "matches routes you run": turn it up, leave it, or ask for new ground
Hills = Literal["avoid", "dont_mind"]  # "flat" is avoid; scored from elevation in Phase 3, step 9
PREFERENCES = ("lights", "crowds", "scenery", "surface", "turns", "familiar", "hills")

# Starting points from discovery (docs/discovery/summary.md, theme 2); to be tuned with ratings. Hills stays neutral
# in both presets until it is scored (step 9), so adding it changes no ranking.
PRESETS: dict[Mode, dict] = {
    Mode.TRAINING: {"lights": Lights.WAITS, "crowds": "avoid", "scenery": "some", "surface": "any", "turns": "fewer",
                    "familiar": "favor", "hills": "dont_mind"},
    Mode.EXPLORING: {"lights": Lights.ZIGZAGS, "crowds": "dont_mind", "scenery": "park_or_water", "surface": "any",
                     "turns": "dont_mind", "familiar": "some", "hills": "dont_mind"},
}
DEFAULTS = {"lights": Lights.ZIGZAGS, "crowds": "some", "scenery": "some", "surface": "any", "turns": "dont_mind",
            "familiar": "some", "hills": "dont_mind"}


class PlaceRef(BaseModel):
    """A place the runner named, resolved by code (rule R12): a places-table match, a geocoded address, or a saved
    place from the profile. Coordinates come from the server's lookup, never from Claude."""
    model_config = ConfigDict(extra="forbid")

    kind: Literal["place", "address", "saved"]
    name: str | None = None
    id: str | None = None  # saved places: the profile's id ("home")
    borough: str | None = None  # the chip always names it (R19)
    lat: float | None = Field(default=None, ge=40.4, le=41.0)  # New York City only
    lon: float | None = Field(default=None, ge=-74.3, le=-73.6)
    source: str | None = None  # "OpenStreetMap", "NYC GeoSearch", "profile"
    trust: Trust | None = None

    @model_validator(mode="after")
    def _check(self) -> "PlaceRef":
        if self.kind == "saved":
            if not self.id:
                raise ValueError("a saved place needs its id")
        elif not (self.name and self.borough and self.lat is not None and self.lon is not None):
            raise ValueError(f"a resolved {self.kind} needs its name, borough and coordinates")
        return self

    def display(self) -> str:
        if self.kind == "saved":
            return render("request.saved_place", name=self.name or self.id.capitalize())
        return render("request.place", name=self.name, borough=self.borough)


class AvoidPlace(BaseModel):
    """Somewhere not to run. A street is avoided along its length; crossing it is fine (R15)."""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    how: Literal["along", "area"] = "area"
    place: PlaceRef | None = None


class AmenityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["restroom", "water"]
    at_mile: float = Field(ge=0)
    within_mi: float = Field(default=0.5, gt=0, le=2)


class RunConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Hard limits. Exactly one start.
    start_address: str | None = None  # an unresolved address, geocoded at build time (the CLI's way in)
    use_my_location: bool = False
    start_place: PlaceRef | None = None
    end_place: PlaceRef | None = None  # A to B (Phase 3, step 7)
    via_places: list[PlaceRef] = Field(default_factory=list, max_length=5)  # through or along, in order (step 8)
    # Optional only when an end or a reused route sets the length (R10).
    distance_mi: float | None = Field(default=None, ge=0.5, le=30)
    tolerance_pct: float = Field(default=5, gt=0, le=25)
    shape: Literal["loop", "out_and_back", "any"] = "any"  # unstated: offer both (out-and-backs are common, decision 010)
    avoid_places: list[AvoidPlace] = Field(default_factory=list)
    amenities: list[AmenityRequest] = Field(default_factory=list)
    # HH:MM, local time. The departure-hour input for hour-dependent dimensions (crowds, restroom hours).
    start_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    start_date: date | None = None  # with start_time, gives weekday / Saturday / Sunday for crowds (decision 016)

    # Past routes (step 10): rebuild a recent route for now, optionally the other way round.
    reuse_route_id: str | None = None
    reverse: bool = False

    # Preferences (None = not stated)
    mode: Mode | None = None
    lights: Lights | None = None
    crowds: Crowds | None = None
    scenery: Scenery | None = None
    surface: Surface | None = None
    turns: Turns | None = None
    familiar: Familiar | None = None
    hills: Hills | None = None

    # A second run in the same request (D6, R18): built for its own day and saved (step 10).
    planned: "RunConstraints | None" = None

    # Where a value came from, for fields that weren't simply said: {"distance_mi": "usual"} (decision 027).
    sources: dict[str, Source] = Field(default_factory=dict)

    @field_validator("avoid_places", mode="before")
    @classmethod
    def _names_are_areas(cls, v):
        return [{"name": a} if isinstance(a, str) else a for a in v or []]

    def start_moment(self) -> datetime | None:
        """The start as a local date and time, when both are known."""
        if self.start_time is None or self.start_date is None:
            return None
        return datetime.combine(self.start_date, datetime.strptime(self.start_time, "%H:%M").time())

    @property
    def start_hour(self) -> int | None:
        """Hour of day, 0-23, from start_time."""
        return int(self.start_time[:2]) if self.start_time else None

    @model_validator(mode="after")
    def _check(self) -> "RunConstraints":
        if sum([bool(self.start_address), self.use_my_location, self.start_place is not None]) != 1:
            raise ValueError("give exactly one start: an address, use_my_location or a start place")
        if self.distance_mi is None and self.end_place is None and self.reuse_route_id is None:
            raise ValueError("a distance is needed unless the run ends somewhere else or reuses a route")
        if self.distance_mi is not None:
            for a in self.amenities:
                if a.at_mile > self.distance_mi:
                    raise ValueError(f"{a.kind} at mile {a.at_mile:g} is past the end of a {self.distance_mi:g} mi run")
        if self.reverse and self.reuse_route_id is None:
            raise ValueError("reverse needs a route to reverse (reuse_route_id)")
        if self.planned is not None:
            if self.planned.planned is not None:
                raise ValueError("a planned run can't hold another planned run")
            if self.planned.start_date is None:
                raise ValueError("a planned run needs its day (start_date)")
        unknown = set(self.sources) - (set(type(self).model_fields) - {"sources"})
        if unknown:
            raise ValueError(f"unknown field in sources: {', '.join(sorted(unknown))}")
        return self


RunConstraints.model_rebuild()


@dataclass(frozen=True)
class Preferences:
    values: dict  # preference -> value, every preference filled in
    sources: dict  # preference -> "said" | "usual" | "preset" | "default"


def resolve_preferences(c: RunConstraints) -> Preferences:
    preset = PRESETS.get(c.mode) if c.mode else None
    values, sources = {}, {}
    for name in PREFERENCES:
        stated = getattr(c, name)
        if stated is not None:
            values[name], sources[name] = stated, c.sources.get(name, "said")
        elif preset is not None:
            values[name], sources[name] = preset[name], "preset"
        else:
            values[name], sources[name] = DEFAULTS[name], "default"
    return Preferences(values, sources)


def _is_set(c: RunConstraints, name: str) -> bool:
    value = getattr(c, name)
    if value is None or value is False or value == []:
        return False
    return name in c.model_fields_set or name in c.sources


def field_sources(c: RunConstraints, prefix: str = "") -> dict[str, str]:
    """Every field that holds a value, with where it came from. A planned run's fields are 'planned.<field>'."""
    out = {}
    for name in type(c).model_fields:
        if name == "sources" or not _is_set(c, name):
            continue
        if name == "planned":
            out[prefix + name] = c.sources.get(name, "said")
            out |= field_sources(c.planned, prefix=f"{prefix}planned.")
            continue
        out[prefix + name] = c.sources.get(name, "said" if name in c.model_fields_set else "default")
    return out


def with_default_date(c: RunConstraints, now: datetime) -> RunConstraints:
    """A start time with no day means the next time that clock time comes round (decision 020): today if it is
    still ahead of `now` (New York local time), else tomorrow. The day is labeled "default". Without a day, crowds
    can't be scored, since weekday, Saturday and Sunday differ (decision 016)."""
    if c.start_time is None or c.start_date is not None:
        return c
    at = datetime.strptime(c.start_time, "%H:%M").time()
    day = now.date() if at >= now.time().replace(second=0, microsecond=0) else now.date() + timedelta(days=1)
    fields = c.model_dump(exclude_unset=True) | {"start_date": day, "sources": {**c.sources, "start_date": "default"}}
    return RunConstraints(**fields)


_ENGINE_LATER = (  # (key, test): Phase 3 fields the engine can't build yet, in the order a caller reports them
    ("end_place", lambda c: c.end_place is not None),  # step 7
    ("via_places", lambda c: bool(c.via_places)),  # step 8
    ("hills", lambda c: resolve_preferences(c).values["hills"] != "dont_mind"),  # step 9
    ("avoid_along", lambda c: any(a.how == "along" for a in c.avoid_places)),  # no step yet (R15)
    ("reuse_route_id", lambda c: c.reuse_route_id is not None),  # step 10
    ("planned", lambda c: c.planned is not None),  # step 10
)


def unsupported(c: RunConstraints) -> list[str]:
    """Fields set on `c` that the engine can't build yet. A caller must say so, never drop them (rule 3)."""
    return [key for key, test in _ENGINE_LATER if test(c)]


def request_items(c: RunConstraints) -> list[dict]:
    """The parsed request for the route file (decision 020), one item per field, each with where it came from:
    "you said", the "<Mode> preset", "your usual" or "default". `describe` prints these. The keys and shape stay as
    the iPhone app's fixture reads them; every string comes from api/copy.py."""
    mode = c.mode.value if c.mode else None
    src = field_sources(c)

    def origin(*fields: str, fallback: str = "default") -> str:
        return source_word(next((src[f] for f in fields if f in src), fallback), mode)

    def item(key: str, value: str, origin_word: str) -> dict:
        return {"key": key, "title": render(f"request.title.{key}"), "value": value, "origin": origin_word}

    if c.start_place is not None:
        start = c.start_place.display()
    elif c.start_address:
        start = c.start_address
    else:
        start = render("request.start.my_location")
    if c.distance_mi is not None:
        distance = render("request.distance", miles=f"{c.distance_mi:g}")
    else:
        distance = render("request.distance.reused" if c.reuse_route_id else "request.distance.shortest")
    items = [item("start", start, origin("start_place", "start_address", "use_my_location", fallback="said"))]
    if c.end_place is not None:
        items.append(item("end", c.end_place.display(), origin("end_place")))
    items += [item("via", v.display(), origin("via_places")) for v in c.via_places]
    items += [
        item("distance", distance, origin("distance_mi", fallback="said" if c.distance_mi is not None else "default")),
        item("tolerance", render("request.tolerance", pct=f"{c.tolerance_pct:g}"), origin("tolerance_pct")),
        item("shape", c.shape.replace("_", " "), origin("shape")),
        item("mode", mode.capitalize() if mode else render("request.mode.unset"), origin("mode")),
    ]
    if c.reuse_route_id:
        items.append(item("reuse", render("request.reuse", route=c.reuse_route_id), origin("reuse_route_id")))
    if c.reverse:
        items.append(item("reverse", render("request.reverse"), origin("reverse")))
    prefs = resolve_preferences(c)
    for name in PREFERENCES:
        items.append(item(name, render(f"pref.{name}.{prefs.values[name]}"), source_word(prefs.sources[name], mode)))
    if c.avoid_places:
        names = [render("request.avoid.along", name=a.name) if a.how == "along" else a.name for a in c.avoid_places]
        items.append(item("avoid", ", ".join(names), origin("avoid_places")))
    for a in c.amenities:
        items.append(item("amenity", render("request.amenity", kind=a.kind, mile=f"{a.at_mile:g}",
                                            within=f"{a.within_mi:g}"), origin("amenities")))
    if c.start_time:
        items.append(item("start_time", render("request.start_time", time=c.start_time, hour=c.start_hour),
                          origin("start_time")))
    else:
        items.append(item("start_time", render("request.start_time.unset"), source_word("default")))
    if c.start_date:
        items.append(item("start_date", render("request.start_date", day=f"{c.start_date:%A %Y-%m-%d}"),
                          origin("start_date")))
    return items


def describe(c: RunConstraints) -> list[str]:
    """The parsed request in plain words, for the runner to check before routes are built."""
    return [f"{i['title']}: {i['value']} ({i['origin']})" for i in request_items(c)]
