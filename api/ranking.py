"""The combined ranking (decisions 009 and 010): score a candidate route against the runner's preferences.

Each dimension says how its value was produced: `measured` (from geometry or a dataset), `estimate` (from a model
with assumptions) or `not_scored` (no data yet, so it carries no weight; it is listed, never treated as zero).
The total is the weighted mean of the scored dimensions' fit (0 worst, 1 best), times 100.

The weights are PROVISIONAL. Turns and retracing in particular stay untuned until they are calibrated against real
runs (decision 010): the reviewer's own runs show out-and-backs and retracing are normal, so neither may be locked in.
"""

from dataclasses import dataclass
from typing import Literal

from api.constraints import Lights
from api.route_context import ContextScores
from api.shape import ShapeMetrics

Status = Literal["measured", "estimate", "not_scored"]
Kind = Literal["loop", "out_and_back", "lollipop"]  # lollipop: out, around and back; ranked like an out-and-back

# Dimensions the plan calls for that have no scorer yet (HANDOFF.md, Phase 2 order).
NOT_YET_SCORED = {
    "closures": "Closures",
    "roadway": "Running in the roadway",
}
CONTEXT_LABELS = {"park_water": "Park and waterfront", "signals": "Traffic signals", "familiar": "Matches routes you run",
                  "crowds": "Crowds"}

# Decision 008's shape weights, plus the context dimensions from decision 011; provisional, see the module docstring.
BASE_WEIGHTS = {"turns": 40.0, "straight": 25.0, "loop_shape": 25.0, "retrace": 10.0,
                "park_water": 30.0, "signals": 25.0, "familiar": 20.0,
                "crowds": 25.0}  # decision 016: new, provisional; no other weight changed
SIGNALS_WORST_PER_MILE = 20.0  # a Manhattan avenue sidewalk: a signal every short block


@dataclass(frozen=True)
class Dimension:
    key: str
    label: str
    status: Status
    value: str  # for display; empty when not scored
    fit: float | None  # 0 to 1; None when not scored
    weight: float  # 0 when not scored
    provisional: bool = True


@dataclass(frozen=True)
class Ranking:
    score: float  # 0 to 100
    dimensions: tuple[Dimension, ...]

    def scored(self) -> list[Dimension]:
        return [d for d in self.dimensions if d.status != "not_scored"]

    def not_scored(self) -> list[Dimension]:
        return [d for d in self.dimensions if d.status == "not_scored"]


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def weights_for(prefs: dict) -> dict[str, float]:
    """Weights from resolved preferences (constraints.resolve_preferences().values)."""
    w = dict(BASE_WEIGHTS)
    w["turns"] *= 1.5 if prefs["turns"] == "fewer" else 0.5
    # A runner who waits at lights wants long straight runs and few signals; a zig-zagger turns at a red anyway.
    waits = prefs["lights"] == Lights.WAITS
    w["straight"] *= 1.5 if waits else 0.75
    w["signals"] *= 2.0 if waits else 0.5
    w["park_water"] *= {"park_or_water": 2.0, "some": 1.0, "dont_mind": 0.25}[prefs["scenery"]]
    w["familiar"] *= 2.0 if prefs["familiar"] == "favor" else 1.0
    w["crowds"] *= {"avoid": 2.0, "some": 1.0, "dont_mind": 0.25}[prefs["crowds"]]
    return w


def _context_dimensions(context: ContextScores | None, prefs: dict, w: dict) -> list[Dimension]:
    if context is None:
        return [Dimension(k, label, "not_scored", "", None, 0.0) for k, label in CONTEXT_LABELS.items()]
    dims = [
        Dimension("park_water", CONTEXT_LABELS["park_water"], "measured",
                  f"{context.park_or_water_pct:.0f}% in a park or by the water",
                  _clamp(context.park_or_water_pct / 60), w["park_water"]),
        Dimension("signals", CONTEXT_LABELS["signals"], "measured",
                  f"{context.signals_per_mile:.1f} signalized crosswalks per mile",
                  _clamp(1 - context.signals_per_mile / SIGNALS_WORST_PER_MILE), w["signals"]),
    ]
    # Scored for every candidate or for none, decided by the start moment, so no route gains by being scorable.
    # Only known-busy distance costs a route; distance with no crowd data is neutral, neither quiet nor busy.
    if context.crowd_not_scored_pct is None or context.crowd_start_band is None:
        dims.append(Dimension("crowds", CONTEXT_LABELS["crowds"], "not_scored", context.crowd_reason or "", None, 0.0))
    else:
        dims.append(Dimension("crowds", CONTEXT_LABELS["crowds"], "estimate",
                              f"{context.crowd_high_pct:.0f}% of the route busy ({context.crowd_band or 'no sidewalks'}); "
                              f"{context.crowd_not_scored_pct:.0f}% has no crowd data, counted as neither quiet nor busy",
                              _clamp(1 - context.crowd_high_pct / 100), w["crowds"]))
    if context.familiar_pct is None:
        dims.append(Dimension("familiar", CONTEXT_LABELS["familiar"], "not_scored", "", None, 0.0))
    else:
        share = context.familiar_pct / 100
        dims.append(Dimension("familiar", CONTEXT_LABELS["familiar"], "measured",
                              f"{context.familiar_pct:.0f}% on ways you have run 2+ times",
                              1 - share if prefs["familiar"] == "new" else share, w["familiar"]))
    return dims


def rank(kind: Kind, shape: ShapeMetrics, prefs: dict, context: ContextScores | None = None) -> Ranking:
    w = weights_for(prefs)
    dims = [
        Dimension("turns", "Turns", "measured", f"{shape.turns_per_mile:.1f} per mile",
                  _clamp(1 - (shape.turns_per_mile - 1) / 9), w["turns"]),
        Dimension("straight", "Straight runs", "measured", f"{shape.pct_in_long_runs:.0f}% on runs of 500 m or more",
                  _clamp(shape.pct_in_long_runs / 100), w["straight"]),
    ]
    if kind == "loop":
        # An out-and-back retraces by design and has no area, so these only apply to loops; an open (trimmed) loop
        # has no area either.
        if shape.compactness is not None:
            dims.append(Dimension("loop_shape", "Loop shape", "measured", f"compactness {shape.compactness:.2f}",
                                  _clamp(shape.compactness / 0.7), w["loop_shape"]))
        dims.append(Dimension("retrace", "Retracing", "measured", f"{shape.retraced_pct:.0f}% retraced",
                              1 - _clamp(shape.retraced_pct / 15), w["retrace"]))
    dims += _context_dimensions(context, prefs, w)
    dims += [Dimension(k, label, "not_scored", "", None, 0.0) for k, label in NOT_YET_SCORED.items()]
    total_w = sum(d.weight for d in dims)
    score = 100 * sum(d.fit * d.weight for d in dims if d.fit is not None) / total_w
    return Ranking(score, tuple(dims))
