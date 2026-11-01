"""Turn the matched runs into a per-OSM-way runner prior and the runner's main corridors (decision 011).

    uv run python -m evals.health_routes.build_prior

Reads data/health/matched.jsonl (from match_runs.py; already trimmed 200 m at both ends). A run uses a way when its
matched line covers at least min(USE_MIN_M, half the way's length) within USE_BUFFER_FT of it. Writes, all personal
and git-ignored or local-only:
- PostGIS table runner_prior (way_id, runs, days, last_date): read by the "matches routes you run" dimension;
- data/health/way_prior.csv: the same rows;
- data/health/corridors.geojson: connected stretches of ways used by at least CORRIDOR_MIN_SHARE of runs.
"""

import csv
import json
import sys
from pathlib import Path

import psycopg

from etl.load import database_url

ROOT = Path(__file__).resolve().parents[2]
HEALTH = ROOT / "data" / "health"
USE_BUFFER_FT = 10  # matched geometry sits on the graph, which is built from these ways; 10 ft absorbs rounding
USE_MIN_M = 25
CORRIDOR_MIN_SHARE = 0.10

SCHEMA = """
DROP TABLE IF EXISTS runner_prior;
CREATE TABLE runner_prior (
    way_id bigint PRIMARY KEY,
    runs integer NOT NULL,
    days integer NOT NULL,
    last_date date NOT NULL,
    total_runs integer NOT NULL,  -- runs in the source set, so a share can be computed
    source text NOT NULL,
    built_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE runner_prior IS 'Personal: one runner''s map-matched Apple Health runs (decision 011). Local only.';
"""

USAGE = """
WITH r AS (SELECT run_id, run_date, ST_Transform(geom, 2263) g FROM tmp_runs),
w AS (
    SELECT w.way_id, ST_Transform(w.geom, 2263) g FROM osm_ways w
    WHERE w.geom && (SELECT ST_Extent(geom) FROM tmp_runs)
      -- Not walkable. They still overlap in 2D where they are stacked over or under a path (the FDR over the
      -- East River esplanade), which would otherwise count as "used".
      AND w.highway NOT IN ('motorway', 'motorway_link', 'trunk', 'trunk_link', 'construction', 'proposed')
)
SELECT w.way_id, r.run_id, r.run_date
FROM r JOIN w ON ST_DWithin(r.g, w.g, %(buf)s)
WHERE ST_Length(ST_Intersection(w.g, ST_Buffer(r.g, %(buf)s))) >= LEAST(%(min_ft)s, ST_Length(w.g) * 0.5)
"""

CORRIDORS = """
WITH used AS (
    SELECT p.way_id, p.runs, w.name, w.highway, w.geom FROM runner_prior p JOIN osm_ways w USING (way_id)
    WHERE p.runs >= %(min_runs)s
),
parts AS (SELECT (ST_Dump(ST_LineMerge(ST_Union(geom)))).geom g FROM used)
SELECT ST_AsGeoJSON(parts.g, 6),
       round(ST_Length(ST_Transform(parts.g, 2263)) * 0.3048) AS meters,
       max(u.runs) AS peak_runs, round(avg(u.runs)) AS mean_runs,
       string_agg(DISTINCT coalesce(u.name, u.highway), ', ') AS names
FROM parts JOIN used u ON ST_Intersects(parts.g, u.geom)
GROUP BY parts.g
HAVING ST_Length(ST_Transform(parts.g, 2263)) * 0.3048 >= 300
ORDER BY ST_Length(ST_Transform(parts.g, 2263)) * avg(u.runs) DESC
"""


def main() -> int:
    runs = [json.loads(line) for line in (HEALTH / "matched.jsonl").open()]
    if not runs:
        print("No matched runs. Run match_runs.py first.", file=sys.stderr)
        return 1
    with psycopg.connect(database_url()) as conn:
        conn.execute("CREATE TEMP TABLE tmp_runs (run_id int, run_date date, geom geometry(LineString, 4326))")
        with conn.cursor().copy("COPY tmp_runs (run_id, run_date, geom) FROM STDIN") as copy:
            for i, r in enumerate(runs):
                wkt = ",".join(f"{x} {y}" for x, y in r["coordinates"])
                copy.write_row((i, r["date"], f"SRID=4326;LINESTRING({wkt})"))
        rows = conn.execute(USAGE, {"buf": USE_BUFFER_FT, "min_ft": USE_MIN_M / 0.3048}).fetchall()

        per_way: dict[int, dict] = {}
        for way_id, run_id, run_date in rows:
            w = per_way.setdefault(way_id, {"runs": set(), "days": set(), "last": run_date})
            w["runs"].add(run_id)
            w["days"].add(run_date)
            w["last"] = max(w["last"], run_date)

        conn.execute(SCHEMA)
        source = f"apple-health matched runs {runs[0]['date']}..{runs[-1]['date']} (n={len(runs)})"
        with conn.cursor().copy("COPY runner_prior (way_id, runs, days, last_date, total_runs, source) FROM STDIN") as copy:
            for way_id, w in per_way.items():
                copy.write_row((way_id, len(w["runs"]), len(w["days"]), w["last"], len(runs), source))

        min_runs = max(2, round(CORRIDOR_MIN_SHARE * len(runs)))
        corridors = conn.execute(CORRIDORS, {"min_runs": min_runs}).fetchall()

    with (HEALTH / "way_prior.csv").open("w", newline="") as fh:
        out = csv.writer(fh)
        out.writerow(["way_id", "runs", "days", "last_date"])
        for way_id, w in sorted(per_way.items(), key=lambda kv: -len(kv[1]["runs"])):
            out.writerow([way_id, len(w["runs"]), len(w["days"]), w["last"]])
    features = [
        {"type": "Feature", "geometry": json.loads(g),
         "properties": {"meters": int(m), "peak_runs": peak, "mean_runs": int(mean), "names": names}}
        for g, m, peak, mean, names in corridors
    ]
    (HEALTH / "corridors.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}))

    print(f"{len(runs)} runs -> {len(per_way)} OSM ways used at least once; "
          f"{sum(len(w['runs']) >= 2 for w in per_way.values())} used on 2+ runs")
    print(f"Corridors (ways on >= {min_runs} runs, merged, 300 m or longer): {len(features)}")
    for f in features[:8]:
        p = f["properties"]
        print(f"  {p['meters']:>5} m  peak {p['peak_runs']:>3} runs, mean {p['mean_runs']:>3}  {p['names'][:90]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
