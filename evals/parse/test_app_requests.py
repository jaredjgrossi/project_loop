"""Live parses of the app's new request fields (decision 043), with Claude: uv run pytest evals/parse

Skips without the Claude key (.env) or Postgres. About 6 parses, about $0.002.
- The route type picked in the app beats the words.
- One way without an end asks where to end.
- A favorite the runner renamed is found by its name; "my usual" is the most run.
"""

import os

import psycopg
import pytest

from api.parse import parse
from api.tests.test_parse import CASES, CONTEXTS, FAVORITES
from evals.parse.fixtures import build_request
from etl.load import database_url


@pytest.fixture(scope="module", autouse=True)
def live():
    from api.env import load_env
    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("no ANTHROPIC_API_KEY in .env")
    try:
        psycopg.connect(database_url(), connect_timeout=3).close()
    except psycopg.Error as exc:
        pytest.skip(f"Postgres not reachable ({exc})")


def run(text: str, **fields) -> dict:
    req = build_request(CASES["P01"], CONTEXTS)
    req.update(text=text, **fields)
    out = parse(req)
    assert "error" not in out, out
    return out["parsed"]


def test_the_route_type_beats_the_words():
    p = run("3 mile loop", shape="out_and_back")
    assert p["constraints"]["shape"] == "out_and_back"
    assert next(c for c in p["chips"] if c["field"] == "shape")["text"] == "Out and back"


def test_one_way_without_an_end_asks_where_to_end():
    q = run("5k this morning", shape="one_way")["question"]
    assert q and (q["about"], q["text"]) == ("end", "Where do you want to end?")


def test_one_way_with_an_end_needs_no_question():
    p = run("4 miles to McCarren Park", shape="one_way")
    assert p["question"] is None and p["constraints"]["end_place"]["name"] == "McCarren Park"


def test_a_renamed_favorite_is_found_by_its_name():
    p = run("the Stuy loop", recent_routes=FAVORITES)
    assert p["constraints"]["reuse_route_id"] == "rt_b", p["question"]


def test_my_usual_is_the_most_run_favorite():
    p = run("my usual", recent_routes=FAVORITES)
    assert p["constraints"]["reuse_route_id"] == "rt_b"
