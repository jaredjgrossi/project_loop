"""A place outside the five boroughs is out_of_area wherever the words come from (decision 057): a named place with a
city outside NYC, an address, a via, or a typed answer. Never "What's the address?" for a place that is not in NYC."""

from types import SimpleNamespace

import pytest

from api.parse import Context, build, claude_area_check, resume
from api.tests.test_parse import CASES, CONTEXTS, FakePlaces, ext, mi, place
from evals.parse.fixtures import build_request

OUTSIDE_WORDS = ("naples", "tampa", "hoboken", "florida", " fl")


class Area:
    """The area check with a few cities in it, counting what it was asked."""

    def __init__(self):
        self.asked = []

    def __call__(self, text):
        self.asked.append(text)
        return any(w in text.casefold() for w in OUTSIDE_WORDS)


def ctx_for(case_id="P19"):
    return Context.from_request(build_request(CASES[case_id], CONTEXTS))


def built(extraction, area, answers=None):
    return build(extraction, ctx_for(), FakePlaces(), answers=answers, area=area)


def question_text(out):
    return out["parsed"]["question"]["text"]


@pytest.mark.parametrize("name", ["Ritz Carlton Naples", "Starbucks Tampa", "the pier in Hoboken"])
def test_a_named_place_with_a_city_outside_nyc_is_out_of_area_not_a_question(name):
    out = built(ext(distance=mi(3), start=place("place", name)), Area())
    assert out["error"] == "out_of_area" and out["place"] == name and out["covers"] == "New York City"
    assert "parsed" not in out


def test_an_address_in_another_city_is_out_of_area_not_couldnt_find():
    out = built(ext(distance=mi(3), start=place("address", "200 Fifth Ave, Naples, FL")), Area())
    assert out["error"] == "out_of_area" and out["place"] == "200 Fifth Ave, Naples, FL"


def test_the_end_and_a_via_are_checked_the_same_way():
    end = built(ext(distance=mi(3), start=place("place", "Central Park"), end=place("place", "Tampa Bay Brewing")), Area())
    assert end["error"] == "out_of_area" and end["place"] == "Tampa Bay Brewing"
    via = ext(distance=mi(3), start=place("place", "Central Park"),
              via=[{"name": "Naples Pier", "kind": "place", "word": "past"}])
    assert built(via, Area())["error"] == "out_of_area"


def test_a_place_the_flag_names_is_out_of_area_even_when_the_same_name_exists_in_nyc():
    e = ext(distance=mi(3), start=place("place", "Central Park Tampa", outside_nyc=True))
    out = built(e, None)  # no area check at all: the extraction's own flag is enough
    assert out["error"] == "out_of_area"


def test_a_place_that_is_not_in_nyc_but_is_not_outside_either_is_still_asked_about():
    out = built(ext(distance=mi(3), start=place("place", "Joe's Corner Cafe")), Area())
    assert out["parsed"]["question"]["text"] == "Couldn't find Joe's Corner Cafe. What's the address?"


def test_without_an_area_check_nothing_changes():
    out = built(ext(distance=mi(3), start=place("place", "Ritz Carlton Naples")), None)
    assert question_text(out) == "Couldn't find Ritz Carlton Naples. What's the address?"


def test_a_place_that_is_found_is_not_sent_to_the_area_check():
    area = Area()
    out = built(ext(distance=mi(3), start=place("place", "Central Park")), area)
    assert "error" not in out and area.asked == []


def test_the_area_check_gets_the_words_only_and_each_text_once():
    area = Area()
    built(ext(distance=mi(3), start=place("place", "Joe's Corner Cafe")), area)
    assert area.asked == ["Joe's Corner Cafe"]


# ---- typed answers --------------------------------------------------------------------------------------------


def asked_where():
    e = ext(distance=mi(3), start=place("place", "Joe's Corner Cafe"))
    out = built(e, Area())
    assert out["parsed"]["question"]["allow_text"]
    return e, out


@pytest.mark.parametrize("typed", ["123 Main Street, Naples, FL", "Starbucks Tampa", "Hoboken"])
def test_a_typed_answer_outside_nyc_is_out_of_area_not_couldnt_find(typed):
    e, out = asked_where()
    after = resume(e, ctx_for(), FakePlaces(), {**out["trace"]["answers"], "text:start": typed}, area=Area())
    assert after["error"] == "out_of_area" and after["place"] == typed


def test_a_typed_answer_is_checked_even_when_a_place_by_that_name_exists_in_nyc():
    e, out = asked_where()
    typed = "Central Park Tampa"  # FakePlaces would find "Central Park" for a lookup of the first words only
    after = resume(e, ctx_for(), FakePlaces(), {**out["trace"]["answers"], "text:start": typed}, area=Area())
    assert after["error"] == "out_of_area"


def test_a_typed_answer_in_nyc_goes_on_to_build():
    e, out = asked_where()
    after = resume(e, ctx_for(), FakePlaces(), {**out["trace"]["answers"], "text:start": "Central Park"}, area=Area())
    assert after["parsed"]["constraints"]["start_place"]["name"] == "Central Park"


def test_a_typed_via_answer_outside_nyc_is_out_of_area():
    e = ext(distance=mi(3), start=place("place", "Central Park"),
            via=[{"name": "Joe's Corner Cafe", "kind": "place", "word": "past"}])
    out = built(e, Area())
    after = resume(e, ctx_for(), FakePlaces(), {**out["trace"]["answers"], "text:via.1": "Naples Pier"}, area=Area())
    assert after["error"] == "out_of_area" and after["place"] == "Naples Pier"


# ---- the Claude area check ------------------------------------------------------------------------------------


def client_answering(outside, calls=None, raises=None):
    block = SimpleNamespace(type="tool_use", name="record_area", input={"outside_nyc": outside})
    usage = SimpleNamespace(input_tokens=300, output_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=0)

    class Client:
        class messages:  # noqa: N801
            @staticmethod
            def create(**kw):
                if calls is not None:
                    calls.append(kw)
                if raises:
                    raise raises
                return SimpleNamespace(content=[block], usage=usage, stop_reason="tool_use", _request_id="req_1")

    return Client


def test_the_claude_check_says_what_the_tool_call_says_and_logs_the_call():
    logged, calls = [], []
    check = claude_area_check(client_answering(True, calls), log=logged.append)
    assert check("Starbucks Tampa") is True
    assert logged[0]["purpose"] == "area" and logged[0]["request_text"] == "Starbucks Tampa"
    assert logged[0]["cost_usd"] > 0 and logged[0]["prompt_version"] == "area_v1"
    assert calls[0]["messages"][0]["content"] == "Starbucks Tampa"  # the words only: no location, no context
    assert claude_area_check(client_answering(False))("Central Park") is False


def test_a_failed_check_never_blocks_the_runner():
    import anthropic
    err = anthropic.APIConnectionError(request=SimpleNamespace())
    logged = []
    assert claude_area_check(client_answering(True, raises=err), log=logged.append)("Starbucks Tampa") is False
    assert "error" in logged[0]
    none = SimpleNamespace(content=[], usage=SimpleNamespace(input_tokens=1, output_tokens=1), stop_reason="end_turn")
    no_call = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: none))
    assert claude_area_check(no_call, log=lambda s: None)("Starbucks Tampa") is False
