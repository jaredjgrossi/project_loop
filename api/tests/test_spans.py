"""Finding the runner's quoted words in their sentence (spans; UI decisions log 2026-11-08)."""

import pytest

from api.spans import find_span


def test_exact_words_give_their_positions_and_the_requests_own_characters():
    text = "Today, we're doing 8 miles on the water, ending at McCarren Park"
    s = find_span(text, "8 miles")
    assert s == {"text": "8 miles", "start": 19, "end": 26} and text[19:26] == "8 miles"


@pytest.mark.parametrize("text,quote,found", [
    ("Central park reservor, starting at 86th st", "central park reservor", "Central park reservor"),
    ("last week’s route", "last week's route", "last week’s route"),  # a curly apostrophe
    ("3–4 miles", "3-4 miles", "3–4 miles"),  # an en dash
    ("5  mi  loop", "5 mi", "5  mi"),  # doubled spaces
])
def test_matching_forgives_case_quotes_dashes_and_spaces(text, quote, found):
    s = find_span(text, quote)
    assert s["text"] == found and text[s["start"]:s["end"]] == found


@pytest.mark.parametrize("quote", ["9 miles", "", None, "   "])
def test_words_that_arent_there_give_no_span(quote):
    assert find_span("8 miles on the water", quote) is None


def test_no_text_no_span():
    assert find_span(None, "8 miles") is None and find_span("", "8 miles") is None


def test_a_second_chip_quoting_the_same_words_takes_the_next_occurrence():
    text = "5k tonight and a 5k sat"
    first = find_span(text, "5k")
    second = find_span(text, "5k", taken={(first["start"], first["end"])})
    assert (first["start"], second["start"]) == (0, 17)


def test_positions_count_code_points_with_an_emoji_before_the_words():
    text = "\U0001F3C3 6 mi flat"
    s = find_span(text, "flat")
    assert text[s["start"]:s["end"]] == "flat" and s["start"] == 7
