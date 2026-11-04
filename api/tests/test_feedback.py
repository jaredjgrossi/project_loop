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


def test_crowded_reports_name_the_stretch_band_and_hour():
    from datetime import datetime

    from api.feedback import crowd_report_rows

    fb = RouteFeedback(route_id="r1", ran_it=True, rating=3, ran_at=datetime(2026, 11, 3, 18, 5), issues=["crowded"],
                       stretch_issues=[{"stretch": 1, "issue": "crowded"}, {"stretch": 0, "issue": "bad_surface"}])
    stretches = [{"properties": {"stretch": 0, "name": "East 34th Street", "crowd": {"value": "low", "band": "x"}}},
                 {"properties": {"stretch": 1, "name": "2nd Avenue",
                                 "crowd": {"value": "medium", "status": "estimate", "band": "weekday 4-7pm (a DOT count window)"}}}]
    rows = crowd_report_rows(fb, stretches, start=datetime(2026, 11, 3, 18, 0))
    assert rows == [
        {"route_id": "r1", "stretch": None, "stretch_name": None, "level_shown": None, "band": None, "hour": 18,
         "weekday": 1},
        {"route_id": "r1", "stretch": 1, "stretch_name": "2nd Avenue", "level_shown": "medium",
         "band": "weekday 4-7pm (a DOT count window)", "hour": 18, "weekday": 1},
    ]


def test_no_crowded_issue_means_no_reports_and_unknown_time_is_kept_unknown():
    from api.feedback import crowd_report_rows

    assert crowd_report_rows(RouteFeedback(route_id="r1", ran_it=False), [], start=None) == []
    rows = crowd_report_rows(RouteFeedback(route_id="r1", ran_it=False, issues=["crowded"]), [], start=None)
    assert rows[0]["hour"] is None and rows[0]["weekday"] is None


def test_closed_or_blocked_reports_keep_the_stretch_geometry_and_whole_route_reports_have_none():
    import json

    from api.feedback import closure_report_rows

    geom = {"type": "LineString", "coordinates": [[-73.97, 40.74], [-73.97, 40.75]]}
    fb = RouteFeedback(route_id="r1", ran_it=True, rating=2, issues=["closed_or_blocked"], note="fenced off",
                       stretch_issues=[{"stretch": 1, "issue": "closed_or_blocked"}, {"stretch": 0, "issue": "crowded"}])
    stretches = [{"properties": {"stretch": 0, "name": "East 34th Street"}, "geometry": geom},
                 {"properties": {"stretch": 1, "name": "East River Esplanade"}, "geometry": geom}]
    whole, stretch = closure_report_rows(fb, stretches)
    assert whole["stretch"] is None and whole["geom"] is None and whole["note"] == "fenced off"
    assert stretch["stretch"] == 1 and stretch["stretch_name"] == "East River Esplanade"
    assert json.loads(stretch["geom"]) == geom
    assert closure_report_rows(RouteFeedback(route_id="r1", ran_it=False, issues=["crowded"]), stretches) == []


def test_a_stretch_report_takes_the_stretch_not_a_piece_inside_it():
    import json

    from api.feedback import closure_report_rows

    whole_line = {"type": "LineString", "coordinates": [[-73.97, 40.74], [-73.97, 40.75]]}
    piece_line = {"type": "LineString", "coordinates": [[-73.97, 40.745], [-73.97, 40.75]]}
    fb = RouteFeedback(route_id="r1", ran_it=True, rating=2,
                       stretch_issues=[{"stretch": 0, "issue": "closed_or_blocked"}])
    features = [{"properties": {"feature": "stretch", "stretch": 0, "name": "East River Esplanade"},
                 "geometry": whole_line},
                {"properties": {"feature": "piece", "piece": 0, "stretch": 0, "kind": "path",
                                "stretch_name": "East River Esplanade"}, "geometry": piece_line}]
    (row,) = closure_report_rows(fb, features)
    assert row["stretch_name"] == "East River Esplanade" and json.loads(row["geom"]) == whole_line
