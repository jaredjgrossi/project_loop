"""Run the parse evals and print a pass/fail table (docs/phase3/parse-evals-v1.md).

    uv run python -m evals.parse.run                       # the stub parser: everything fails
    uv run python -m evals.parse.run --parser api.parse:parse --case R02 --case P17

`needs` marks cases whose fields land in a later Phase 3 step (end, via, reuse, hills, planned); they are counted
apart. Exit status is 0 unless --strict and a case that needs nothing later fails.
"""

import argparse
import importlib
import sys
import time

from evals.parse.fixtures import build_request, load_cases, load_contexts
from evals.parse.grader import Grade, grade


def load_parser(spec: str):
    module, _, name = spec.partition(":")
    return getattr(importlib.import_module(module), name or "parse")


def template_keys() -> set | None:
    try:
        from api.copy import TEMPLATES  # added in step 4; until then only the presence of a key is checked
    except ImportError:
        return None
    return set(TEMPLATES)


def run(parser, case_ids: list[str] | None = None) -> list[tuple[dict, Grade, float]]:
    contexts, keys = load_contexts(), template_keys()
    rows = []
    for case in load_cases(case_ids):
        t0 = time.perf_counter()
        try:
            output = parser(build_request(case, contexts))
        except Exception as e:  # a crash is a failed case, not a failed run
            output = {"error": f"{type(e).__name__}: {e}"}
        rows.append((case, grade(case, output, keys), time.perf_counter() - t0))
    return rows


def table(rows: list[tuple[dict, Grade, float]]) -> str:
    lines = [f"{'case':<5} {'ctx':<3} {'expect':<10} {'got':<10} {'needs':<10} {'result':<6} first reason",
             "-" * 100]
    for case, g, _ in rows:
        reason = g.reasons[0] if g.reasons else ""
        lines.append(f"{case['id']:<5} {case['context']:<3} {case['expect']['outcome']:<10} {g.outcome or '-':<10} "
                     f"{','.join(case['needs']) or '-':<10} {'PASS' if g.passed else 'FAIL':<6} {reason[:60]}")
    now = [(c, g) for c, g, _ in rows if not c["needs"]]
    later = [(c, g) for c, g, _ in rows if c["needs"]]
    passed = sum(g.passed for _, g, _ in rows)
    lines += ["-" * 100,
              f"passed {passed}/{len(rows)}  ·  needing nothing later: {sum(g.passed for _, g in now)}/{len(now)}  ·  "
              f"needing a later step: {sum(g.passed for _, g in later)}/{len(later)}"]
    secs = sorted(s for _, _, s in rows)
    if secs:
        lines.append(f"median {secs[len(secs) // 2]:.3f} s per parse")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--parser", default="evals.parse.stub:parse", help="module:function (default: the stub)")
    ap.add_argument("--case", action="append", help="run only this case id (repeatable)")
    ap.add_argument("-v", "--verbose", action="store_true", help="print every reason for each failed case")
    ap.add_argument("--strict", action="store_true", help="exit 1 if a case that needs nothing later fails")
    args = ap.parse_args(argv)
    rows = run(load_parser(args.parser), args.case)
    print(table(rows))
    if args.verbose:
        for case, g, _ in rows:
            if not g.passed:
                print(f"\n{case['id']}  {case['text']!r}\n  " + "\n  ".join(g.reasons))
    failed_now = any(not g.passed and not c["needs"] for c, g, _ in rows)
    return 1 if args.strict and failed_now else 0


if __name__ == "__main__":
    sys.exit(main())
