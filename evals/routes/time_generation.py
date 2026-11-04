"""Where generation time goes, per review row and lights setting (decision 018).

    uv run python -m evals.routes.time_generation --out out/review/timing.json [--label before]
    uv run python -m evals.routes.time_generation --pin evals/routes/pinned_top3.json

Runs the same generation as evals/routes/live.top_loops (default zones, known closures, the reviewer's runs on,
top 3), uncached, with every router call, context score and anchor lookup timed. Times inside the job pool are
summed across its worker threads, so they add up to more than the wall clock. Needs the live stack.

--pin writes today's top 3 per row (label, kind, distance and a fingerprint of the route) for
evals/routes/test_pinned_top3.py. Nothing about the route's geometry beyond a hash is written.
"""

import argparse
import hashlib
import json
import statistics
import threading
import time
from collections import defaultdict
from pathlib import Path

from api.constraints import DEFAULTS
from api.generate import generate_loops
from api.nogo import resolve as resolve_zones
from api.scripts.make_loop import (
    DB_FEATURE_ANCHOR_SOURCES,
    context_for,
    current_grid,
    db_closures,
    familiar_anchors,
    routers_for,
)
from evals.routes.live import load_starts

LIGHTS = ("zigzags", "waits")
SOURCE_NAMES = ("corridor anchors", "park anchors", "water anchors")


def fingerprint(coords: list[list[float]]) -> str:
    """A short hash of the route at about 10 m precision: equal for the same route, and no geometry in it."""
    text = ";".join(f"{c[0]:.4f},{c[1]:.4f}" for c in coords)
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def summary(c) -> dict:
    return {"label": c.label, "kind": c.kind, "distance_m": round(c.route.distance_m),
            "score": round(c.score, 2), "fingerprint": fingerprint(c.route.coordinates)}


class Timer:
    """Thread-safe call counts and summed seconds per name."""

    def __init__(self):
        self.lock = threading.Lock()
        self.calls = defaultdict(int)
        self.seconds = defaultdict(float)

    def wrap(self, name, fn):
        def timed(*a, **kw):
            t = time.perf_counter()
            try:
                return fn(*a, **kw)
            finally:
                with self.lock:
                    self.calls[name] += 1
                    self.seconds[name] += time.perf_counter() - t

        return timed


def run_row(start_id: str, miles: float, lights: str) -> dict:
    s = load_starts()[start_id]
    t = Timer()
    t0 = time.perf_counter()
    grid = current_grid(s["lat"], s["lon"])
    t_grid = time.perf_counter() - t0
    zones, _ = resolve_zones([])
    t1 = time.perf_counter()
    closures = db_closures(s["lat"], s["lon"], miles)
    t_closures = time.perf_counter() - t1
    prefs = {**DEFAULTS, "lights": lights}
    route_fn, round_trip_fn, area_route_fn = routers_for(zones, lights, closures)
    sources = [t.wrap(n, f) for n, f in zip(SOURCE_NAMES, DB_FEATURE_ANCHOR_SOURCES)]
    t2 = time.perf_counter()
    result = generate_loops(
        s["lat"], s["lon"], miles, grid, route_fn=t.wrap("router: route", route_fn),
        round_trip_fn=t.wrap("router: round trip", round_trip_fn), top_n=3, shape="any", prefs=prefs, avoid=zones,
        closures=closures, context_fn=t.wrap("context score", context_for(lights, grid, use_prior=True)),
        anchor_fn=t.wrap("familiar anchors", familiar_anchors), feature_anchor_fn=sources,
        area_route_fn=t.wrap("router: feature area", area_route_fn),
    )
    t_generate = time.perf_counter() - t2
    return {
        "row": f"{start_id} {miles:g} mi", "start": start_id, "miles": miles, "lights": lights,
        "setup_s": {"grid": round(t_grid, 3), "closures": round(t_closures, 3)},
        "generate_s": round(t_generate, 3), "timing": result.timing, "jobs": result.generated,
        "rejected": dict(result.rejected),
        "calls": dict(t.calls), "summed_s": {k: round(v, 3) for k, v in t.seconds.items()},
        "top3": [summary(c) for c in result.candidates],
        "provisional_top3": [summary(c) for c in result.provisional],
    }


def rows():
    return [(sid, mi) for sid, s in load_starts().items() for mi in s["miles"]]


def print_table(results: list[dict]) -> None:
    print(f"{'row':24s} {'lights':8s} {'first':>6s} {'winner':>7s} {'pool':>6s} {'jobs':>5s} "
          f"{'route':>12s} {'area':>12s} {'trip':>10s} {'context':>12s} {'anchors':>8s}")
    for r in results:
        c, s, tm = r["calls"], r["summed_s"], r["timing"]
        anchors = sum(s.get(n, 0) for n in (*SOURCE_NAMES, "familiar anchors"))
        cell = lambda k: f"{c.get(k, 0):3d} {s.get(k, 0):6.1f}s"
        print(f"{r['row']:24s} {r['lights']:8s} {tm['first_candidate_s'] or 0:6.2f} {tm['winner_arrived_s'] or 0:7.2f} "
              f"{r['generate_s']:6.2f} {r['jobs']:5d} {cell('router: route'):>12s} {cell('router: feature area'):>12s} "
              f"{cell('router: round trip'):>10s} {cell('context score'):>12s} {anchors:7.2f}s")
    pools = [r["generate_s"] for r in results]
    firsts = [r["timing"]["first_candidate_s"] or 0 for r in results]
    print(f"\npool: median {statistics.median(pools):.2f} s, max {max(pools):.2f} s; "
          f"first candidate: median {statistics.median(firsts):.2f} s, max {max(firsts):.2f} s")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, help="write every row's timing and top 3 to this JSON file")
    ap.add_argument("--pin", type=Path, help="write today's top 3 per row for the pinned-top-3 eval")
    ap.add_argument("--label", default="", help="a name for this run, kept in the JSON")
    args = ap.parse_args(argv)
    from api import scoring_pool

    scoring_pool.warm()  # start the scoring processes, as a server would at startup
    run_row(*rows()[0], LIGHTS[0])  # warm GraphHopper and Postgres caches; not counted
    results = []
    for lights in LIGHTS:
        for sid, mi in rows():
            results.append(run_row(sid, mi, lights))
            print(f"  {results[-1]['row']} {lights}: pool {results[-1]['generate_s']:.2f} s", flush=True)
    print_table(results)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"label": args.label, "rows": results}, indent=1))
    if args.pin:
        pinned = {f"{r['start']}|{r['miles']:g}|{r['lights']}": r["top3"] for r in results}
        args.pin.write_text(json.dumps({"_about": "Today's top 3 per review row and lights setting (decision 018), "
                                        "written by evals/routes/time_generation.py --pin. Fingerprints hash the "
                                        "route at about 10 m; no geometry is stored.", "rows": pinned}, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
