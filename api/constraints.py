"""What the runner asked for: the RunConstraints schema (decision 009).

Claude's parse step fills this in from plain English; validation failures become a clarifying question, never a
guess (product rule 4). The parsed result is shown back to the runner with `describe`, so they can correct it.
Everything downstream (routing, scoring, ranking) reads this schema and nothing else from the request.

Hard limits (distance, shape, places to avoid, amenities) are checked and reported when missed. Preferences are
soft: they set the ranking weights. A preference left unstated comes from the Training or Exploring preset, or from a
neutral default, and `resolve_preferences` records which.
"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Mode(StrEnum):
    TRAINING = "training"  # competitive: pace matters, so crowds, lights and turns cost more
    EXPLORING = "exploring"  # casual: scenery matters more than pace


class Lights(StrEnum):
    WAITS = "waits"  # stops at a red to keep going straight
    ZIGZAGS = "zigzags"  # turns with whatever is green


Crowds = Literal["avoid", "some", "dont_mind"]
Scenery = Literal["park_or_water", "some", "dont_mind"]
Surface = Literal["paths", "any"]
Turns = Literal["fewer", "dont_mind"]
Familiar = Literal["favor", "some", "new"]  # "matches routes you run": turn it up, leave it, or ask for new ground
PREFERENCES = ("lights", "crowds", "scenery", "surface", "turns", "familiar")

# Starting points from discovery (docs/discovery/summary.md, theme 2); to be tuned with ratings.
PRESETS: dict[Mode, dict] = {
    Mode.TRAINING: {"lights": Lights.WAITS, "crowds": "avoid", "scenery": "some", "surface": "any", "turns": "fewer",
                    "familiar": "favor"},
    Mode.EXPLORING: {"lights": Lights.ZIGZAGS, "crowds": "dont_mind", "scenery": "park_or_water", "surface": "any",
                     "turns": "dont_mind", "familiar": "some"},
}
DEFAULTS = {"lights": Lights.ZIGZAGS, "crowds": "some", "scenery": "some", "surface": "any", "turns": "dont_mind",
            "familiar": "some"}


class AmenityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["restroom", "water"]
    at_mile: float = Field(ge=0)
    within_mi: float = Field(default=0.5, gt=0, le=2)


class RunConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Hard limits
    start_address: str | None = None
    use_my_location: bool = False
    distance_mi: float = Field(ge=0.5, le=30)
    tolerance_pct: float = Field(default=5, gt=0, le=25)
    shape: Literal["loop", "out_and_back", "any"] = "any"  # unstated: offer both (out-and-backs are common, decision 010)
    avoid_places: list[str] = Field(default_factory=list)  # names only; code resolves them to areas
    amenities: list[AmenityRequest] = Field(default_factory=list)
    # HH:MM, local time. The departure-hour input for hour-dependent dimensions (crowds, restroom hours); none of
    # those is scored yet, so it is carried and shown, not used for ranking (decision 014).
    start_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    start_date: date | None = None  # with start_time, gives weekday / Saturday / Sunday for crowds (decision 016)

    # Preferences (None = not stated)
    mode: Mode | None = None
    lights: Lights | None = None
    crowds: Crowds | None = None
    scenery: Scenery | None = None
    surface: Surface | None = None
    turns: Turns | None = None
    familiar: Familiar | None = None

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
        if bool(self.start_address) == self.use_my_location:
            raise ValueError("give exactly one start: an address or use_my_location")
        for a in self.amenities:
            if a.at_mile > self.distance_mi:
                raise ValueError(f"{a.kind} at mile {a.at_mile:g} is past the end of a {self.distance_mi:g} mi run")
        return self


@dataclass(frozen=True)
class Preferences:
    values: dict  # preference -> value, every preference filled in
    sources: dict  # preference -> "stated" | "preset" | "default"


def resolve_preferences(c: RunConstraints) -> Preferences:
    preset = PRESETS.get(c.mode) if c.mode else None
    values, sources = {}, {}
    for name in PREFERENCES:
        stated = getattr(c, name)
        if stated is not None:
            values[name], sources[name] = stated, "stated"
        elif preset is not None:
            values[name], sources[name] = preset[name], "preset"
        else:
            values[name], sources[name] = DEFAULTS[name], "default"
    return Preferences(values, sources)


LABELS = {
    "lights": {Lights.WAITS: "waits for the light", Lights.ZIGZAGS: "zig-zags with the lights"},
    "crowds": {"avoid": "avoid", "some": "some", "dont_mind": "don't mind"},
    "scenery": {"park_or_water": "park or water", "some": "some", "dont_mind": "don't mind"},
    "surface": {"paths": "paths", "any": "any"},
    "turns": {"fewer": "fewer", "dont_mind": "don't mind"},
    "familiar": {"favor": "favor routes you run", "some": "some", "new": "new ground"},
}


SAID, DEFAULT = "you said", "default"


def _said(c: RunConstraints, field: str) -> bool:
    """Whether the request stated this field (passed with a value), rather than leaving the schema default."""
    return field in c.model_fields_set and getattr(c, field) is not None


def request_items(c: RunConstraints) -> list[dict]:
    """The parsed request, one item per field, each with where it came from (decision 020): "you said", the
    "<Mode> preset", or "default". `describe` prints these; the UI shows them as chips."""
    mode_name = c.mode.value.capitalize() if c.mode else ""
    items = [
        {"key": "start", "title": "Start", "value": c.start_address or "your location", "origin": SAID},
        {"key": "distance", "title": "Distance", "value": f"{c.distance_mi:g} mi", "origin": SAID},
        {"key": "tolerance", "title": "Within", "value": f"{c.tolerance_pct:g}%",
         "origin": SAID if _said(c, "tolerance_pct") else DEFAULT},
        {"key": "shape", "title": "Shape", "value": c.shape.replace("_", " "),
         "origin": SAID if _said(c, "shape") else DEFAULT},
        {"key": "mode", "title": "Mode", "value": mode_name or "not set", "origin": SAID if c.mode else DEFAULT},
    ]
    prefs = resolve_preferences(c)
    origin = {"stated": SAID, "preset": f"{mode_name} preset", "default": DEFAULT}
    titles = {"familiar": "Matches routes you run"}
    for name in PREFERENCES:
        items.append({"key": name, "title": titles.get(name, name.capitalize()),
                      "value": LABELS[name][prefs.values[name]], "origin": origin[prefs.sources[name]]})
    if c.avoid_places:
        items.append({"key": "avoid", "title": "Avoid", "value": ", ".join(c.avoid_places), "origin": SAID})
    for a in c.amenities:
        items.append({"key": "amenity", "title": "Stop", "value": f"{a.kind} near mile {a.at_mile:g} "
                      f"(within {a.within_mi:g} mi)", "origin": SAID})
    if c.start_time:
        items.append({"key": "start_time", "title": "Start time",
                      "value": f"{c.start_time} (hour {c.start_hour}; sets the crowd band)", "origin": SAID})
    else:
        items.append({"key": "start_time", "title": "Start time", "value": "not set, so crowds are not scored",
                      "origin": DEFAULT})
    if c.start_date:
        items.append({"key": "start_date", "title": "Day", "value": f"{c.start_date:%A %Y-%m-%d}",
                      "origin": SAID if _said(c, "start_date") else DEFAULT})
    return items


def describe(c: RunConstraints) -> list[str]:
    """The parsed request in plain words, for the runner to check before routes are built."""
    return [f"{i['title']}: {i['value']} ({i['origin']})" for i in request_items(c)]
