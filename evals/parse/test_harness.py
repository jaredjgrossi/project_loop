"""Tests for the parse-eval harness itself: the fixtures match the evals doc, the stub fails everything, a parser
that returns exactly what each case expects passes everything, and each grading rule catches its own mistake.

No services and no Claude calls: these run with the unit tests (decision 019).
"""

import copy
from collections import Counter

import pytest

from evals.parse import run as runner
from evals.parse.fixtures import build_request, load_cases, load_contexts
from evals.parse.grader import (ABOUTS, FIELD_CHIP, FROMS, GAPS, KNOWN_FIELDS, MUST_NOT_CHECKS, NEEDS, NOTE_KEYS,
                                OUTCOMES, SOURCES, grade)

CASES = load_cases()
BY_ID = {c["id"]: c for c in CASES}


# ---- a parser that returns what each case expects ---------------------------------------------------------------

def _actual(name, value):
    if name in ("start_place", "end_place"):
        kind = next(k for k in ("place", "address", "saved") if k in value)
        ref = {"kind": kind, "id": value[kind]} if kind == "saved" else {"kind": kind, "name": value[kind]}
        return ref | ({"borough": value["borough"]} if "borough" in value else {})
    if name == "via_places":
        return [_actual("start_place", v) for v in value]
    return copy.deepcopy(value)


def oracle(case: dict, exp: dict | None = None) -> dict:
    exp = exp or case["expect"]
    listed = exp.get("fields") or exp.get("keep") or {}
    constraints, sources, chips, texts = {}, {}, [], []

    def say(text, key):
        texts.append({"text": text, "key": key})
        return text

    for name, spec in listed.items():
        if name == "planned":
            inner = {}
            for k, s in spec["value"].items():
                inner[k] = _actual(k, s["value"])
                if "source" in s:
                    sources[f"planned.{k}"] = s["source"]
            constraints["planned"] = inner
            continue
        constraints[name] = _actual(name, spec["value"])
        if "source" in spec:
            sources[name] = spec["source"]
    for name, spec in listed.items():
        chip = FIELD_CHIP.get(name)
        if chip is None or (name == "tolerance_pct" and "distance_mi" in listed):
            continue
        if name == "start_date" and "start_time" in listed:
            continue
        chips.append({"id": f"c_{name}", "field": chip, "text": say(f"chip {name}", f"chip.{chip}"),
                      "source": spec.get("source", "said"), "editable": True})
    question = None
    if exp["outcome"] == "ASK":
        want = exp["question"]
        opts = want.get("options") or [f"option {i}" for i in range(want.get("min_options", 0))]
        question = {"id": "q_1", "about": want["about"], "from": want["from"],
                    "text": say("question", f"question.{want['about']}"),
                    "options": [{"id": f"o{i}", "text": say(o, "option")} for i, o in enumerate(opts)],
                    "allow_text": want.get("allow_text", False)}
    cant = [{"id": f"k_{i}", "gap": g, "text": say(f"cant {g}", f"cant.{g}")} for i, g in enumerate(exp.get("cant", []))]
    notes = [{"id": f"n_{i}", "key": k, "text": say(f"note {k}", f"note.{k}"), "trust": "listed"}
             for i, k in enumerate(exp.get("notes", []))]
    return {"parsed": {"event": "parsed", "v": 1, "parse_id": "p_test", "chips": chips, "question": question,
                       "cant": cant, "notes": notes, "constraints": constraints},
            "trace": {"sources": sources, "lookups": [], "routing_calls": 0, "texts": texts}}


def reasons(case_id: str, output: dict) -> list[str]:
    return grade(BY_ID[case_id], output).reasons


# ---- the fixtures ----------------------------------------------------------------------------------------------

def test_fifty_cases_with_the_docs_coverage():
    assert len(CASES) == 50 and len(BY_ID) == 50
    assert [c["seq"] for c in CASES] == list(range(1, 51))
    assert Counter(c["category"] for c in CASES) == {"A": 4, "B": 4, "C": 3, "D": 11, "E": 4, "F": 7, "G": 6,
                                                     "H": 5, "I": 3, "J": 3}
    assert sum(c["expect"]["outcome"] == "ASK" for c in CASES) == 13  # P16, P46 parse since R19
    assert sum(c["origin"] in ("real", "endorsed") for c in CASES) == 16


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_case_fixture_is_well_formed(case):
    assert case["context"] in load_contexts()
    assert set(case["needs"]) <= set(NEEDS)
    assert set(case["tags"]) <= {"lookup", "engine"}
    for exp in [case["expect"], *case.get("alternatives", [])]:
        assert exp["outcome"] in OUTCOMES
        assert ("question" in exp) == (exp["outcome"] == "ASK")
        assert not ("fields" in exp and "keep" in exp)
        for name, spec in (exp.get("fields") or exp.get("keep") or {}).items():
            assert name in KNOWN_FIELDS
            assert spec.get("source", "said") in SOURCES
        if "question" in exp:
            assert exp["question"]["about"] in ABOUTS and exp["question"]["from"] in FROMS
        assert set(exp.get("cant", [])) <= set(GAPS)
        assert set(exp.get("notes", [])) <= set(NOTE_KEYS)
        assert (exp["outcome"] == "PARSE+CANT") <= bool(exp.get("cant"))
    for rule in case["must_not"]:
        assert rule["check"] in MUST_NOT_CHECKS and rule["why"]


def test_request_follows_the_contract_and_drops_human_labels():
    req = build_request(BY_ID["H01"], load_contexts())
    assert set(req) == {"v", "text", "client", "profile", "recent_routes"}
    assert req["client"]["now"] == "2026-11-03T06:40:00-05:00"
    assert "label" not in req["client"]["location"]
    assert "stand_in" not in req["profile"]["saved_places"][0]
    assert [r["id"] for r in req["recent_routes"]] == ["rt_a", "rt_c", "rt_b"]
    new = build_request(BY_ID["R06"], load_contexts())
    assert new["recent_routes"] == [] and new["profile"]["usual_distance_mi"] is None


# ---- the harness against the stub and the oracle ----------------------------------------------------------------

def test_stub_fails_every_case():
    rows = runner.run(runner.load_parser("evals.parse.stub:parse"))
    assert len(rows) == 50 and not any(g.passed for _, g, _ in rows)
    assert "passed 0/50" in runner.table(rows)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_oracle_passes(case):
    assert grade(case, oracle(case)).reasons == []


def test_alternative_passes_when_the_main_expectation_does_not():
    case = BY_ID["P17"]
    assert grade(case, oracle(case, case["alternatives"][0])).passed


# ---- each rule catches its own mistake --------------------------------------------------------------------------

def test_outcome_mismatch_fails():
    out = oracle(BY_ID["P01"])
    out["parsed"]["question"] = {"about": "distance", "from": "parser", "text": "x", "options": []}
    assert any(r.startswith("outcome") for r in reasons("P01", out))


def test_distance_off_by_more_than_005_fails_and_within_passes():
    out = oracle(BY_ID["P38"])
    out["parsed"]["constraints"]["distance_mi"] = 3.15
    assert reasons("P38", out) == []
    out["parsed"]["constraints"]["distance_mi"] = 3.2
    assert any("distance_mi" in r for r in reasons("P38", out))


def test_wrong_source_fails_on_trace_and_chip():
    out = oracle(BY_ID["P01"])
    out["trace"]["sources"]["distance_mi"] = "default"
    out["parsed"]["chips"][0]["source"] = "default"
    rs = reasons("P01", out)
    assert any("source expected usual" in r for r in rs) and any("chip source" in r for r in rs)


def test_unlisted_said_field_fails_but_code_default_passes():
    out = oracle(BY_ID["R08"])
    out["parsed"]["constraints"]["start_time"] = "06:40"
    out["trace"]["sources"]["start_time"] = "default"
    assert reasons("R08", out) == []
    out["parsed"]["constraints"]["lights"] = "waits"
    out["trace"]["sources"]["lights"] = "said"
    assert any("unlisted field set: lights" in r for r in reasons("R08", out))


def test_missing_cant_gap_and_note_key_fail():
    out = oracle(BY_ID["P14"])
    out["parsed"]["cant"] = []
    assert "missing can't-do line G9" in reasons("P14", out)
    out = oracle(BY_ID["P35"])
    out["parsed"]["notes"] = []
    assert "missing note fountains_seasonal" in reasons("P35", out)


def test_question_checks():
    out = oracle(BY_ID["R06"])
    out["parsed"]["question"]["options"][2]["text"] = "8 mi"
    assert any("question options" in r for r in reasons("R06", out))
    out = oracle(BY_ID["R06"])
    out["parsed"]["question"]["options"][0]["text"] = "3 mi (your usual is unknown)"  # rewording is fine
    out["trace"]["texts"].append({"text": "3 mi (your usual is unknown)", "key": "option"})
    assert reasons("R06", out) == []
    out = oracle(BY_ID["R06"])
    out["trace"]["routing_calls"] = 1
    assert any("routing call" in r for r in reasons("R06", out))
    out = oracle(BY_ID["P20"])
    out["parsed"]["question"]["options"] = []
    assert any("at least 1" in r for r in reasons("P20", out))


def test_must_nots():
    out = oracle(BY_ID["P09"])
    out["parsed"]["constraints"]["mode"] = "training"
    out["trace"]["sources"]["mode"] = "said"
    assert any("Must not: set mode=training" in r for r in reasons("P09", out))
    out = oracle(BY_ID["P04"])
    out["trace"]["lookups"] = [{"name": "Kip Bay", "role": "start"}]
    assert any("kip bay" in r for r in reasons("P04", out))
    out = oracle(BY_ID["R07"])
    out["parsed"]["constraints"]["avoid_places"].append({"name": "42nd St", "how": "area"})
    assert any("block crossing" in r for r in reasons("R07", out))
    out = oracle(BY_ID["P23"])
    out["parsed"]["constraints"]["avoid_places"].append({"name": "1st Ave", "how": "along"})
    assert any("all of 1st Ave" in r for r in reasons("P23", out))
    out = oracle(BY_ID["P27"])
    out["parsed"]["constraints"]["avoid_places"] = [{"name": "East River Greenway", "how": "along"}]
    assert any("East River path" in r for r in reasons("P27", out))
    out = oracle(BY_ID["P24"])
    out["parsed"]["cant"] = [{"id": "k", "gap": "G10", "text": "cant G10"}]
    out["trace"]["texts"].append({"text": "cant G10", "key": "cant.G10"})
    assert any("can't-do line" in r for r in reasons("P24", out))
    out = oracle(BY_ID["R05"])
    out["parsed"]["reply"] = "Try the waterfront!"
    assert any("what do you suggest" in r for r in reasons("R05", out))
    out = oracle(BY_ID["H01"])
    out["parsed"]["constraints"]["reuse_route_id"] = None
    assert any("today" in r for r in reasons("H01", out))


def test_health_and_safety_words_are_caught():
    out = oracle(BY_ID["P32"])
    out["parsed"]["notes"] = [{"id": "n", "key": "x", "text": "Easy on the knees", "trust": "listed"}]
    out["trace"]["texts"].append({"text": "Easy on the knees", "key": "note.x"})
    assert any("knee" in r for r in reasons("P32", out))
    out = oracle(BY_ID["P14"])
    out["parsed"]["cant"][0]["text"] = "Can't plan around lighting and safety yet"  # the can't-do line may say it
    out["trace"]["texts"].append({"text": "Can't plan around lighting and safety yet", "key": "cant.G9"})
    assert reasons("P14", out) == []
    out["parsed"]["chips"][0]["text"] = "Well-lit streets"
    out["trace"]["texts"].append({"text": "Well-lit streets", "key": "chip.time"})
    assert any("well lit" in r for r in reasons("P14", out))


def test_text_without_a_template_key_fails():
    out = oracle(BY_ID["P05"])
    out["parsed"]["chips"][0]["text"] = "Three miles, nice!"
    assert any("not from a template" in r for r in reasons("P05", out))
    case = BY_ID["P05"]
    assert grade(case, oracle(case), template_keys={"chip.distance"}).reasons == ["unknown template key "
                                                                                  "'chip.shape' for 'chip shape'"]


def test_places_and_planned_compare_by_name_and_kind():
    out = oracle(BY_ID["P18"])
    out["parsed"]["constraints"]["start_place"] = {"kind": "place", "name": "penn station", "lat": 40.75}
    assert reasons("P18", out) == []
    out["parsed"]["constraints"]["start_place"] = {"kind": "saved", "id": "Penn Station"}
    assert any("start_place" in r for r in reasons("P18", out))
    out = oracle(BY_ID["P16"])
    out["parsed"]["constraints"]["start_place"]["borough"] = "Brooklyn"
    assert any("start_place" in r for r in reasons("P16", out))
    out = oracle(BY_ID["P45"])
    out["parsed"]["constraints"]["planned"]["start_date"] = "2026-11-08"
    assert any("planned.start_date" in r for r in reasons("P45", out))


def test_parser_error_and_missing_trace_fail():
    assert not grade(BY_ID["P01"], {"error": "boom"}).passed
    out = oracle(BY_ID["P01"])
    del out["trace"]
    assert any("no trace" in r for r in reasons("P01", out))
