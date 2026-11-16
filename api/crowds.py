"""Crowds (decision 016): a crowd level on sidewalk stretches from subway volume, with time from DOT's count windows,
and `not_scored` wherever the data can't speak. Follows decision 013's recommendation.

- Where: station flow (entries + exits) summed with a Gaussian kernel (sigma 300 m, cut at 800 m) around each sidewalk
  way, divided by sidewalk width (52n9-sdep). Levels come from citywide percentiles within a band: high at or above
  the 85th, medium at or above the 50th, else low. Ways more than 800 m from the subway are low, "far from the subway
  (assumption)". Precomputed by etl/load_crowds.py into sidewalk_crowd.
- When: coarse bands matching DOT's count windows, not hourly subway shapes (013 found subway hours don't predict
  sidewalk hours). Before 7am, after 8pm, Sundays and Saturday outside 12-2pm are not scored ("no count data at this
  hour"), never assumed quiet. The hour at a point = start + distance so far at an assumed 10 min/mi.
- Paths, bridges, greenways and road centerlines (anything but a mapped sidewalk): not scored ("no crowd data off
  mapped sidewalks"), except paths within 400 m of a current DOT
  automated pedestrian counter on the same corridor, which take its measured hourly counts (any day, any hour).
All levels are `estimate`.
"""

import math
from datetime import datetime, timedelta

STATION_SIGMA_M = 300
STATION_CUT_M = 800
NEAR_SUBWAY_M = 800
HIGH_PCT, MEDIUM_PCT = 85, 50
PACE_MIN_PER_MI = 10.0
METERS_PER_MILE = 1609.344

# band -> (day type, hours used for station flow, label)
BANDS = {
    "weekday_am": ("weekday", [7, 8], "weekday 7-9am (a DOT count window)"),
    "weekday_midday": ("weekday", list(range(9, 16)), "weekday 9am-4pm (between DOT count windows)"),
    "weekday_pm": ("weekday", [16, 17, 18], "weekday 4-7pm (a DOT count window)"),
    "saturday_midday": ("saturday", [12, 13], "Saturday 12-2pm (a DOT count window)"),
}


def band_for(when: datetime | None) -> tuple[str | None, str]:
    """The DOT band for a moment, or None with the reason it isn't scored."""
    if when is None:
        return None, "no start time given"
    h, dow = when.hour, when.weekday()  # Monday = 0
    if dow == 6:
        return None, "no count data on Sundays"
    if h < 7:
        return None, "no count data before 7am"
    if h >= 20:
        return None, "no count data after 8pm"
    if dow == 5:
        if 12 <= h < 14:
            return "saturday_midday", BANDS["saturday_midday"][2]
        return None, "no count data on Saturday outside 12-2pm"
    if h < 9:
        return "weekday_am", BANDS["weekday_am"][2]
    if h < 16:
        return "weekday_midday", BANDS["weekday_midday"][2]
    if h < 19:
        return "weekday_pm", BANDS["weekday_pm"][2]
    return "weekday_pm", "weekday 7-8pm (after the 4-7pm count window; assumed like it)"


def daytype(when: datetime) -> str:
    return "sunday" if when.weekday() == 6 else ("saturday" if when.weekday() == 5 else "weekday")


def sample_times(start: datetime, along_m: list[float], pace_min_per_mi: float = PACE_MIN_PER_MI) -> list[datetime]:
    return [start + timedelta(minutes=a / METERS_PER_MILE * pace_min_per_mi) for a in along_m]


def counter_level(per_hour: float, thresholds: dict) -> str:
    """Level for a counter's people per hour, against DOT street sites' per-hour counts (median and 85th pct)."""
    if per_hour >= thresholds["high"]:
        return "high"
    return "medium" if per_hour >= thresholds["medium"] else "low"


def summarize(levels: list[str | None]) -> dict:
    """Shares of distance (samples are evenly spaced) at each level, and not scored."""
    n = len(levels) or 1
    share = lambda v: round(100 * sum(lv == v for lv in levels) / n, 1)
    return {"high_pct": share("high"), "medium_pct": share("medium"), "low_pct": share("low"),
            "not_scored_pct": round(100 * sum(lv is None for lv in levels) / n, 1) if levels else 100.0}


PULSE_LABEL = "scheduled crowd pulse (school or ferry, decision 022)"


def band_labels(bands: set) -> str | None:
    """The label for the bands a route's scored samples used; counter samples name their counter instead."""
    labels = [BANDS[b][2] for b in sorted(b for b in bands if b and b not in ("counter", "pulse"))]
    if "pulse" in bands:
        labels.append(PULSE_LABEL)
    return ", ".join(labels) or None


def pulse_window(way_id, sidewalk: bool, at: datetime | None, windows: dict):
    """The scheduled pulse window a path sample falls in (decision 022), or None. Sidewalks keep decision 016's level;
    outside the windows a path stays not scored."""
    if sidewalk or way_id not in windows:
        return None
    from api.pulses import hit

    return hit(at, windows[way_id])


def pulse_level(way_id, sidewalk: bool, at: datetime | None, windows: dict) -> tuple | None:
    """A path sample inside a scheduled pulse window: high, with the cause as its basis."""
    w = pulse_window(way_id, sidewalk, at, windows)
    return ("high", w.basis, "pulse") if w else None


def pulse_hits(hits: list[tuple], step_m: float) -> list[dict]:
    """The pulses a route meets, one entry per window, from (window, along_m, time) sample hits in route order: the
    cause in parts, where the run meets it (first to last sample, miles) and the clock when it first does. Everything
    here is an estimate (the windows are assumed, decision 022); `source` is the window's basis prose."""
    out: dict[str, dict] = {}
    for w, along, t in hits:
        e = out.get(w.basis)
        if e is None:
            out[w.basis] = e = {"cause": w.cause, "name": w.name, "place": w.place,
                                "arrival": f"{w.arrival:%H:%M}" if w.arrival else None, "event": w.event,
                                "from_mile": round(along / METERS_PER_MILE, 2), "to_mile": round(along / METERS_PER_MILE, 2),
                                "at": f"{t:%H:%M}", "meters": 0, "status": "estimate", "source": w.basis}
        e["to_mile"] = round(along / METERS_PER_MILE, 2)
        e["meters"] += step_m
    return sorted((dict(e, meters=round(e["meters"])) for e in out.values()), key=lambda e: e["from_mile"])


def stretch_crowd(levels: list[tuple]) -> dict:
    """A stretch's crowd level from its samples' (level, basis, band): the most common scored level, an estimate, or
    not_scored with the most common reason when half or more of the stretch has no crowd data."""
    scored = [lv for lv in levels if lv[0]]
    if not levels or 2 * len(scored) <= len(levels):
        reasons = [lv[1] for lv in levels if not lv[0]]
        return {"value": None, "status": "not_scored",
                "basis": max(set(reasons), key=reasons.count) if reasons else "no crowd data"}
    names = [lv[0] for lv in scored]
    value = max(("high", "medium", "low"), key=names.count)  # ties go to the busier level
    bands = [lv[2] for lv in scored]
    band = max(set(bands), key=bands.count)
    bases = [lv[1] for lv in scored if lv[0] == value]
    return {"value": value, "status": "estimate", "basis": max(set(bases), key=bases.count),
            "band": {"counter": "DOT automated pedestrian counter (hourly)", "pulse": PULSE_LABEL}.get(band)
                    or BANDS[band][2],
            "high_pct": round(100 * names.count("high") / len(levels), 1)}


# --- PostGIS -------------------------------------------------------------------------------------

_SAMPLES = """
WITH s AS (
    SELECT ord, ST_SetSRID(ST_MakePoint(lon, lat), 4326) AS g
    FROM unnest(%(lons)s::float8[], %(lats)s::float8[]) WITH ORDINALITY AS u(lon, lat, ord)
)
SELECT s.ord, w.way_id, w.sidewalk, c.sensor_id
FROM s
LEFT JOIN LATERAL (
    SELECT way_id, coalesce(tags->>'footway', '') = 'sidewalk' AS sidewalk FROM osm_ways w
    WHERE w.geom && ST_Expand(s.g, 0.0001) AND ST_DWithin(w.geom::geography, s.g::geography, 6)
    ORDER BY w.geom <-> s.g LIMIT 1) w ON true
LEFT JOIN counter_ways c ON c.way_id = w.way_id
ORDER BY s.ord
"""
_thresholds: dict | None = None


def street_thresholds(conn) -> dict:
    """People per hour at DOT street sites (latest two rounds): the median and the 85th percentile."""
    global _thresholds
    if _thresholds is None:
        rows = conn.execute("""SELECT count / CASE period WHEN 'pm' THEN 3 ELSE 2 END FROM dot_ped_counts
                               WHERE kind = 'street' AND round IN ('oct25', 'may26')""").fetchall()
        vals = sorted(r[0] for r in rows) or [0.0]
        q = lambda p: vals[min(len(vals) - 1, int(p / 100 * len(vals)))]
        _thresholds = {"medium": q(MEDIUM_PCT), "high": q(HIGH_PCT)}
    return _thresholds


def route_crowds(conn, coords: list[list[float]], start: datetime | None, step_m: float = 20.0) -> dict:
    """Crowd level per sample (every step_m) and the route summary. Levels are estimates."""
    start_band = band_for(start)[0]
    if not conn.execute("SELECT to_regclass('sidewalk_crowd') IS NOT NULL").fetchone()[0]:
        return {**summarize([]), "band": None, "reason": "crowd data not loaded", "start_band": None, "levels": [],
                "along_m": [], "sidewalk_ways": []}
    kx = 111_320 * math.cos(math.radians(coords[0][1]))
    samples, along = [coords[0]], [0.0]
    total = 0.0
    for a, b in zip(coords, coords[1:]):
        seg = math.hypot((b[0] - a[0]) * kx, (b[1] - a[1]) * 110_574)
        n = max(1, int(seg // step_m))
        for k in range(1, n + 1):
            samples.append([a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n])
            along.append(total + seg * k / n)
        total += seg
    rows = conn.execute(_SAMPLES, {"lons": [p[0] for p in samples], "lats": [p[1] for p in samples]}).fetchall()
    times = sample_times(start, along) if start else [None] * len(samples)
    bands = [band_for(t) for t in times]
    sidewalk_ids = list({r[1] for r in rows if r[1] is not None and r[2]})
    levels_by_way: dict = {}
    if sidewalk_ids:
        for way_id, band, level, basis in conn.execute(
                "SELECT way_id, band, level, basis FROM sidewalk_crowd WHERE way_id = ANY(%s)", (sidewalk_ids,)):
            levels_by_way[(way_id, band)] = (level, basis)
    sensors = {r[3] for r in rows if r[3]}
    per_hour = {}
    if sensors:
        for sid, dt, hour, ph in conn.execute(
                "SELECT sensor_id, daytype, hour, per_hour FROM counter_crowd WHERE sensor_id = ANY(%s)", (list(sensors),)):
            per_hour[(sid, dt, hour)] = ph
    th = street_thresholds(conn) if sensors else None
    windows = {}
    if start is not None and start_band is not None:  # pulses count only when crowds are scored at all (016)
        from api.pulses import windows_by_way

        windows = windows_by_way(conn, list({r[1] for r in rows if r[1] is not None and not r[2]}), start.date())
    out, hits = [], []
    for (ord_, way_id, sidewalk, sensor), t, (band, why), a in zip(rows, times, bands, along):
        if sensor and t is not None and (sensor, daytype(t), t.hour) in per_hour:
            ph = per_hour[(sensor, daytype(t), t.hour)]
            out.append((counter_level(ph, th), f"DOT automated pedestrian counter {sensor}: {ph:.0f} people/hour", "counter"))
        elif w := pulse_window(way_id, bool(sidewalk), t, windows):
            out.append(("high", w.basis, "pulse"))
            hits.append((w, a, t))
        elif way_id is None or not sidewalk:
            out.append((None, "no crowd data off mapped sidewalks (paths, greenways, bridges)", None))
        elif band is None:
            out.append((None, why, None))
        else:
            lv, basis = levels_by_way.get((way_id, band), (None, None))
            out.append((lv, f"{basis}, {why}" if lv else "no width or flow for this sidewalk", band if lv else None))
    summary = summarize([o[0] for o in out])
    used = {b for b in (o[2] for o in out) if b and b != "counter"}
    return {**summary, "band": band_labels(used),
            "reason": bands[0][1] if not used else None, "start_band": start_band, "levels": out, "along_m": along,
            "sidewalk_ways": [r[1] if r[2] else None for r in rows], "pulses": pulse_hits(hits, step_m)}
