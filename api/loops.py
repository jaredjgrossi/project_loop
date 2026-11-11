"""Around or through: how a run uses a via place (decision 035).

Claude records the runner's word for each via ("around", "loop of", "lap of", "through", "in"...); code sets the
mode from it, never the model:
- a word with "through", "via", "past", "across", "in", "on", "along" (and the like) passes the place: `through`;
- otherwise "around", "loop", "lap" or "circle" runs a full lap of it: `around`;
- a place on the curated list of running loops (etl/curated/running_loops.json) that means its loop when named on
  its own ("Central park reservor") is `around` with no word; so is any of a loop's own names ("the Prospect Park
  loop", "McCarren track");
- anything else stays `through`.
An around via runs the curated loop when the place has one, or else the place's outline, for a park or water only.
A loop the router can't run yet (McCarren's track) stays `through`, with a can't-do line (rule 3).
"""

import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

CURATED = Path(__file__).resolve().parent.parent / "etl" / "curated" / "running_loops.json"
THROUGH_WORDS = frozenset({"through", "thru", "via", "past", "across", "cross", "crossing", "in", "into", "inside",
                           "on", "along", "by", "to", "from"})
AROUND_WORDS = frozenset({"around", "round", "loop", "loops", "lap", "laps", "circle", "circuit"})
LAP_KINDS = ("park", "water")  # places with an outline to run around


@dataclass(frozen=True)
class Mode:
    mode: str  # "through" | "around"
    loop: str | None = None  # a curated loop's id
    cant: str | None = None  # a can't-do line's copy key, when the lap can't be run
    name: str | None = None  # what to call the lap: the curated loop's name, or the place's


def _norm(text: str) -> str:
    text = re.sub(r"[’'`]s\b", "s", text.lower())
    words = re.findall(r"[a-z0-9]+", text)
    return " ".join(w for w in words if w not in ("the", "a", "an"))


@cache
def loops() -> tuple[dict, ...]:
    return tuple(json.loads(CURATED.read_text())["loops"])


def loop_by_id(loop_id: str) -> dict | None:
    return next((lp for lp in loops() if lp["id"] == loop_id), None)


def loop_named(name: str) -> dict | None:
    """The curated loop a via name is the loop's own name for ("the Reservoir", "Prospect Park loop")."""
    n = _norm(name)
    return next((lp for lp in loops() if n in {_norm(x) for x in lp["names"]}), None)


def place_for(loop: dict) -> str:
    """The places-table name to look up for a loop named on its own."""
    return loop.get("place_for_names") or loop["places"][0]


def _loop_at(place: str) -> dict | None:
    n = _norm(place)
    return next((lp for lp in loops() if n in {_norm(x) for x in lp["places"]}), None)


def word_mode(word: str | None) -> str | None:
    """'through' or 'around' from the runner's word, or None when the word doesn't say."""
    tokens = set(_norm(word or "").split())
    if tokens & THROUGH_WORDS:
        return "through"
    if tokens & AROUND_WORDS:
        return "around"
    return None


def mode_for(word: str | None, said_name: str, matched: str, kind: str | None) -> Mode:
    """The mode for a via the runner named `said_name`, matched to the place `matched` of `kind`."""
    by_word = word_mode(word)
    named = loop_named(said_name)
    at = named or _loop_at(matched) or _loop_at(said_name)
    if by_word == "through":
        return Mode("through")
    around = by_word == "around" or named is not None or bool(at and at.get("around_alone"))
    if not around:
        return Mode("through")
    if at is not None:
        if at.get("geometry") is None:
            return Mode("through", cant="cant.lap_unrouted", name=at["name"])
        return Mode("around", at["id"], name=at["name"])
    if kind in LAP_KINDS:
        return Mode("around", name=matched)
    return Mode("through", cant="cant.around_shape", name=matched)
