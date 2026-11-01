"""Before/after table for every review start (decision 012):  uv run python -m evals.routes.report_starts --label before

For each start and distance in starts.json: the top 3 generated WITHOUT the reviewer's runs (use_prior=False), with
the #1 route's park share, waterfront share and signalized crosswalks per mile, the best park-or-water share in the top
3, and the top 3's candidate types. All shares are measured on routes trimmed 200 m at both ends, as in calibration.
Where the reviewer has 20+ real runs nearby, the real-run gap at 3 mi: best generated score minus the median real
run's, both with "matches routes you run" off (negative = generated is worse). Writes out/review/starts-<label>.md.
"""

import argparse
import json
import statistics as st
import sys
from pathlib import Path

import psycopg

from api.constraints import DEFAULTS
from api.ranking import rank
from api.route_context import score_context
from api.shape import shape_metrics, trim_ends
from etl.load import database_url
from evals.routes.live import load_starts, stack_problem, top_loops

OUT = Path(__file__).resolve().parents[2] / "out" / "review"
MATCHED = Path(__file__).resolve().parents[2] / "data" / "health" / "matched.jsonl"
TRIM_M = 200.0


def real_run_medians(conn) -> dict[str, float]:
    """Median real-run score (familiar off) for the starts the real-run eval judges."""
    if not MATCHED.exists():
        return {}
    from evals.routes.test_real_runs import HOME, _score

    return {sid: st.median(_score(conn, r["coordinates"]) for r in runs) for sid, runs in HOME}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", required=True)
    args = ap.parse_args(argv)
    problem = stack_problem()
    if problem:
        print(problem, file=sys.stderr)
        return 3
    lines = [
        f"# Review starts: {args.label}", "",
        "Generated without the reviewer's runs; shares on routes trimmed 200 m at both ends; all values measured.", "",
        "| start | mi | #1 park % | #1 water % | #1 signals/mi | best park-or-water % in top 3 | top 3 types | real-run gap at 3 mi |",
        "|---|---|---|---|---|---|---|---|",
    ]
    with psycopg.connect(database_url()) as conn:
        medians = real_run_medians(conn)
        for sid, s in load_starts().items():
            for mi in s["miles"]:
                cands = top_loops(sid, mi, 3, use_prior=False)
                if not cands:
                    lines.append(f"| {sid} | {mi:g} | | | | | none generated | |")
                    continue
                ctxs = [score_context(conn, trim_ends(c.route.coordinates, TRIM_M), use_prior=False) for c in cands]
                first = ctxs[0]
                gap = ""
                if sid in medians and mi == 3:
                    best = max(rank(c.kind, shape_metrics(trim_ends(c.route.coordinates, TRIM_M)), DEFAULTS, x).score
                               for c, x in zip(cands, ctxs))
                    gap = f"{best - medians[sid]:+.0f} ({best:.0f} vs {medians[sid]:.0f})"
                types = ", ".join(c.method.replace("_", " ") for c in cands)
                lines.append(
                    f"| {sid} | {mi:g} | {first.park_pct:.0f} | {first.waterfront_pct:.0f} | {first.signals_per_mile:.1f} "
                    f"| {max(x.park_or_water_pct for x in ctxs):.0f} | {types} | {gap} |"
                )
            print(lines[-1], flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"starts-{args.label}.md"
    path.write_text("\n".join(lines) + "\n")
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
