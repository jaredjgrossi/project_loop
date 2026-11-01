"""Measure real runs and generated routes with identical definitions (decision 011).

    uv run python -m evals.health_routes.calibrate

(i) the reviewer's map-matched runs (data/health/matched.jsonl) and (ii) the generator's top 3 from every review
start (plus 3 mi, the reviewer's typical distance, from the two Manhattan home-area starts). Every route is trimmed
200 m at both ends before measuring, real or generated, so the two are cut the same way; only closure (a single
distance) uses the untrimmed ends. Metrics come from api/shape.py and api/route_context.py, the same code the ranking
uses. Writes data/health/calibration_rows.csv and data/health/calibration.md (git-ignored) and prints the summary.
"""

import csv
import json
import math
import statistics as st
import sys
from pathlib import Path

import psycopg

from api.route_context import crossing_counts, fetch_context, park_share, waterfront_share
from api.shape import shape_metrics, trim_ends
from etl.load import database_url
from evals.routes.live import load_starts, stack_problem, top_loops

ROOT = Path(__file__).resolve().parents[2]
HEALTH = ROOT / "data" / "health"
TRIM_M = 200.0
TYPICAL_MILES = 3.0  # the reviewer's median run, last 12 months
HOME_AREA_STARTS = ("kips-bay", "upper-east-side")
NEAR_START_M = 1500  # a real run "starts near" a review start if its trimmed start is this close

METRICS = [  # key, label, format
    ("miles", "distance (trimmed), mi", "{:.2f}"),
    ("turns_per_mile", "turns per mile", "{:.1f}"),
    ("retraced_pct", "retraced %", "{:.0f}"),
    ("out_and_back_pct", "out-and-back %", "{:.0f}"),
    ("closure_m", "start-finish gap, m", "{:.0f}"),
    ("park_pct", "in a park %", "{:.0f}"),
    ("waterfront_pct", "waterfront %", "{:.0f}"),
    ("crossings_per_mile", "crosswalks per mile", "{:.1f}"),
    ("signals_per_mile", "signalized per mile", "{:.1f}"),
]


def measure(conn, trimmed: list, closure_m: float) -> dict:
    s = shape_metrics(trimmed)
    ctx = fetch_context(conn, trimmed)
    crossings, signals = crossing_counts(trimmed, ctx.crossings)
    return {
        "miles": s.distance_miles, "turns_per_mile": s.turns_per_mile, "retraced_pct": s.retraced_pct,
        "out_and_back_pct": s.out_and_back_pct, "closure_m": closure_m,
        "park_pct": park_share(trimmed, ctx.parks), "waterfront_pct": waterfront_share(trimmed, ctx.shoreline),
        "crossings_per_mile": crossings / s.distance_miles, "signals_per_mile": signals / s.distance_miles,
    }


def _m(a, b) -> float:
    return math.hypot((a[0] - b[0]) * 111_320 * math.cos(math.radians(40.75)), (a[1] - b[1]) * 110_574)


def summarize(rows: list[dict]) -> dict:
    def q(key, f):
        v = sorted(r[key] for r in rows)
        return v[int(f * (len(v) - 1))]

    out = {k: (q(k, 0.1), q(k, 0.5), q(k, 0.9)) for k, _, _ in METRICS}
    out["share_out_and_back"] = sum(r["out_and_back_pct"] > 50 for r in rows) / len(rows)
    out["share_retraced_30"] = sum(r["retraced_pct"] > 30 for r in rows) / len(rows)
    out["share_closed_400"] = sum(r["closure_m"] < 400 for r in rows) / len(rows)
    return out


def table(groups: dict[str, list[dict]]) -> str:
    names = list(groups)
    sums = {n: summarize(groups[n]) for n in names}
    lines = ["| metric (median, p10-p90) | " + " | ".join(f"{n} (n={len(groups[n])})" for n in names) + " |",
             "|---|" + "---|" * len(names)]
    for key, label, fmt in METRICS:
        cells = [f"{fmt.format(sums[n][key][1])} ({fmt.format(sums[n][key][0])}-{fmt.format(sums[n][key][2])})" for n in names]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    for key, label in (("share_out_and_back", "out-and-back (>50% of second half revisits first)"),
                       ("share_retraced_30", "retraced > 30%"), ("share_closed_400", "ends within 400 m of start")):
        lines.append(f"| {label} | " + " | ".join(f"{sums[n][key]:.0%}" for n in names) + " |")
    return "\n".join(lines)


def main() -> int:
    problem = stack_problem()
    if problem:
        print(problem, file=sys.stderr)
        return 3
    runs = [json.loads(line) for line in (HEALTH / "matched.jsonl").open()]
    starts = load_starts()
    rows = []
    with psycopg.connect(database_url()) as conn:
        for r in runs:
            m = measure(conn, r["coordinates"], r["closure_m"])  # matched runs are already trimmed
            near = [sid for sid, s in starts.items() if _m(r["coordinates"][0], (s["lon"], s["lat"])) <= NEAR_START_M]
            rows.append({"group": "real", "id": r["date"], "kind": "", "near": ",".join(near), **m})
        for sid, s in starts.items():
            miles = sorted(set(s["miles"]) | ({TYPICAL_MILES} if sid in HOME_AREA_STARTS else set()))
            for mi in miles:
                for rank, c in enumerate(top_loops(sid, mi, 3), start=1):
                    trimmed = trim_ends(c.route.coordinates, TRIM_M)
                    closure = _m(c.route.coordinates[0], c.route.coordinates[-1])
                    rows.append({"group": "generated", "id": f"{sid}-{mi:g}mi-#{rank}", "kind": c.kind, "near": sid,
                                 "requested_miles": mi, **measure(conn, trimmed, closure)})

    HEALTH.mkdir(parents=True, exist_ok=True)
    keys = sorted({k for r in rows for k in r})
    with (HEALTH / "calibration_rows.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)

    real = [r for r in rows if r["group"] == "real"]
    gen = [r for r in rows if r["group"] == "generated"]
    gen3 = [r for r in gen if r.get("requested_miles") == TYPICAL_MILES and r["near"] in HOME_AREA_STARTS]
    groups = {
        "real runs": real,
        "generated, all": gen,
        "generated loops": [r for r in gen if r["kind"] == "loop"],
        "generated out-and-backs": [r for r in gen if r["kind"] == "out_and_back"],
        "generated at 3 mi, home areas": gen3,
    }
    near_counts = {sid: sum(sid in r["near"].split(",") for r in real) for sid in starts}
    report = [
        "# Calibration: real runs vs generated routes (decision 011)", "",
        "All routes trimmed 200 m at both ends; identical definitions (api/shape.py, api/route_context.py). "
        "All values measured.", "", table(groups), "",
        "Real runs whose trimmed start is within 1.5 km of a review start: "
        + ", ".join(f"{k} {v}" for k, v in near_counts.items() if v) + ".",
    ]
    (HEALTH / "calibration.md").write_text("\n".join(report) + "\n")
    print("\n".join(report))
    print(f"\nWrote {HEALTH.relative_to(ROOT)}/calibration.md and calibration_rows.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
