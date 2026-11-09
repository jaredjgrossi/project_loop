"""The command-line client's stream reader and printout (step 5)."""

from api.scripts.ask import describe, sse_events


def test_sse_lines_become_events():
    lines = ["event: parsed", 'data: {"event": "parsed", "n": 1}', "", ": ping", "", "event: done",
             'data: {"event": "done"}', ""]
    assert list(sse_events(lines)) == [("parsed", {"event": "parsed", "n": 1}), ("done", {"event": "done"})]


def test_a_question_prints_its_options():
    ev = {"event": "parsed", "chips": [{"text": "5 mi", "source": "said"}], "cant": [], "notes": [],
          "question": {"from": "parser", "about": "distance", "text": "How far?", "allow_text": True,
                       "options": [{"id": "a", "text": "3 mi"}]}}
    text = describe(ev)
    assert "5 mi (said)" in text and "How far?" in text and "a) 3 mi" in text


def test_routes_print_with_distance_and_pool():
    ev = {"event": "final", "route_id": "r_1", "elapsed_s": 2.5, "pool_size": 14, "notes": [],
          "routes": [{"rank": 1, "label": "East River loop", "distance": {"value": 3.02}}]}
    assert describe(ev) == "r_1 at 2.50 s engine time: #1 East River loop 3.02 mi; best of 14"


def test_candidates_print_their_ids_and_point_counts():
    ev = {"event": "candidates", "candidates": [{"id": "r_1.4", "kind": "loop", "points": [[0, 0]] * 31}]}
    assert describe(ev) == "r_1.4 loop (31 points)"
