"""Map-match the reviewer's Apple Health runs onto Loop's OSM graph (decision 011).

    uv run python -m evals.health_routes.match_runs apple_health_export/workout-routes [--since 2025-10-30]

Uses GraphHopper's own map matching (/match, a hidden Markov model over the same foot graph the generator routes
on), so a real run and a generated route end up as the same kind of geometry and can be measured with identical
definitions. Privacy: the first and last TRIM_M of every track are cut BEFORE matching, so nothing stored or rendered
starts or ends at the runner's door. Raw tracks are never written anywhere.

Writes data/health/matched.jsonl (git-ignored): one line per run with the trimmed, matched geometry and the few
numbers that need the untrimmed track (distance, duration, start-to-finish gap in meters, start cell id).
"""

import argparse
import json
import math
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import httpx

from api.routing import graphhopper_url

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "health" / "matched.jsonl"
TRIM_M = 200.0
RESAMPLE_S = 3  # GPS fixes are 1 s apart; every 3rd keeps the shape and speeds matching up
GPS_ACCURACY_M = 40  # GraphHopper's default; 15 hugged noise and hopped between parallel paths, 60 cut corners (decision 011)
PT = re.compile(r'<trkpt lon="([^"]+)" lat="([^"]+)">.*?<time>([^<]+)</time>', re.S)
M_LAT = 111_320.0
M_LON = M_LAT * math.cos(math.radians(40.75))


def is_run(miles: float, mps: float) -> bool:
    """Same rule as summarize.py, so the run set matches the first-pass numbers."""
    return 2.2 <= mps <= 6.5 and 0.8 <= miles <= 30


def _d(a, b) -> float:
    return math.hypot((a[0] - b[0]) * M_LON, (a[1] - b[1]) * M_LAT)


def trim(points: list[tuple[float, float, str]], meters: float = TRIM_M) -> list[tuple[float, float, str]]:
    """Drop the first and last `meters` of a track, measured along it."""
    def cut_index(pts):
        along = 0.0
        for i in range(1, len(pts)):
            along += _d(pts[i - 1], pts[i])
            if along >= meters:
                return i
        return len(pts)

    head = cut_index(points)
    tail = len(points) - cut_index(points[::-1])
    return points[head:tail] if head < tail else []


def read_track(path: Path) -> list[tuple[float, float, str]]:
    return [(float(lon), float(lat), t) for lon, lat, t in PT.findall(path.read_text(encoding="utf-8"))]


def gpx_body(points) -> str:
    pts = "".join(f'<trkpt lon="{lon}" lat="{lat}"><time>{t}</time></trkpt>' for lon, lat, t in points)
    return f'<?xml version="1.0"?><gpx version="1.1" creator="loop"><trk><trkseg>{pts}</trkseg></trk></gpx>'


def match(points, client: httpx.Client) -> dict:
    resp = client.post(
        f"{graphhopper_url()}/match",
        params={"profile": "foot", "gps_accuracy": GPS_ACCURACY_M, "points_encoded": "false", "instructions": "false"},
        content=gpx_body(points[::RESAMPLE_S]),
        headers={"Content-Type": "application/gpx+xml"},
    )
    payload = resp.json()
    if resp.status_code != 200 or not payload.get("paths"):
        raise ValueError(payload.get("message", f"HTTP {resp.status_code}"))
    return payload


def process(path: Path, since: str, client: httpx.Client) -> dict:
    date = path.name.split("_")[1]
    if date < since:
        return {"file": path.name, "status": "before_window"}
    pts = read_track(path)
    if len(pts) < 20:
        return {"file": path.name, "status": "too_few_points"}
    dist = sum(_d(pts[i - 1], pts[i]) for i in range(1, len(pts)))
    t0 = datetime.fromisoformat(pts[0][2].replace("Z", "+00:00"))
    t1 = datetime.fromisoformat(pts[-1][2].replace("Z", "+00:00"))
    dur = (t1 - t0).total_seconds()
    if dur <= 0 or not is_run(dist / 1609.344, dist / dur):
        return {"file": path.name, "status": "not_a_run"}
    trimmed = trim(pts)
    if len(trimmed) < 10:
        return {"file": path.name, "status": "too_short_after_trim"}
    if sum(-74.26 <= lon <= -73.70 and 40.49 <= lat <= 40.92 for lon, lat, _ in trimmed) < len(trimmed) / 2:
        return {"file": path.name, "status": "outside_nyc"}  # the graph is NYC only
    try:
        payload = match(trimmed, client)
    except (ValueError, httpx.HTTPError) as exc:
        return {"file": path.name, "status": "match_failed", "reason": str(exc)[:200]}
    p = payload["paths"][0]
    stats = payload.get("map_matching", {})
    sx, sy = pts[0][0] * M_LON, pts[0][1] * M_LAT
    return {
        "file": path.name, "status": "ok", "date": date, "start_utc": pts[0][2],
        "raw_miles": round(dist / 1609.344, 3), "minutes": round(dur / 60, 1),
        "closure_m": round(_d(pts[0], pts[-1])),  # needs the untrimmed ends; only the distance is kept
        "start_cell": f"{int(sx // 300)}_{int(sy // 300)}",  # 300 m cell id, as in analyze_routes.py
        "trimmed_gps_m": round(stats.get("original_distance", 0)), "matched_m": round(p["distance"]),
        "coordinates": [c[:2] for c in p["points"]["coordinates"]],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("routes_dir", type=Path)
    ap.add_argument("--since", default="2025-10-30", help="first date to include (YYYY-MM-DD)")
    ap.add_argument("--limit", type=int, help="only the first N files in the window (for trying it out)")
    args = ap.parse_args(argv)
    files = sorted(p for p in args.routes_dir.glob("*.gpx") if p.name.split("_")[1] >= args.since)
    if args.limit:
        files = files[: args.limit]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    with httpx.Client(timeout=120) as client, ThreadPoolExecutor(max_workers=4) as pool, OUT.open("w") as out:
        for r in pool.map(lambda f: process(f, args.since, client), files):
            counts[r["status"]] = counts.get(r["status"], 0) + 1
            if r["status"] == "ok":
                out.write(json.dumps(r) + "\n")
            elif r["status"] == "match_failed":
                print(f"  match failed: {r['file']}: {r['reason']}", file=sys.stderr)
    print(f"{len(files)} files since {args.since}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    print(f"Wrote {OUT.relative_to(ROOT)} ({datetime.now(UTC):%Y-%m-%d %H:%M} UTC)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
