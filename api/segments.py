"""Per-segment GeoJSON for the UI (decision 014): a route cut into named stretches ("Mile 1 · East River Greenway").

Each stretch has a kind (corridor, park, waterfront, street or path), a name, its mile range, its signalized crosswalks
(measured), its climb (estimate) and facts. Every fact carries a source and a trust label (product rule 2). The
datasets behind stretch facts (OSM, the corridor catalog built from OSM, OSM park areas) say a path or park is there,
not that it is open today, so stretch facts are `listed`.

Labels come from PostGIS for a sample every STEP_M along the route; the merging and the GeoJSON are pure.
"""

import json
import math
from dataclasses import dataclass

STEP_M = 20.0
MIN_STRETCH_M = 150.0  # shorter changes are absorbed: crossing a plaza is not a stretch
METERS_PER_MILE = 1609.344


@dataclass(frozen=True)
class Label:
    kind: str  # corridor | park | waterfront | street | path
    name: str
    source: str
    trust: str = "listed"


@dataclass
class Stretch:
    label: Label
    start: int  # sample index, inclusive
    end: int  # sample index, exclusive


def merge_stretches(labels: list[Label], step_m: float = STEP_M) -> list[Stretch]:
    """Group consecutive samples with the same kind and name; absorb stretches shorter than MIN_STRETCH_M."""
    runs: list[Stretch] = []
    for i, lab in enumerate(labels):
        if runs and (runs[-1].label.kind, runs[-1].label.name) == (lab.kind, lab.name):
            runs[-1].end = i + 1
        else:
            runs.append(Stretch(lab, i, i + 1))
    min_n = max(1, int(MIN_STRETCH_M // step_m))
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for i, r in enumerate(runs):
            if r.end - r.start < min_n:
                if i == 0:
                    runs[1].start = r.start
                else:
                    runs[i - 1].end = r.end
                del runs[i]
                changed = True
                break
        # Neighbors that now share a label merge.
        merged: list[Stretch] = []
        for r in runs:
            if merged and (merged[-1].label.kind, merged[-1].label.name) == (r.label.kind, r.label.name):
                merged[-1].end = r.end
            else:
                merged.append(r)
        runs = merged
    return runs


def _resample(coords: list[list[float]], step_m: float) -> list[list[float]]:
    kx = 111_320 * math.cos(math.radians(coords[0][1]))
    out = [coords[0]]
    carry = 0.0
    for (x0, y0), (x1, y1) in zip(coords, coords[1:]):
        seg = math.hypot((x1 - x0) * kx, (y1 - y0) * 110_574)
        pos = step_m - carry
        while pos <= seg:
            f = pos / seg
            out.append([x0 + (x1 - x0) * f, y0 + (y1 - y0) * f])
            pos += step_m
        carry = seg - (pos - step_m)
    if out[-1] != coords[-1]:
        out.append(coords[-1])
    return out


def stretch_features(samples: list[list[float]], labels: list[Label], step_m: float = STEP_M,
                     signals: list[int] | None = None, gains: list[float | None] | None = None,
                     extra_facts: list[list[dict]] | None = None, crowds: list[dict] | None = None) -> list[dict]:
    """GeoJSON features for the stretches of a route sampled every step_m (samples[i] has labels[i])."""
    stretches = merge_stretches(labels, step_m)
    feats = []
    for i, s in enumerate(stretches):
        geom = samples[s.start:min(s.end + 1, len(samples))]
        if len(geom) < 2:
            geom = samples[max(0, s.start - 1):s.start + 1]
        lab = s.label
        facts = [{"text": FACT_TEXT[lab.kind].format(name=lab.name), "source": lab.source, "trust": lab.trust}]
        facts += (extra_facts[i] if extra_facts else [])
        feats.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": geom},
            "properties": {
                "feature": "stretch", "stretch": i, "name": lab.name, "kind": lab.kind,
                "from_mile": round(s.start * step_m / METERS_PER_MILE, 2),
                "to_mile": round(min(s.end, len(samples) - 1) * step_m / METERS_PER_MILE, 2),
                "length_m": round((min(s.end, len(samples) - 1) - s.start) * step_m),
                "signals": {"value": signals[i], "status": "measured"} if signals else {"value": None, "status": "not_scored"},
                "elevation_gain_m": ({"value": gains[i], "status": "estimate"} if gains and gains[i] is not None
                                     else {"value": None, "status": "not_scored"}),
                "crowd": crowds[i] if crowds else {"value": None, "status": "not_scored", "basis": "not computed"},
                "facts": facts,
            },
        })
    return feats


FACT_TEXT = {
    "corridor": "On {name}",
    "park": "Through {name}",
    "waterfront": "Along the waterfront ({name})",
    "street": "On {name}",
    "path": "On {name}",
}


# --- PostGIS ------------------------------------------------------------------------------

_LABELS = """
WITH s AS (
    SELECT ord, ST_SetSRID(ST_MakePoint(lon, lat), 4326) AS g
    FROM unnest(%(lons)s::float8[], %(lats)s::float8[]) WITH ORDINALITY AS u(lon, lat, ord)
)
SELECT s.ord, c.id, c.name, c.verified, p.area_id, p.name,
       EXISTS (SELECT 1 FROM osm_coastline k WHERE k.geom && ST_Expand(s.g, 0.001)
               AND ST_DWithin(k.geom::geography, s.g::geography, 60)) AS by_water,
       w.way_id, w.name
FROM s
LEFT JOIN LATERAL (SELECT id, name, verified FROM corridors c WHERE c.geom && ST_Expand(s.g, 0.0003)
                   AND ST_DWithin(c.geom::geography, s.g::geography, 15) ORDER BY c.geom <-> s.g LIMIT 1) c ON true
LEFT JOIN LATERAL (SELECT area_id, name FROM osm_parks p WHERE p.geom && s.g AND ST_Contains(p.geom, s.g)
                   AND p.name IS NOT NULL ORDER BY ST_Area(p.geom) LIMIT 1) p ON true
LEFT JOIN LATERAL (SELECT way_id, name FROM osm_ways w WHERE w.name IS NOT NULL AND w.geom && ST_Expand(s.g, 0.0004)
                   AND ST_DWithin(w.geom::geography, s.g::geography, 30)
                   AND w.highway NOT IN ('motorway', 'motorway_link', 'trunk', 'trunk_link')
                   ORDER BY w.geom <-> s.g LIMIT 1) w ON true
ORDER BY s.ord
"""

_GAPS = """
SELECT id, round(gap_m) FROM corridor_gaps
WHERE ST_DWithin(geom::geography, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)::geography, 50)
"""


def _label(row) -> Label:
    _, cid, cname, verified, area_id, pname, by_water, way_id, wname = row
    if cid is not None:
        how = "continuity checked by routing" if verified else "has gaps when routed end to end"
        if cname.startswith("unnamed") and wname:
            cname = f"{cname.removeprefix('unnamed ').removesuffix(' path')} path near {wname}"
        return Label("corridor", cname, f"Loop corridor catalog #{cid}, from OSM ways ({how})")
    if area_id is not None:
        return Label("park", pname, f"OSM park area a{area_id}")
    if by_water:
        return Label("waterfront", wname or "waterfront path",
                     "OSM coastline within 60 m" + (f"; OSM way w{way_id}" if way_id else ""))
    if wname is not None:
        return Label("street", wname, f"OSM way w{way_id}")
    return Label("path", "unnamed path", "OSM ways (unnamed)")


WIDTH_SOURCE = "NYC planimetric sidewalk polygons (52n9-sdep, 2022 imagery), width measured across the way by Loop"


def route_stretches(conn, coords: list[list[float]], elevation: list[float] | None = None, start=None) -> list[dict]:
    """Stretch features for a route: labels from PostGIS, signals from OSM crosswalks, climb from the elevation, and
    the crowd level (estimate) for a run starting at `start` (decision 016)."""
    from api.crowds import route_crowds, stretch_crowd
    from api.elevation import elevation_profile
    from api.route_context import crossing_counts, fetch_context

    samples = _resample(coords, STEP_M)
    rows = conn.execute(_LABELS, {"lons": [c[0] for c in samples], "lats": [c[1] for c in samples]}).fetchall()
    labels = [_label(r) for r in rows]
    stretches = merge_stretches(labels, STEP_M)
    crossings = fetch_context(conn, coords).crossings
    sample_ele = _elevation_at_samples(coords, elevation, samples) if elevation else None
    crowd = route_crowds(conn, coords, start)
    widths = {}
    ways = list({w for w in crowd["sidewalk_ways"] if w is not None})
    if ways:
        widths = dict(conn.execute("SELECT way_id, width_ft FROM sidewalk_width WHERE width_ft IS NOT NULL AND way_id = ANY(%s)", (ways,)).fetchall())
    signals, gains, extra, crowds = [], [], [], []
    for s in stretches:
        lo, hi = s.start * STEP_M, s.end * STEP_M
        idx = [k for k, a in enumerate(crowd["along_m"]) if lo <= a < hi]
        crowds.append(stretch_crowd([crowd["levels"][k] for k in idx]))
        ws = sorted(widths[w] for w in (crowd["sidewalk_ways"][k] for k in idx) if w in widths)
        part = samples[s.start:min(s.end + 1, len(samples))]
        if len(part) < 2:
            part = samples[max(0, s.start - 1):s.start + 1]
        signals.append(crossing_counts(part, crossings)[1])
        gains.append(elevation_profile(part, sample_ele[s.start:s.start + len(part)])["gain_m"] if sample_ele else None)
        gaps = conn.execute(_GAPS, (json.dumps({"type": "LineString", "coordinates": part}),)).fetchall()
        extra.append([{"text": f"A known {int(m)} m gap in the waterfront or greenway path is nearby",
                       "source": f"Loop corridor catalog gap #{gid} (routed in OSM)", "trust": "listed"}
                      for gid, m in gaps])
        if idx and 2 * len(ws) > len(idx):  # mostly on sidewalks with a measured width
            extra[-1].append({"text": f"Sidewalk about {ws[len(ws) // 2]:.0f} ft wide", "source": WIDTH_SOURCE,
                              "trust": "listed"})
    return stretch_features(samples, labels, STEP_M, signals, gains, extra, crowds)


def _elevation_at_samples(coords, elevation, samples) -> list[float]:
    """Nearest route vertex's elevation for each sample (vertices are dense enough on routed geometry)."""
    out, j = [], 0
    for lon, lat in samples:
        best, best_d = j, math.inf
        for k in range(j, min(len(coords), j + 60)):
            d = (coords[k][0] - lon) ** 2 + (coords[k][1] - lat) ** 2
            if d < best_d:
                best, best_d = k, d
        j = best
        out.append(elevation[best])
    return out
