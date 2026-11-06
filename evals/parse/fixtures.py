"""Load the parse-eval fixtures and build the request each case sends (docs/phase3/parse-contract-v1.md).

A case file holds the context id, the runner's text and what must come out. The request is the contract's
`POST /v1/runs` body: the text plus the context's client, profile and recent routes. Labels and stand-in notes in
`contexts.json` are for people reading the fixture and are dropped from the request.
"""

import json
from pathlib import Path

HERE = Path(__file__).parent
CASES_DIR = HERE / "cases"

_HUMAN_ONLY = {"label", "stand_in"}


def load_contexts() -> dict:
    raw = json.loads((HERE / "contexts.json").read_text())
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def load_recent_routes(name: str | None) -> list[dict]:
    if name is None:
        return []
    return json.loads((HERE / name).read_text())["routes"]


def load_cases(ids: list[str] | None = None) -> list[dict]:
    cases = sorted((json.loads(p.read_text()) for p in CASES_DIR.glob("*.json")), key=lambda c: c["seq"])
    if ids:
        wanted = {i.upper() for i in ids}
        cases = [c for c in cases if c["id"].upper() in wanted]
    return cases


def _strip(obj):
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in obj.items() if k not in _HUMAN_ONLY}
    if isinstance(obj, list):
        return [_strip(v) for v in obj]
    return obj


def build_request(case: dict, contexts: dict) -> dict:
    ctx = contexts[case["context"]]
    return {
        "v": 1,
        "text": case["text"],
        "client": _strip(ctx["client"]),
        "profile": _strip(ctx["profile"]),
        "recent_routes": load_recent_routes(ctx["recent_routes"]),
    }
