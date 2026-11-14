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
from api.elevation import SOURCE as ELEVATION_SOURCE
from api.hills import hill_metrics
from api.reason import route_reason
from api.route_context import COMPOSITION
from api.segments import COMPOSITION_SOURCE, SIGNALS_COUNTED
from api.steps import route_steps

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


def way_list(stretches: list[dict], turns: list[dict]) -> list[dict]:
    """The route as the sheet's "The way" lists it (UI review): each stretch with its name, kind and distance, in order,
    and `turnaround` ({mile, meters}) on the stretch the run turns on. The name is listed (OSM or the corridor
    catalog); the distance is measured from the route's own geometry."""
    out, start = [], 0
    for s in stretches:
        p = s["properties"]
        fact = (p.get("facts") or [{}])[0]
        length = p.get("length_m", 0)
        end = start + length
        item = {"name": p.get("name"), "kind": p.get("kind"), "from_mile": p.get("from_mile"),
                "to_mile": p.get("to_mile"),
                "distance": _value(round(length / METERS_PER_MILE, 2), "mi", "measured", DISTANCE_SOURCE, meters=length),
                "status": "measured", "trust": fact.get("trust", "listed"), "source": fact.get("source", DISTANCE_SOURCE)}
        out.append(item)
        start = end
    bounds = [0]
    for item in out:
        bounds.append(bounds[-1] + item["distance"]["meters"])
    for t in turns:
        along = t["along_m"]
        k = next((i for i in range(len(out)) if bounds[i] <= along <= bounds[i + 1]), None)
        if k is not None and "turnaround" not in out[k]:
            out[k]["turnaround"] = {"mile": round(along / METERS_PER_MILE, 2), "meters": along}
    return out


def _park_name(stretches: list[dict]) -> str | None:
    """The park the route runs most, by stretch name, or None when no stretch is labeled a park."""
    totals: dict[str, float] = {}
    for s in stretches:
        p = s["properties"]
        if p.get("kind") == "park":
            totals[p["name"]] = totals.get(p["name"], 0.0) + p.get("length_m", 0)
    return max(totals, key=totals.get) if totals else None


BEST_OF_SOURCE = ("distinct routes that passed every hard rule within the distance limit, duplicates dropped as "
                  "for the top 3 (decision 020)")


def route_summary(c: Candidate, stretches: list[dict], markers: list[dict], elevation: dict,
                  rank: int | None = None, best_of: int | None = None) -> dict:
    # The geometry's own length, as the mile markers and stretches measure it; GraphHopper's figure differs slightly.
    miles = c.shape.distance_miles
    stretches = [s for s in stretches if s["properties"].get("feature", "stretch") == "stretch"]  # not the pieces
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
    hills = next((d for d in (c.ranking.dimensions if c.ranking else ()) if d.key == "hills"), None)
    if hills is not None:  # only when the runner asked for flat (decision 037)
        h = hill_metrics(c.route.coordinates, c.route.elevation)
        out["hills"] = (_value(h.climb_m_per_mi, "m/mi", "estimate", f"{ELEVATION_SOURCE}, read every 0.1 mi",
                               steepest_pct=h.steepest_pct) if h is not None
                        else _not_scored("no elevation for this route"))
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
    out["way"] = way_list(stretches, [t for t in (m["properties"] for m in markers) if t.get("feature") == "turnaround"])
    steps = route_steps(c.route.coordinates, c.route.instructions, stretches, [t["along_m"] for t in turns],
                        out["distance"]["meters"])
    if steps:  # decision 054: a route that wasn't routed (a stored line) has none, and the app keeps `way`
        out["steps"] = steps
    shown = lambda key: out[key]["value"] if out[key]["status"] == "measured" else None  # noqa: E731
    out["reason"] = route_reason(
        waterfront_pct=shown("waterfront_pct"), park_pct=shown("park_pct"), park_name=_park_name(stretches),
        lights=shown("signalized_crossings"), climb_m=out["climb"]["value"] if out["climb"]["status"] == "estimate" else None,
        miles=miles)
    out["score"] = _value(round(c.score), None, "provisional", "combined ranking; weights not calibrated (decision 010)")
    out["rank"] = (_value(rank, None, "measured", BEST_OF_SOURCE, of=best_of) if rank is not None and best_of
                   else _not_scored("no route came within the distance limit"))
    return out
