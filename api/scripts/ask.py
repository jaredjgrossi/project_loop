"""Send a typed request to the Loop API and print the stream, for testing without the phone (Phase 3, step 5).

    python -m api.scripts.ask "6 mi loop, mostly waterfront" --at kips-bay
    python -m api.scripts.ask "run to the park" --at kips-bay --answer a     # answers the question, if one comes
    python -m api.scripts.ask "5k" --url http://<mac>.<tailnet>.ts.net:8000 --json

Each event prints with the seconds since send. A question prompts for an answer (an option letter, or typed text)
unless --answer gives it; the answer goes back as a new POST, as the app sends it. Starts are the public stand-ins
in evals/routes/starts.json, never a real home. The Loop token comes from .env (LOOP_TOKEN).
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from api.env import load_env

NEW_YORK = ZoneInfo("America/New_York")


def sse_events(lines):
    """(event, data) from server-sent event lines."""
    name, data = None, []
    for line in lines:
        if line == "":
            if data:
                yield name, json.loads("\n".join(data))
            name, data = None, []
        elif line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
    if data:
        yield name, json.loads("\n".join(data))


def describe(ev: dict) -> str:
    kind = ev["event"]
    if kind == "parsed":
        out = ["chips: " + " · ".join(f"{c['text']} ({c['source']})" for c in ev["chips"])]
        out += [f"can't: {c['text']}" for c in ev["cant"]]
        out += [f"note:  {n['text']}" for n in ev["notes"]]
        q = ev.get("question")
        if q:
            out.append(f"question ({q['from']}, about {q['about']}): {q['text']}")
            out += [f"   {o['id']}) {o['text']}" for o in q["options"]]
            if q["allow_text"]:
                out.append("   or type an answer")
        return "\n           ".join(out)
    if kind in ("top3", "provisional", "final"):
        routes = ", ".join(f"#{r['rank']} {r['label']} {r['distance']['value']} mi" for r in ev["routes"]) or "none"
        extra = f"; best of {ev['pool_size']}" if kind == "final" and ev.get("pool_size") else ""
        notes = "".join(f"\n           note:  {n['text']}" for n in ev.get("notes") or [])
        return f"{ev['route_id']} at {ev['elapsed_s']:.2f} s engine time: {routes}{extra}{notes}"
    if kind == "error":
        return f"{ev['code']}: {ev['text']}"
    return ""


def main(argv: list[str] | None = None) -> int:
    from evals.routes.live import load_starts

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("text", help="the request, as the runner types it")
    ap.add_argument("--url", default=os.environ.get("LOOP_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--at", default="kips-bay", help="the phone's location: a stand-in start id, or 'off'")
    ap.add_argument("--home", default="kips-bay", help="the saved Home: a stand-in start id, or 'none'")
    ap.add_argument("--usual-mi", type=float, default=3.1)
    ap.add_argument("--usual-time", default="07:00")
    ap.add_argument("--answer", action="append", default=[], help="answer(s) to questions, in order")
    ap.add_argument("--json", action="store_true", help="print each event's full JSON")
    args = ap.parse_args(argv)

    load_env()
    token = os.environ.get("LOOP_TOKEN")
    if not token:
        print("LOOP_TOKEN isn't set (.env).", file=sys.stderr)
        return 2
    starts = load_starts()
    loc = None if args.at == "off" else {"lat": starts[args.at]["lat"], "lon": starts[args.at]["lon"], "accuracy_m": 15}
    saved = [] if args.home == "none" else [{"id": "home", "label": "Home", "lat": starts[args.home]["lat"],
                                             "lon": starts[args.home]["lon"]}]
    base = {"v": 1, "client": {"now": datetime.now(NEW_YORK).isoformat(timespec="seconds"),
                               "tz": "America/New_York", "location": loc},
            "profile": {"usual_distance_mi": args.usual_mi, "usual_time": args.usual_time, "saved_places": saved},
            "recent_routes": []}
    payload = base | {"text": args.text}
    answers = list(args.answer)
    headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}
    t0 = time.perf_counter()
    with httpx.Client(timeout=httpx.Timeout(10, read=120)) as client:
        while payload is not None:
            question = parse_id = None
            with client.stream("POST", f"{args.url}/v1/runs", json=payload, headers=headers) as resp:
                if resp.status_code != 200:
                    print(f"HTTP {resp.status_code}: {resp.read().decode()[:200]}", file=sys.stderr)
                    return 3
                for name, ev in sse_events(resp.iter_lines()):
                    print(f"{time.perf_counter() - t0:6.2f} s  {name:<11} {describe(ev)}", flush=True)
                    if args.json:
                        print(json.dumps(ev, indent=1))
                    if name == "parsed" and ev.get("question"):
                        question, parse_id = ev["question"], ev["parse_id"]
                    if name == "error":
                        return 4
            payload = None
            if question:
                given = answers.pop(0) if answers else input("answer> ").strip()
                option = next((o["id"] for o in question["options"] if o["id"] == given.lower()), None)
                payload = base | {"answer": {"parse_id": parse_id, "question_id": question["id"],
                                             "option_id": option, "text": None if option else given}}
                t0 = time.perf_counter()
    return 0


if __name__ == "__main__":
    sys.exit(main())
