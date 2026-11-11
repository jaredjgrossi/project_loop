"""Mile and turnaround markers along a route (decision 020): GeoJSON points for the UI, and the GPX waypoints.

Both are `measured`: positions on the route's own geometry, with no dataset involved. A turnaround is where the
heading reverses after the same spur removal and 20 m simplification the turn count uses (api/shape.py).

Each reversal's reach is how far the route goes out along a dead end before coming back the same way (the two
directions within REACH_SAME_M of each other). A reversal that reaches SPUR_MIN_REACH_M to SPUR_REACH_M is a spur, a
quick out-and-back of a few hundred meters off the main line (shorter ones, a ramp or a footbridge approach, are
part of the line): only the main turnarounds are marked, and the generator rejects routes with a spur
away from the start and finish (phone test, 2026-11-11: a spur 0.8 mi in was marked TURN, not the turn at the far
end). Decision 044.
"""

import math


METERS_PER_MILE = 1609.344
SPUR_REACH_M = 400  # a dead end reached and left in less than this is a spur, not where the run turns ...
SPUR_MIN_REACH_M = 150  # ... if it reaches this far: "a quick out-and-back of a few hundred meters". Shorter
# reversals are part of the line (a ramp or footbridge approach), neither spurs nor turnarounds.
REACH_SAME_M = 30  # the way out and the way back are the same path while this close
REACH_STEP_M = 5
REACH_GAP_M = 150
SAMPLE_M = 5.0
END_ZONE_M = 300
FAR_TIP_M = 150  # a reversal this close (along the route) to the point farthest from the start is where the run turns
TIP_SCALES_M = (40, 100, 200)
TIP_CLOSE_M = 25  # the way out and the way back this close, at the same distance from the tip ...
TIP_OUT_M = 30  # ... with the tip this far off them
MILE_SOURCE = "route geometry"
TURNAROUND_SOURCE = "route geometry: where the route turns back on itself, not counting spurs under 400 m"


def _xy(coords):
    lat0 = coords[0][1]
    kx = 111_320 * math.cos(math.radians(lat0))
    return [((c[0] - coords[0][0]) * kx, (c[1] - lat0) * 110_574) for c in coords]


def _along(xy) -> list[float]:
    out = [0.0]
    for a, b in zip(xy, xy[1:]):
        out.append(out[-1] + math.dist(a, b))
    return out


def mile_points(coords: list[list[float]]) -> list[dict]:
    """{mile, lon, lat, along_m} at each whole mile along the route."""
    xy = _xy(coords)
    along = _along(xy)
    out, mile = [], 1
    for i, (a, b) in enumerate(zip(coords, coords[1:])):
        seg = along[i + 1] - along[i]
        while seg and along[i + 1] >= mile * METERS_PER_MILE:
            f = (mile * METERS_PER_MILE - along[i]) / seg
            out.append({"mile": mile, "lon": a[0] + (b[0] - a[0]) * f, "lat": a[1] + (b[1] - a[1]) * f,
                        "along_m": mile * METERS_PER_MILE})
            mile += 1
    return out


def reversals(coords: list[list[float]]) -> list[dict]:
    """Every place the route reverses direction, {lon, lat, along_m, reach_m}, in order along the route.

    On the route resampled every SAMPLE_M: a point is a tip when, at one of TIP_SCALES_M, the route that far before
    and after it comes back within TIP_CLOSE_M of itself while the point stands TIP_OUT_M or more off that spot.
    Several scales, so a turn around a block at the far end (the way back starts a block later) counts too. Each
    run of tip points is one reversal, at its point farthest out."""
    import numpy as np
    raw = np.asarray(_xy(coords), dtype=float)
    along_raw = np.asarray(_along(raw.tolist()))
    if len(raw) < 3 or along_raw[-1] < 3 * SAMPLE_M:
        return []
    along = np.arange(0.0, along_raw[-1], SAMPLE_M)
    xy = np.column_stack([np.interp(along, along_raw, raw[:, 0]), np.interp(along, along_raw, raw[:, 1])])
    n = len(xy)
    score = np.zeros(n)
    for scale in TIP_SCALES_M:
        k = int(scale / SAMPLE_M)
        if n <= 2 * k:
            continue
        i = np.arange(k, n - k)
        before, after = xy[i - k], xy[i + k]
        mid = (before + after) / 2
        ok = (np.hypot(*(before - after).T) <= TIP_CLOSE_M) & (np.hypot(*(xy[i] - mid).T) >= TIP_OUT_M)
        score[i[ok]] = np.maximum(score[i[ok]], np.hypot(*(xy[i[ok]] - mid[ok]).T))
    tips, run = [], []
    for idx in [*np.nonzero(score)[0], None]:
        if idx is not None and (not run or idx - run[-1] <= 2):
            run.append(idx)
            continue
        if run:
            tips.append(max(run, key=lambda j: score[j]))
        run = [idx] if idx is not None else []
    lat0, lon0 = coords[0][1], coords[0][0]
    kx = 111_320 * math.cos(math.radians(lat0))
    out = []
    for t in tips:
        out.append({"lon": lon0 + xy[t, 0] / kx, "lat": lat0 + xy[t, 1] / 110_574, "along_m": float(along[t]),
                    "reach_m": _reach(xy.tolist(), along.tolist(), int(t))})
    return out


def _reach(xy, along, tip: int) -> float:
    """How far the route went out along the dead end it turns at: from the tip back along the way out, as far as the
    way out runs within REACH_SAME_M of the way back (the route after the tip), measured on the way out. Gaps up to
    REACH_GAP_M are crossed: a turn around a block at the tip, or a crossing on the other side of the street."""
    import numpy as np
    pts = np.asarray(xy, dtype=float)
    back_along = np.asarray(along[tip:])
    reach, j, last = 0.0, tip, along[tip]
    while j > 0:
        j -= 1
        if last - along[j] < REACH_STEP_M:
            continue
        last = along[j]
        out_m = along[tip] - along[j]
        window = pts[tip: tip + int(np.searchsorted(back_along, along[tip] + out_m + 200))]
        if len(window) and np.min(np.hypot(*(window - pts[j]).T)) <= REACH_SAME_M:
            reach = out_m
        elif out_m - reach > REACH_GAP_M:
            break
    return reach


def turnarounds(coords: list[list[float]]) -> list[dict]:
    """{lon, lat, along_m, reach_m} where the run turns: every reversal that reaches SPUR_REACH_M or more, and the one
    at the route's farthest point from the start, if it turns there (a thin loop's tip is where it turns, however
    short its reach). Spurs aren't turnarounds; a round loop has none."""
    found = reversals(coords)
    if not found:
        return []
    xy = _xy(coords)
    along = _along(xy)
    far = max(range(len(xy)), key=lambda i: math.hypot(*xy[i]))
    return [t for t in found if t["reach_m"] >= SPUR_REACH_M or abs(t["along_m"] - along[far]) <= FAR_TIP_M]


def spurs(coords: list[list[float]]) -> list[dict]:
    """The quick out-and-backs off the main line: reversals that reach less than SPUR_REACH_M, other than the one
    main turnaround of a route that has nothing longer, and more than END_ZONE_M from the start or finish (where the
    start point sits mid-block and the route first heads the other way)."""
    found = reversals(coords)
    if not found:
        return []
    main = turnarounds(coords)
    total = _along(_xy(coords))[-1]
    return [t for t in found if SPUR_MIN_REACH_M <= t["reach_m"] < SPUR_REACH_M and t not in main
            and END_ZONE_M < t["along_m"] < total - END_ZONE_M]


def marker_features(coords: list[list[float]]) -> list[dict]:
    """GeoJSON points for the miles and turnarounds, each with its distance along the route and a trust label."""
    def point(lon, lat, props):
        return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": props}

    feats = [point(m["lon"], m["lat"], {"feature": "mile", "mile": m["mile"], "along_m": round(m["along_m"]),
                                        "along_mi": float(m["mile"]), "status": "measured", "source": MILE_SOURCE})
             for m in mile_points(coords)]
    feats += [point(t["lon"], t["lat"], {"feature": "turnaround", "along_m": round(t["along_m"]),
                                         "along_mi": round(t["along_m"] / METERS_PER_MILE, 2), "status": "measured",
                                         "source": TURNAROUND_SOURCE})
              for t in turnarounds(coords)]
    return feats
