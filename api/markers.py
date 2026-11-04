"""Mile and turnaround markers along a route (decision 020): GeoJSON points for the UI, and the GPX waypoints.

Both are `measured`: positions on the route's own geometry, with no dataset involved. A turnaround is where the
heading reverses after the same spur removal and 20 m simplification the turn count uses (api/shape.py).
"""

import math

from api.shape import _remove_spurs, _simplify

METERS_PER_MILE = 1609.344
TURNAROUND_DEGREES = 150  # a heading change this sharp is a turnaround, not a corner
MILE_SOURCE = "route geometry"
TURNAROUND_SOURCE = f"route geometry: where the heading reverses by {TURNAROUND_DEGREES} degrees or more"


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


def turnarounds(coords: list[list[float]]) -> list[dict]:
    """{lon, lat, along_m} where the route reverses direction, in order along the route."""
    raw = _xy(coords)
    along = _along(raw)
    pts = _simplify(_remove_spurs(raw), 20)
    out = []
    for p, q, r in zip(pts, pts[1:], pts[2:]):
        b1 = math.degrees(math.atan2(q[0] - p[0], q[1] - p[1]))
        b2 = math.degrees(math.atan2(r[0] - q[0], r[1] - q[1]))
        if abs((b2 - b1 + 180) % 360 - 180) >= TURNAROUND_DEGREES:
            # Spur removal trims up to 50 m off the tip; mark the real tip: the route point near q farthest from p.
            near = [i for i, c in enumerate(raw) if math.dist(c, q) <= 120]
            tip = max(near, key=lambda i: math.dist(raw[i], p))
            out.append({"lon": coords[tip][0], "lat": coords[tip][1], "along_m": along[tip]})
    return sorted(out, key=lambda t: t["along_m"])


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
