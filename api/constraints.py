"""What the runner asked for: the RunConstraints schema (decision 009).

Claude's parse step fills this in from plain English; validation failures become a clarifying question, never a
guess (product rule 4). The parsed result is shown back to the runner with `describe`, so they can correct it.
Everything downstream (routing, scoring, ranking) reads this schema and nothing else from the request.

Hard limits (distance, shape, places to avoid, amenities) are checked and reported when missed. Preferences are
soft: they set the ranking weights. A preference left unstated comes from the Training or Exploring preset, or from a
neutral default, and `resolve_preferences` records which.
"""

from dataclasses import dataclass
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

    # Preferences (None = not stated)
    mode: Mode | None = None
    lights: Lights | None = None
    crowds: Crowds | None = None
    scenery: Scenery | None = None
    surface: Surface | None = None
    turns: Turns | None = None
    familiar: Familiar | None = None

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


def describe(c: RunConstraints) -> list[str]:
    """The parsed request in plain words, for the runner to check before routes are built."""
    lines = [
        f"Start: {c.start_address or 'your location'}",
        f"Distance: {c.distance_mi:g} mi (within {c.tolerance_pct:g}%)",
        f"Shape: {c.shape.replace('_', ' ')}",
        f"Mode: {c.mode.value.capitalize() if c.mode else 'not set'}",
    ]
    prefs = resolve_preferences(c)
    origin = {"stated": "you said", "preset": f"{c.mode.value.capitalize() if c.mode else ''} preset", "default": "default"}
    titles = {"familiar": "Matches routes you run"}
    for name in PREFERENCES:
        title = titles.get(name, name.capitalize())
        lines.append(f"{title}: {LABELS[name][prefs.values[name]]} ({origin[prefs.sources[name]]})")
    if c.avoid_places:
        lines.append(f"Avoid: {', '.join(c.avoid_places)}")
    for a in c.amenities:
        lines.append(f"Stop: {a.kind} near mile {a.at_mile:g} (within {a.within_mi:g} mi)")
    if c.start_time:
        lines.append(f"Start time: {c.start_time} (hour {c.start_hour}; nothing hour-dependent is scored yet)")
    return lines
