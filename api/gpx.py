"""GPX export for a generated route (v1 scope: routes load into a watch or Strava), with mile markers and
turnaround points as waypoints so they show on the watch."""

import math
from xml.sax.saxutils import escape

from api.shape import _remove_spurs, _simplify

METERS_PER_MILE = 1609.344
TURNAROUND_DEGREES = 150  # a heading change this sharp is a turnaround, not a corner


def _frame(coords):
    lat0 = coords[0][1]
    kx = 111_320 * math.cos(math.radians(lat0))
    return lambda c: ((c[0] - coords[0][0]) * kx, (c[1] - lat0) * 110_574), kx


def mile_markers(coords: list[list[float]]) -> list[tuple[float, float, str]]:
    """(lat, lon, "Mile n") at each whole mile along the route."""
    xy, _ = _frame(coords)
    out, along, mile = [], 0.0, 1
    for a, b in zip(coords, coords[1:]):
        (x0, y0), (x1, y1) = xy(a), xy(b)
        seg = math.hypot(x1 - x0, y1 - y0)
        while seg and along + seg >= mile * METERS_PER_MILE:
            f = (mile * METERS_PER_MILE - along) / seg
            out.append((a[1] + (b[1] - a[1]) * f, a[0] + (b[0] - a[0]) * f, f"Mile {mile}"))
            mile += 1
        along += seg
    return out


def turnaround_points(coords: list[list[float]]) -> list[tuple[float, float, str]]:
    """(lat, lon, "Turnaround") where the route reverses direction, after the same spur removal and 20 m
    simplification the turn count uses (api/shape.py)."""
    xy, _ = _frame(coords)
    raw = [xy(c) for c in coords]
    pts = _simplify(_remove_spurs(raw), 20)
    out = []
    for p, q, r in zip(pts, pts[1:], pts[2:]):
        b1 = math.degrees(math.atan2(q[0] - p[0], q[1] - p[1]))
        b2 = math.degrees(math.atan2(r[0] - q[0], r[1] - q[1]))
        if abs((b2 - b1 + 180) % 360 - 180) >= TURNAROUND_DEGREES:
            # Spur removal trims up to 50 m off the tip; mark the real tip: the route point near q farthest from p.
            near = [i for i, c in enumerate(raw) if math.dist(c, q) <= 120]
            tip = max(near, key=lambda i: math.dist(raw[i], p))
            out.append((coords[tip][1], coords[tip][0], "Turnaround"))
    return out


def route_to_gpx(name: str, coords: list[list[float]], elevation: list[float] | None,
                 waypoints: list[tuple[float, float, str]]) -> str:
    wpts = "".join(f'  <wpt lat="{lat:.7f}" lon="{lon:.7f}"><name>{escape(label)}</name></wpt>\n'
                   for lat, lon, label in waypoints)
    trkpts = "".join(
        f'      <trkpt lat="{c[1]:.7f}" lon="{c[0]:.7f}">'
        + (f"<ele>{elevation[i]:.1f}</ele>" if elevation else "") + "</trkpt>\n"
        for i, c in enumerate(coords)
    )
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<gpx version="1.1" creator="Loop" xmlns="http://www.topografix.com/GPX/1/1">\n'
            f"  <metadata><name>{escape(name)}</name></metadata>\n{wpts}"
            f"  <trk><name>{escape(name)}</name><trkseg>\n{trkpts}    </trkseg></trk>\n</gpx>\n")
