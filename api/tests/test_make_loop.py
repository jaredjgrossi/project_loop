import json
from collections import Counter

import psycopg
import pytest

from api.generate import Candidate, GenerationResult
from api.geocoding import AmbiguousAddressError, GeocodeResult
from api.grid import GridEstimate
from api.routing import Route, RoutingUnavailableError
from api.scripts.make_loop import main, output_path_for, run
from api.shape import shape_metrics

RESULT = GeocodeResult(
    lat=40.741518, lon=-73.986485, label="11 MADISON AVENUE, New York, NY, USA", borough="Manhattan",
    postalcode="10010", housenumber="11", street="MADISON AVENUE", source="nycpad", source_id="1",
    match_type="fallback", confidence=0.8,
)
GRID = GridEstimate(angle_deg=28.7, strength=0.97)


def square_coords(lat=40.7415, lon=-73.9865, side=0.01):
    return [[lon, lat], [lon + side, lat], [lon + side, lat + side], [lon, lat + side], [lon, lat]]


def candidate(miles_actual=4.0, requested=4.0, label="rectangle 1:1, ++", score=80.0):
    coords = square_coords()
    route = Route(distance_m=miles_actual * 1609.344, time_s=3600, coordinates=coords)
    miss = (miles_actual - requested) / requested * 100
    return Candidate("rectangle", label, route, shape_metrics(coords), score, miss, abs(miss) <= 5)


def fake_generate(candidates, note=None, within=True):
    def generate_fn(lat, lon, miles, grid, route_fn, round_trip_fn, top_n=3, **kw):
        return GenerationResult(
            candidates=candidates[:top_n], within_tolerance=within, grid=grid, generated=20,
            rejected=Counter({"retraced": 2}), note=note,
        )

    return generate_fn


def go(tmp_path, generate_fn, miles=4.0, top=1, **kw):
    return run(
        "11 Madison Ave, Manhattan", miles, out=tmp_path / "loop.geojson", top=top,
        geocode_fn=lambda q: RESULT, grid_fn=lambda lat, lon: GRID, generate_fn=generate_fn, **kw,
    )


def test_writes_geojson_with_shape_and_reports_it(tmp_path, capsys):
    assert go(tmp_path, fake_generate([candidate()])) == 0
    text = capsys.readouterr().out
    assert "11 MADISON AVENUE" in text and "4.00 mi" in text
    assert "Turns:" in text and "per mile" in text and "retraced" in text
    assert "28.7" in text  # the grid angle used
    assert "geojson.io" in text
    fc = json.loads((tmp_path / "loop.geojson").read_text())
    props = fc["features"][0]["properties"]
    for key in ("turns", "turns_per_mile", "longest_straight_m", "retraced_pct", "score", "kind", "method", "rank"):
        assert key in props
    assert props["rank"] == 1


def test_top_n_writes_one_file_per_loop(tmp_path, capsys):
    cands = [candidate(label="first", score=90), candidate(label="second", score=80)]
    assert go(tmp_path, fake_generate(cands), top=2) == 0
    assert (tmp_path / "loop-rank1.geojson").exists() and (tmp_path / "loop-rank2.geojson").exists()
    text = capsys.readouterr().out
    assert "first" in text and "second" in text


def test_a_miss_is_stated_with_how_far_off(tmp_path, capsys):
    cand = candidate(miles_actual=3.0)
    note = "No loop came within 5% of 4 mi. The nearest is 25% short."
    assert go(tmp_path, fake_generate([cand], note=note, within=False)) == 0
    text = capsys.readouterr().out
    assert "25% short" in text
    assert "-25%" in text


def test_notes_such_as_a_weak_grid_are_shown(tmp_path, capsys):
    go(tmp_path, fake_generate([candidate()], note="The street grid here is weak (strength 0.20), so rectangles don't fit"))
    assert "street grid here is weak" in capsys.readouterr().out


def test_no_valid_loop_exits_nonzero_and_says_why(tmp_path, capsys):
    code = go(tmp_path, fake_generate([], note="No valid loop could be generated from this start point.", within=False))
    assert code == 5
    assert "No valid loop" in capsys.readouterr().err
    assert not (tmp_path / "loop.geojson").exists()


def test_geocode_failure_prints_the_reason_and_writes_nothing(tmp_path, capsys):
    def ambiguous(q):
        raise AmbiguousAddressError("11 Madison Avenue exists in Manhattan and Staten Island. Add a borough or zip code.", ["Manhattan", "Staten Island"])

    code = run("11 Madison Ave", 4.0, out=tmp_path / "l.geojson", geocode_fn=ambiguous,
               grid_fn=lambda *a: GRID, generate_fn=fake_generate([candidate()]))
    assert code == 2 and not (tmp_path / "l.geojson").exists()
    assert "Staten Island" in capsys.readouterr().err


def test_graphhopper_down_exits_nonzero(tmp_path, capsys):
    def down(*a, **k):
        raise RoutingUnavailableError("Could not reach GraphHopper. Try: docker compose up -d graphhopper")

    assert go(tmp_path, down) == 3
    assert "docker compose" in capsys.readouterr().err


def test_database_down_says_how_to_start_it(tmp_path, capsys):
    def no_db(lat, lon):
        raise psycopg.OperationalError("connection refused")

    code = run("11 Madison Ave, Manhattan", 4.0, out=tmp_path / "l.geojson", geocode_fn=lambda q: RESULT,
               grid_fn=no_db, generate_fn=fake_generate([candidate()]))
    assert code == 3
    assert "make up" in capsys.readouterr().err


@pytest.mark.parametrize("miles", [0, -1, 60])
def test_rejects_unreasonable_distances(miles, tmp_path):
    assert go(tmp_path, fake_generate([candidate()]), miles=miles) == 4


def test_default_output_path_is_under_out_and_named_from_the_inputs():
    path = output_path_for("11 Madison Ave, Manhattan", 4.0)
    assert path.parent.name == "out" and path.suffix == ".geojson"
    assert "11-madison-ave-manhattan" in path.name and "4mi" in path.name


def test_main_parses_arguments(tmp_path, monkeypatch):
    import api.scripts.make_loop as mod

    monkeypatch.setattr(mod, "geocode", lambda q: RESULT)
    monkeypatch.setattr(mod, "current_grid", lambda lat, lon: GRID)
    monkeypatch.setattr(mod, "generate_loops", fake_generate([candidate()]))
    out = tmp_path / "x.geojson"
    assert main(["11 Madison Ave, Manhattan", "4", "--out", str(out)]) == 0
    assert out.exists()


def test_parsed_request_is_shown_and_passed_to_the_generator(tmp_path, capsys):
    seen = {}

    def spy(lat, lon, miles, grid, route_fn, round_trip_fn, top_n=3, **kw):
        seen.update(kw)
        return fake_generate([candidate()])(lat, lon, miles, grid, route_fn, round_trip_fn, top_n)

    assert go(tmp_path, spy, shape="out_and_back", mode="training") == 0
    text = capsys.readouterr().out
    assert "Request:" in text and "Shape: out and back" in text and "Training preset" in text
    assert seen["shape"] == "out_and_back"
    assert seen["prefs"]["crowds"] == "avoid"
    assert any(z.id == "times_square" for z in seen["avoid"])  # default no-go zones always apply


def test_an_unknown_place_to_avoid_is_reported_not_silently_dropped(tmp_path, capsys):
    assert go(tmp_path, fake_generate([candidate()]), avoid=["Nowhere Plaza"]) == 0
    assert "'Nowhere Plaza' isn't in the no-go list, so it was NOT applied" in capsys.readouterr().out
