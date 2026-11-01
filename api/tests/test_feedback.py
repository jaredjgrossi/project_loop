import pytest
from pydantic import ValidationError

from api.feedback import RouteFeedback


def test_ran_it_with_a_rating_and_issues():
    f = RouteFeedback(route_id="r-123", ran_it=True, rating=4, issues=["crowded"],
                      stretch_issues=[{"stretch": 2, "issue": "closed_or_blocked"}], note="Esplanade fenced at 20th")
    assert f.rating == 4 and f.stretch_issues[0].stretch == 2


def test_a_rating_needs_the_run():
    with pytest.raises(ValidationError, match="rating"):
        RouteFeedback(route_id="r-1", ran_it=False, rating=5)


def test_ran_it_needs_a_rating():
    with pytest.raises(ValidationError, match="rating"):
        RouteFeedback(route_id="r-1", ran_it=True)


@pytest.mark.parametrize("rating", [0, 6])
def test_rating_is_one_to_five(rating):
    with pytest.raises(ValidationError):
        RouteFeedback(route_id="r-1", ran_it=True, rating=rating)


def test_unknown_issues_and_fields_are_rejected():
    with pytest.raises(ValidationError):
        RouteFeedback(route_id="r-1", ran_it=True, rating=3, issues=["too_pretty"])
    with pytest.raises(ValidationError):
        RouteFeedback(route_id="r-1", ran_it=True, rating=3, gps_track=[[0, 0]])


def test_notes_are_capped():
    with pytest.raises(ValidationError):
        RouteFeedback(route_id="r-1", ran_it=True, rating=3, note="x" * 501)


def test_skipped_without_running_is_fine():
    assert RouteFeedback(route_id="r-1", ran_it=False, issues=["too_long"]).rating is None
