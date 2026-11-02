"""Render the fixed review starts as one HTML page:  uv run python -m evals.routes.render_review

For every start and distance in starts.json, draws the top 3 loops over streets and parks, with the scored fields
and any rule from rejected_routes.json the loop breaks. Writes out/review/index.html (git-ignored: it holds the
reviewer's own start). Reject a route by adding a case to rejected_routes.json; it then fails `pytest evals/`.
"""

import argparse
import html
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import psycopg

from api.elevation import elevation_profile
from api.scripts.make_loop import KIND_LABELS
from api.segments import route_stretches
from etl.load import database_url
from evals.routes.live import load_starts, rule_violations, stack_problem, top_loops

OUT = Path(__file__).resolve().parents[2] / "out" / "review" / "index.html"
TOP = 3
PANEL_PX = 340
PAD_DEG = 0.003
# Sidewalks and crossings are drawn by the street centerlines they run beside; leaving them out keeps the page small.
STREET_SQL = """
SELECT ST_AsGeoJSON(ST_Simplify(geom, 0.00003), 5), highway IN ('footway','path','pedestrian','cycleway','steps','track')
FROM osm_ways WHERE geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)
  AND coalesce(tags->>'footway', '') NOT IN ('sidewalk', 'crossing') AND highway NOT IN ('service', 'motorway', 'motorway_link')
"""
PARK_SQL = """
SELECT ST_AsGeoJSON(ST_Simplify(ST_Intersection(geom, ST_MakeEnvelope(%s, %s, %s, %s, 4326)), 0.00003), 5)
FROM parks WHERE geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)
"""


class Frame:
    """Projects lon/lat into panel pixels, keeping east-west distances true at the frame's latitude."""

    def __init__(self, bbox):
        self.x0, self.y0, x1, y1 = bbox
        self.kx = math.cos(math.radians((self.y0 + y1) / 2))
        w, h = (x1 - self.x0) * self.kx, y1 - self.y0
        self.scale = PANEL_PX / max(w, h)
        self.width, self.height = w * self.scale, h * self.scale

    def path(self, coords) -> str:
        pts = [f"{(x - self.x0) * self.kx * self.scale:.1f},{self.height - (y - self.y0) * self.scale:.1f}" for x, y in coords]
        return "M" + "L".join(pts)


def lines_of(geom: dict):
    t, c = geom["type"], geom["coordinates"]
    if t == "LineString":
        yield c
    elif t in ("MultiLineString", "Polygon"):
        yield from c
    elif t == "MultiPolygon":
        for poly in c:
            yield from poly


def background(conn, frame: Frame, bbox) -> str:
    parks = "".join(
        f'<path d="{frame.path(ring)}Z"/>'
        for (g,) in conn.execute(PARK_SQL, (*bbox, *bbox)) if g for ring in lines_of(json.loads(g))
    )
    streets, paths = [], []
    for g, is_path in conn.execute(STREET_SQL, bbox):
        if g is None:  # simplified away: shorter than the tolerance
            continue
        for line in lines_of(json.loads(g)):
            (paths if is_path else streets).append(frame.path(line))
    return (
        f'<g class="parks">{parks}</g>'
        f'<path class="streets" d="{"".join(streets)}"/><path class="paths" d="{"".join(paths)}"/>'
    )


def panel(frame: Frame, bg_id: str, rank: int, c, start, violations, when=None) -> str:
    lon, lat = start["lon"], start["lat"]
    sx, sy = frame.path([[lon, lat]])[1:].split(",")
    flags = "".join(f'<div class="flag">Rejected rule: {html.escape(v["reason"])}</div>' for r, v in violations if r == rank)
    kind = KIND_LABELS[c.kind]
    dims = "".join(
        f"<li>{html.escape(d.label)}: {html.escape(d.value)} <span class='tag'>{d.status}</span></li>"
        for d in c.ranking.scored()
    )
    missing = ", ".join(d.label for d in c.ranking.not_scored())
    with psycopg.connect(database_url()) as conn:
        stretches = route_stretches(conn, c.route.coordinates, c.route.elevation, when)
    ele = elevation_profile(c.route.coordinates, c.route.elevation)
    names = " → ".join(f"{html.escape(s['properties']['name'])} <span class='m'>mi {s['properties']['from_mile']:.1f}"
                       f"–{s['properties']['to_mile']:.1f}</span>{_crowd_tag(s['properties']['crowd'])}" for s in stretches)
    climb = (f"Climb {ele['gain_m']:.0f} m, steepest {ele['max_grade_pct']:.1f}% <span class='tag'>estimate</span>"
             if ele["status"] == "estimate" else "Climb <span class='tag'>not scored</span>")
    ctx = c.context
    if ctx is not None and ctx.wait_s is not None:
        credit = f", zig-zag alternative at {ctx.wait_credited}" if ctx.wait_credited else ""
        climb += (f" · Wait at lights {ctx.wait_s / 60:.1f} min at {ctx.wait_signals} signals{credit} "
                  f"<span class='tag'>estimate</span>")
    return f"""
<figure class="{'bad' if flags else ''}">
  <svg viewBox="0 0 {frame.width:.0f} {frame.height:.0f}"><use href="#{bg_id}"/>
    <path class="route" d="{frame.path(c.route.coordinates)}"/><circle class="start" cx="{sx}" cy="{sy}" r="5"/></svg>
  <figcaption><b>#{rank}</b> {kind} · score {c.score:.0f} <span class="m">(provisional weights)</span>{flags}
    <div class="m">{html.escape(c.label)} · {c.route.distance_m / 1609.344:.2f} mi ({c.miss_pct:+.0f}%)</div>
    <ul class="m dims">{dims}</ul>
    <div class="m stretches">{names}</div>
    <div class="m">{climb}</div>
    <div class="m todo">Not scored: {html.escape(missing)}</div>
  </figcaption>
</figure>"""


def _crowd_tag(crowd: dict) -> str:
    if crowd["status"] == "estimate":
        return f" <span class='tag crowd-{crowd['value']}'>{crowd['value']} crowd, estimate</span>"
    return f" <span class='tag' title='{html.escape(crowd['basis'])}'>crowd not scored</span>" if crowd["basis"] != "not computed" else ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--with-prior", action="store_true", help="use the reviewer's own runs (familiar placement and score)")
    ap.add_argument("--lights", choices=["waits", "zigzags"], default="zigzags", help="the runner's lights setting")
    ap.add_argument("--crowds", choices=["avoid", "some", "dont_mind"], default="some", help="the runner's crowds setting")
    ap.add_argument("--start", type=datetime.fromisoformat, help="start moment, e.g. 2026-11-03T18:00 (sets crowd bands)")
    ap.add_argument("--out", type=Path, default=OUT, help="where to write the page")
    args = ap.parse_args(argv)
    problem = stack_problem()
    if problem:
        print(problem, file=sys.stderr)
        return 3
    sections = []
    with psycopg.connect(database_url()) as conn:
        for start in load_starts().values():
            for miles in start["miles"]:
                print(f"{start['id']} {miles:g} mi ...", flush=True)
                cands = top_loops(start["id"], miles, TOP, use_prior=args.with_prior,
                                  prefs=(("lights", args.lights), ("crowds", args.crowds)), when=args.start)
                if not cands:
                    sections.append(f"<section><h2>{html.escape(start['address'])} · {miles:g} mi</h2><p>No loop generated.</p></section>")
                    continue
                xs = [x for c in cands for x, _ in c.route.coordinates]
                ys = [y for c in cands for _, y in c.route.coordinates]
                bbox = (min(xs) - PAD_DEG, min(ys) - PAD_DEG, max(xs) + PAD_DEG, max(ys) + PAD_DEG)
                frame = Frame(bbox)
                bg_id = f"bg-{start['id']}-{miles:g}"
                violations = rule_violations(start["id"], miles, cands)
                panels = "".join(panel(frame, bg_id, r, c, start, violations, args.start) for r, c in enumerate(cands, start=1))
                sections.append(f"""
<section><h2>{html.escape(start['address'])} · {miles:g} mi <small>{html.escape(start['why'])}</small></h2>
  <svg width="0" height="0" style="position:absolute"><defs><g id="{bg_id}">{background(conn, frame, bbox)}</g></defs></svg>
  <div class="row">{panels}</div></section>""")

    out = args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    prior = ("Includes the reviewer's own runs (placement along their corridors and the \"matches routes you run\" score)."
             if args.with_prior else "Without the reviewer's own runs: what any runner gets.")
    prior += f" Lights: the runner {'waits for the light' if args.lights == 'waits' else 'zig-zags with the lights'}."
    prior += f" Crowds: {args.crowds.replace('_', ' ')}; " + (
        f"start {args.start:%A %Y-%m-%d %H:%M} (crowd levels are estimates from subway volume and DOT count windows)."
        if args.start else "no start time, so crowds are not scored.")
    out.write_text(PAGE.format(when=datetime.now().strftime("%Y-%m-%d %H:%M"), body="".join(sections), prior=prior))
    print(f"Saved {out}")
    return 0


PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Loop review</title><style>
:root {{ --bg:#fff; --fg:#1d1d1f; --muted:#6e6e73; --street:#c9c9c9; --path:#9a9a9a; --park:#dcefd6; --route:#d62728; --start:#1f63c4; --bad:#fdecec; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#141414; --fg:#eee; --muted:#9a9a9f; --street:#3d3d3d; --path:#5a5a5a; --park:#1f3a1f; --bad:#3a1d1d; }} }}
body {{ background:var(--bg); color:var(--fg); font:14px/1.4 -apple-system, system-ui, sans-serif; margin:0; padding:16px; }}
h1 {{ font-size:20px; margin:0 0 4px; }} h2 {{ font-size:16px; margin:28px 0 8px; }} h2 small {{ color:var(--muted); font-weight:normal; margin-left:6px; }}
.row {{ display:flex; flex-wrap:wrap; gap:12px; }} figure {{ margin:0; width:{px}px; max-width:100%; padding:6px; border-radius:8px; }}
figure.bad {{ background:var(--bad); }} svg {{ width:100%; height:auto; display:block; }}
.parks path {{ fill:var(--park); stroke:none; }} .streets {{ stroke:var(--street); stroke-width:.6; fill:none; }}
.paths {{ stroke:var(--path); stroke-width:.6; stroke-dasharray:2 1.5; fill:none; }}
.route {{ stroke:var(--route); stroke-width:2.4; fill:none; stroke-linejoin:round; }} .start {{ fill:var(--start); stroke:var(--bg); stroke-width:1.5; }}
figcaption {{ margin-top:4px; }} .m {{ color:var(--muted); font-size:12px; }} .todo {{ font-style:italic; }}
.flag {{ color:var(--route); font-weight:600; }} .dims {{ margin:2px 0; padding-left:16px; }}
.crowd-high {{ border-color:#c92a2a; color:#c92a2a; }} .crowd-medium {{ border-color:#e8590c; color:#e8590c; }}
.stretches {{ margin:4px 0; }} .tag {{ font-size:10px; border:1px solid var(--muted); border-radius:3px; padding:0 3px; }}
</style></head><body><h1>Loop review</h1><div class="m">Rendered {when}. Top 3 per start with nothing but the distance stated (shape any, neutral preferences, default no-go zones; park/water and signals measured from PostGIS). {prior} Parks green, paths dashed. Scores use provisional weights. To reject a route, add it to evals/routes/rejected_routes.json.</div>
{body}</body></html>""".replace("{px}", str(PANEL_PX))


if __name__ == "__main__":
    sys.exit(main())
