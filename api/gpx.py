"""GPX export for a generated route (v1 scope: routes load into a watch or Strava), with mile markers and
turnaround points as waypoints so they show on the watch."""

from xml.sax.saxutils import escape

from api.markers import mile_points, turnarounds


def mile_markers(coords: list[list[float]]) -> list[tuple[float, float, str]]:
    """(lat, lon, "Mile n") at each whole mile along the route."""
    return [(m["lat"], m["lon"], f"Mile {m['mile']}") for m in mile_points(coords)]


def turnaround_points(coords: list[list[float]]) -> list[tuple[float, float, str]]:
    """(lat, lon, "Turnaround") where the route reverses direction (api/markers.py)."""
    return [(t["lat"], t["lon"], "Turnaround") for t in turnarounds(coords)]


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
