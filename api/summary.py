"""The route summary for the UI (decision 020): every headline value with its unit, trust label and source.

Built from what make_loop already has for a saved route: the candidate (distance, context, ranking), its stretch
features (api/segments.py), its marker features (api/markers.py) and its elevation profile. The shares and the lights
are sums over the stretches, so the stretches always add up to the summary. Labels:
- `measured`: straight from geometry or a dataset;
- `estimate`: from a model with assumptions (climb, wait, crowds);
- `not_scored`: no data, with the reason when there is one; never shown as zero;
- `provisional`: the ranking score, whose weights are not calibrated yet (decision 010).
"""

from api.generate import Candidate
from api.route_context import COMPOSITION
from api.segments import COMPOSITION_SOURCE, SIGNALS_COUNTED

METERS_PER_MILE = 1609.344
DISTANCE_SOURCE = "route geometry (GraphHopper)"
SIGNALS_SOURCE = "OpenStreetMap crosswalks tagged crossing=traffic_signals that the route walks"


def _value(value, unit: str | None, status: str, source: str, **extra) -> dict:
    out = {"value": value, "status": status, "source": source, **extra}
    if unit:
        out["unit"] = unit
    return out


def _not_scored(reason: str) -> dict:
    return {"value": None, "status": "not_scored", "reason": reason}


def route_summary(c: Candidate, stretches: list[dict], markers: list[dict], elevation: dict) -> dict:
    # The geometry's own length, as the mile markers and stretches measure it; GraphHopper's figure differs slightly.
    miles = c.shape.distance_miles
    out = {
        "distance": _value(round(miles, 2), "mi", "measured", DISTANCE_SOURCE, meters=round(miles * METERS_PER_MILE),
                           router_meters=round(c.route.distance_m)),
        "kind": c.kind,
    }

    comps = [s["properties"].get("composition", {}) for s in stretches]
    if comps and all(x.get("status") == "measured" for x in comps):
        meters = {k: sum(x[f"{k}_m"] for x in comps) for k in COMPOSITION}
        total = sum(meters.values())
        for k in COMPOSITION:
            out[f"{k}_pct"] = _value(round(100 * meters[k] / total, 1), "%", "measured", COMPOSITION_SOURCE)
    else:
        for k in COMPOSITION:
            out[f"{k}_pct"] = _not_scored("no stretches for this route")

    signals = [s["properties"].get("signals", {}) for s in stretches]
    if signals and all(x.get("status") == "measured" for x in signals):
        n = sum(x["value"] for x in signals)
        out["signalized_crossings"] = _value(n, None, "measured", SIGNALS_SOURCE, counted=SIGNALS_COUNTED)
        out["lights_per_mile"] = _value(round(n / miles, 1), "per mi", "measured", SIGNALS_SOURCE,
                                        counted=SIGNALS_COUNTED)
    else:
        out["signalized_crossings"] = out["lights_per_mile"] = _not_scored("no stretches for this route")
    ctx = c.context
    out["ranking_signals_per_mile"] = (
        _value(round(ctx.signals_per_mile, 1), "per mi", "measured", SIGNALS_SOURCE,
               counted="each signalized crosswalk once, however often it is crossed: the ranking's input")
        if ctx is not None else _not_scored("route context not scored"))

    if elevation.get("status") == "estimate":
        out["climb"] = _value(elevation["gain_m"], "m", "estimate", elevation["source"])
    else:
        out["climb"] = _not_scored("no elevation for this route")
    if ctx is not None and ctx.wait_s is not None:
        out["wait_at_lights"] = _value(round(ctx.wait_s / 60, 1), "min", "estimate",
                                       "decision 015's signal-timing assumptions, at every signalized crossing")
    else:
        out["wait_at_lights"] = _not_scored("no lights setting or street grid")
    crowd = next((d for d in (c.ranking.dimensions if c.ranking else ()) if d.key == "crowds"), None)
    if crowd is not None and crowd.status == "estimate" and ctx is not None:
        out["crowds"] = _value(round(ctx.crowd_high_pct, 1), "% busy", "estimate",
                               f"subway volume and DOT counts, {ctx.crowd_band}",
                               not_scored_pct=round(ctx.crowd_not_scored_pct, 1))
    else:
        out["crowds"] = _not_scored((crowd.value if crowd is not None else "") or "no start time given")

    turns = [m["properties"] for m in markers if m["properties"].get("feature") == "turnaround"]
    out["turnarounds"] = [_value(t["along_mi"], "mi", "measured", t["source"], meters=t["along_m"]) for t in turns]
    out["score"] = _value(round(c.score), None, "provisional", "combined ranking; weights not calibrated (decision 010)")
    return out
