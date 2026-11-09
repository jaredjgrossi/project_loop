"""Grade one parse against its case, following the Grading section of docs/phase3/parse-evals-v1.md.

What a parser returns (the harness's interface; `api/parse.py` will return this shape):

    {
      "parsed": {                      # the contract's `parsed` event
        "chips": [{"id", "field", "text", "source", ...}],
        "question": {"id", "about", "from", "text", "options": [{"id", "text"}], "allow_text"} | None,
        "cant": [{"id", "gap", "text"}],
        "notes": [{"id", "key", "text", "trust"}],
        "constraints": {...},          # RunConstraints as a dict; partial while a question is open
      },
      "trace": {                       # for grading only; never sent to the phone
        "sources": {"distance_mi": "usual", "planned.start_time": "usual", ...},
        "lookups": [{"name": "Penn Station", "role": "start"}],
        "routing_calls": 0,
        "texts": [{"text": "6 mi", "key": "chip.distance"}],   # every string the runner sees, with its template key
      },
    }

or {"error": "..."} when the parser failed. Place refs in constraints are {"kind": "place", "name": ...} or
{"kind": "saved", "id": ...}; avoids are {"name", "how"}, with how "along" or "area".

A case passes when its main expectation or any listed alternative passes. Must-nots apply either way.
"""

import json
import math
import re
from dataclasses import dataclass, field

OUTCOMES = ("PARSE", "PARSE+CANT", "ASK")
SOURCES = ("said", "preset", "default", "usual")
ABOUTS = ("distance", "start", "end", "via", "time", "reuse", "amount")
FROMS = ("parser", "places", "engine")
GAPS = tuple(f"G{i}" for i in range(1, 12)) + ("bike_lanes",)
NOTE_KEYS = ("crowds_estimated", "fountains_seasonal")
NEEDS = ("end", "via", "reuse", "hills", "planned")

# Every RunConstraints field after Phase 3, with its schema default. A field at its default is "not set".
SCHEMA_DEFAULTS = {
    "start_address": None, "use_my_location": False, "start_place": None, "end_place": None, "via_places": [],
    "distance_mi": None, "tolerance_pct": 5, "shape": "any", "avoid_places": [], "amenities": [],
    "start_time": None, "start_date": None, "mode": None, "lights": None, "crowds": None, "scenery": None,
    "surface": None, "turns": None, "familiar": None, "hills": None, "reuse_route_id": None, "reverse": False,
    "planned": None, "sources": {}, "spans": {},
}
KNOWN_FIELDS = tuple(SCHEMA_DEFAULTS)

# The chip each field shows on (contract: chips). Tolerance folds into the distance chip; planned has no chip here.
FIELD_CHIP = {
    "start_address": "start", "use_my_location": "start", "start_place": "start", "end_place": "end",
    "via_places": "via", "distance_mi": "distance", "tolerance_pct": "distance", "start_time": "time",
    "start_date": "time", "shape": "shape", "mode": "mode", "lights": "lights", "crowds": "crowds",
    "scenery": "scenery", "surface": "surface", "turns": "turns", "familiar": "familiar", "hills": "hills",
    "avoid_places": "avoid", "amenities": "amenity", "reuse_route_id": "reuse", "reverse": "reverse", "planned": None,
    "sources": None, "spans": None,
}
NUMBER_TOL = {"distance_mi": 0.05, "tolerance_pct": 0.1, "at_mile": 0.05}
PARSED_KEYS = {"event", "v", "parse_id", "chips", "question", "cant", "notes", "reach_m", "constraints"}  # reach_m: step 7b
MUST_NOT_CHECKS = ("no_question", "no_free_text", "field_absent", "field_not", "lookup_not_called", "no_cant",
                   "avoid_excludes", "text_absent")


@dataclass
class Grade:
    id: str
    passed: bool
    outcome: str | None  # what the parser produced: PARSE, PARSE+CANT, ASK, or None on error
    reasons: list[str] = field(default_factory=list)
    stats: dict | None = None  # the parser's Claude call: model, tokens, cost, latency


def norm(s: str) -> str:
    """Names compare as the places table compares them: "First Avenue" is "1st Ave" (api.places.normalize)."""
    from api.places import normalize
    return normalize(s.replace("–", "-").replace("—", "-"))


def words(s: str) -> list[str]:
    return re.findall(r"\+?[\w.]+", s.casefold())


def outcome_of(parsed: dict) -> str:
    if parsed.get("question"):
        return "ASK"
    return "PARSE+CANT" if parsed.get("cant") else "PARSE"


def is_unset(name: str, value) -> bool:
    return value is None or value == SCHEMA_DEFAULTS.get(name, None) or value == []


# ---- value comparison -------------------------------------------------------------------------------------------

def _same_number(name: str, want, got) -> bool:
    if isinstance(got, bool) or not isinstance(got, (int, float)):
        return False
    return math.isclose(want, got, abs_tol=NUMBER_TOL.get(name, 1e-9))


def _same_place(want: dict, got) -> bool:
    """want: {"place": name} | {"address": text} | {"saved": id}, with an optional "borough" (rule R19)."""
    if not isinstance(got, dict):
        return False
    if "borough" in want and got.get("borough") != want["borough"]:
        return False
    for kind in ("place", "address"):
        if kind in want:
            return got.get("kind") == kind and norm(str(got.get("name", ""))) == norm(want[kind])
    return got.get("kind") == "saved" and got.get("id") == want["saved"]


def _cross_numbers(text: str) -> list[int]:
    return [int(n) for n in re.findall(r"(\d+)(?:st|nd|rd|th)\b", text)]


def _same_avoid(want: dict, got) -> bool:
    """want: {"name", "how"}, or a stretch: {"street", "within": [from, to], "how"}, which matches any stretch of that
    street whose cross streets both lie inside `within` ("1st Ave, E 25th–E 34th St" inside E 23rd–E 34th)."""
    if not isinstance(got, dict):
        return False
    if "how" in want and got.get("how") != want["how"]:
        return False
    if "street" not in want:
        return norm(str(got.get("name", ""))) == norm(want["name"])
    street, _, stretch = str(got.get("name", "")).partition(",")
    if norm(street) != norm(want["street"]):
        return False
    lo, hi = (_cross_numbers(w)[0] for w in want["within"])
    got_nums = _cross_numbers(stretch)
    return len(got_nums) == 2 and all(lo <= n <= hi for n in got_nums) and got_nums[0] != got_nums[1]


def _same_amenity(want: dict, got) -> bool:
    return (isinstance(got, dict) and got.get("kind") == want["kind"]
            and _same_number("at_mile", want["at_mile"], got.get("at_mile")))


def _unordered(want: list, got, same) -> bool:
    if not isinstance(got, list) or len(got) != len(want):
        return False
    left = list(got)
    for w in want:
        hit = next((g for g in left if same(w, g)), None)
        if hit is None:
            return False
        left.remove(hit)
    return True


def same_value(name: str, want, got) -> bool:
    if name in ("start_place", "end_place"):
        return _same_place(want, got)
    if name == "via_places":  # order matters: the route goes through them in turn
        return (isinstance(got, list) and len(got) == len(want)
                and all(_same_place(w, g) for w, g in zip(want, got)))
    if name == "avoid_places":
        return _unordered(want, got, _same_avoid)
    if name == "amenities":
        return _unordered(want, got, _same_amenity)
    if isinstance(want, bool):
        return got is want
    if isinstance(want, (int, float)):
        return _same_number(name, want, got)
    return want == got


def _show(v) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)


# ---- the seven grading rules ------------------------------------------------------------------------------------

def _check_fields(listed: dict, constraints: dict, sources: dict, chips: list, prefix: str = "") -> list[str]:
    """Rule 2: every listed field matches, and its source matches on the trace and on its chip."""
    out = []
    for name, spec in listed.items():
        if name == "planned":
            got = constraints.get("planned")
            if not isinstance(got, dict):
                out.append(f"planned: expected a planned run, got {_show(got)}")
            else:
                out += _check_fields(spec["value"], got, sources, [], prefix="planned.")
            continue
        got = constraints.get(name)
        if not same_value(name, spec["value"], got):
            out.append(f"{prefix}{name}: expected {_show(spec['value'])}, got {_show(got)}")
            continue
        if "source" in spec and sources.get(prefix + name) != spec["source"]:
            out.append(f"{prefix}{name}: source expected {spec['source']}, got {sources.get(prefix + name)}")
    if prefix:
        return out
    # Chips: one per field that has one. The time chip carries start_time's source when both are listed; the
    # distance chip carries distance_mi's.
    for name, spec in listed.items():
        chip = FIELD_CHIP.get(name)
        if chip is None:
            continue
        on_chip = [c for c in chips if c.get("field") == chip]
        if not on_chip:
            out.append(f"no '{chip}' chip for {name}")
            continue
        if "source" not in spec:
            continue
        if name == "tolerance_pct" and "distance_mi" in listed:
            continue
        if name == "start_date" and "start_time" in listed:
            continue
        if not any(c.get("source") == spec["source"] for c in on_chip):
            out.append(f"'{chip}' chip source expected {spec['source']}, got "
                       f"{', '.join(str(c.get('source')) for c in on_chip)}")
    return out


CODE_FILLED = ("default", "preset", "usual")  # rule 3's "code-filled defaults": from code, the presets or the profile
CONTEXT_TODAY = "2026-11-03"  # every context's day (contexts.json); a said "today" equals what code would fill in


def _check_unlisted(listed: dict, constraints: dict, sources: dict) -> list[str]:
    """Rule 3: nothing beyond the listed fields is set, except values code filled in: defaults, presets and the
    runner's usual values (R2). An unlisted day equal to today is what code fills in anyway."""
    out = []
    for name, value in constraints.items():
        if name in ("sources", "spans"):  # where values and words came from: graded through chips (rules 2, 8)
            continue
        if name not in SCHEMA_DEFAULTS:
            out.append(f"unknown field {name}")
        elif name == "start_date" and str(value) == CONTEXT_TODAY:
            continue
        elif name not in listed and not is_unset(name, value) and sources.get(name) not in CODE_FILLED:
            out.append(f"unlisted field set: {name}={_show(value)} (source {sources.get(name)})")
    return out


def _check_question(want: dict | None, q, routing_calls: int) -> list[str]:
    """Rule 5: exactly one question, about and from match, options match where listed, and no routing call."""
    if want is None:
        return []
    if not isinstance(q, dict):
        return [f"expected one question, got {_show(q)}"]
    out = []
    for k in ("about", "from"):
        if q.get(k) != want[k]:
            out.append(f"question {k}: expected {want[k]}, got {q.get(k)}")
    opts = [o.get("text", "") for o in q.get("options") or []]
    if len(opts) > 4:
        out.append(f"question has {len(opts)} options; at most 4")
    if "options" in want:
        expected = want["options"]
        matched = [any(set(words(e)) <= set(words(o)) for o in opts) for e in expected]
        if len(opts) != len(expected) or not all(matched):
            out.append(f"question options: expected {expected}, got {opts}")
    if "min_options" in want and len(opts) < want["min_options"]:
        out.append(f"question options: expected at least {want['min_options']}, got {len(opts)}")
    if "allow_text" in want and bool(q.get("allow_text")) != want["allow_text"]:
        out.append(f"question allow_text: expected {want['allow_text']}, got {q.get('allow_text')}")
    if routing_calls:
        out.append(f"a question was asked but {routing_calls} routing call(s) were made")
    return out


def _check_lines(want_gaps: list, want_keys: list, parsed: dict) -> list[str]:
    """Rule 4: every listed can't-do line (by gap id) and note (by key) is present."""
    gaps = {c.get("gap") for c in parsed.get("cant") or []}
    keys = {n.get("key") for n in parsed.get("notes") or []}
    return ([f"missing can't-do line {g}" for g in want_gaps if g not in gaps]
            + [f"missing note {k}" for k in want_keys if k not in keys])


def visible_texts(parsed: dict, include_cant: bool = True) -> list[str]:
    texts = [c.get("text", "") for c in parsed.get("chips") or []]
    q = parsed.get("question")
    if isinstance(q, dict):
        texts += [q.get("text", "")] + [o.get("text", "") for o in q.get("options") or []]
    if include_cant:
        texts += [c.get("text", "") for c in parsed.get("cant") or []]
    texts += [n.get("text", "") for n in parsed.get("notes") or []]
    return texts


def _check_templates(parsed: dict, trace: dict, template_keys: set | None) -> list[str]:
    """Rule 7: every string the runner sees was rendered from a template key."""
    keyed: dict[str, str] = {}
    for t in trace.get("texts") or []:
        if t.get("key"):
            keyed.setdefault(t.get("text", ""), t["key"])
    out = []
    for text in visible_texts(parsed):
        key = keyed.get(text)
        if key is None:
            out.append(f"text not from a template: {text!r}")
        elif template_keys is not None and key not in template_keys:
            out.append(f"unknown template key {key!r} for {text!r}")
    return out


def _check_must_not(rules: list[dict], output: dict) -> list[str]:
    """Rule 6: no must-not is violated."""
    parsed, trace = output.get("parsed") or {}, output.get("trace") or {}
    constraints = parsed.get("constraints") or {}
    out = []
    for r in rules:
        kind, broke = r["check"], False
        if kind == "no_question":
            broke = bool(parsed.get("question"))
        elif kind == "no_free_text":
            broke = bool(set(parsed) - PARSED_KEYS) or bool(set(output) - {"parsed", "trace"})
        elif kind == "field_absent":
            broke = not is_unset(r["field"], constraints.get(r["field"]))
        elif kind == "field_not":
            got = constraints.get(r["field"])
            broke = got is None if r["value"] is None else same_value(r["field"], r["value"], got)
        elif kind == "lookup_not_called":
            broke = any(norm(r["name_contains"]) in norm(str(lk.get("name", "")))
                        and ("role" not in r or lk.get("role") == r["role"])
                        for lk in trace.get("lookups") or [])
        elif kind == "no_cant":
            broke = bool(parsed.get("cant"))
        elif kind == "avoid_excludes":
            for a in constraints.get("avoid_places") or []:
                name = norm(a.get("name", "") if isinstance(a, dict) else str(a))
                hit = name == norm(r["match"]) if r.get("exact") else norm(r["match"]) in name
                how_ok = "how" not in r or (isinstance(a, dict) and a.get("how") == r["how"])
                broke = broke or (hit and how_ok)
        elif kind == "text_absent":
            texts = visible_texts(parsed, include_cant=r["where"] != "visible_except_cant")
            if r["where"] == "visible_and_constraints":
                texts.append(json.dumps(constraints, default=str))
            broke = any(re.search(p, t, re.IGNORECASE) for p in r["patterns"] for t in texts)
        else:
            raise ValueError(f"unknown must-not check {kind}")
        if broke:
            out.append(f"must not: {r['why']}")
    return out


def _check_spans(text: str, parsed: dict) -> list[str]:
    """Rule 8 (the request screen, 2026-11-08): every chip the runner said has a span, the runner's own words at
    those positions in the request text; every other chip has span null. The question names the chip it's about
    (chip_id), which is a chip in the event, or null."""
    out = []
    chips = parsed.get("chips") or []
    for c in chips:
        if "span" not in c:
            out.append(f"chip {c.get('id')}: no span field")
            continue
        span = c["span"]
        if c.get("source") != "said":
            if span is not None:
                out.append(f"chip {c['id']}: a {c.get('source')} value has a span")
            continue
        if not isinstance(span, dict):
            out.append(f"chip {c['id']} ({c.get('text')!r}): said, but no span")
        elif not (0 <= span.get("start", -1) < span.get("end", -1) <= len(text)) \
                or text[span["start"]:span["end"]] != span.get("text"):
            out.append(f"chip {c['id']}: span {span} isn't the request's words at those positions")
    q = parsed.get("question")
    if q is not None:
        if "chip_id" not in q:
            out.append("question: no chip_id field")
        elif q["chip_id"] is not None and q["chip_id"] not in {c.get("id") for c in chips}:
            out.append(f"question: chip_id {q['chip_id']} isn't a chip")
    return out


def _grade_expectation(exp: dict, parsed: dict, trace: dict, template_keys: set | None) -> list[str]:
    constraints = parsed.get("constraints") or {}
    sources = trace.get("sources") or {}
    chips = parsed.get("chips") or []
    got = outcome_of(parsed)
    reasons = [] if got == exp["outcome"] else [f"outcome: expected {exp['outcome']}, got {got}"]
    listed = exp.get("fields") or exp.get("keep") or {}
    reasons += _check_fields(listed, constraints, sources, chips)
    if exp["outcome"] != "ASK":  # an ASK keeps what was said for the answer to continue; its keep list is a minimum
        reasons += _check_unlisted(listed, constraints, sources)
    reasons += _check_lines(exp.get("cant", []), exp.get("notes", []), parsed)
    reasons += _check_question(exp.get("question") if exp["outcome"] == "ASK" else None, parsed.get("question"),
                               int(trace.get("routing_calls") or 0))
    reasons += _check_templates(parsed, trace, template_keys)
    return reasons


def grade(case: dict, output: dict | None, template_keys: set | None = None) -> Grade:
    """Grade one parser output against one case. `template_keys`, when given, are the keys in api/copy.py."""
    if not isinstance(output, dict) or "error" in output or not isinstance(output.get("parsed"), dict):
        err = output.get("error") if isinstance(output, dict) else None
        return Grade(case["id"], False, None, [f"parser failed: {err or 'no parsed result'}"])
    parsed, trace = output["parsed"], output.get("trace")
    if not isinstance(trace, dict):
        return Grade(case["id"], False, outcome_of(parsed), ["no trace: sources, lookups and template keys are needed"])
    must_not = _check_must_not(case.get("must_not", []), output) + _check_spans(case["text"], parsed)
    attempts = [_grade_expectation(e, parsed, trace, template_keys)
                for e in [case["expect"], *case.get("alternatives", [])]]
    best = next((a for a in attempts if not a), attempts[0])
    reasons = best + must_not
    return Grade(case["id"], not reasons, outcome_of(parsed), reasons)
