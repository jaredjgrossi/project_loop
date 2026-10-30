import json
from pathlib import Path

import pytest

from api.geocoding import AmbiguousAddressError, GeocodeResult
from api.routing import Route, RoutingUnavailableError
from api.scripts.make_loop import main, output_path_for, run

RESULT = GeocodeResult(
    lat=40.741518, lon=-73.986485, label="11 MADISON AVENUE, New York, NY, USA", borough="Manhattan",
    postalcode="10010", housenumber="11", street="MADISON AVENUE", source="nycpad", source_id="1",
    match_type="fallback", confidence=0.8,
)


def fake_route(distance_m):
    def route_fn(lat, lon, requested_m, seed=0):
        return Route(distance_m=distance_m, time_s=3600, coordinates=[[lon, lat], [lon + 0.01, lat], [lon, lat]], seed=seed)

    return route_fn


def test_writes_geojson_and_reports_actual_distance(tmp_path, capsys):
    out = tmp_path / "loop.geojson"
    code = run("11 Madison Ave, Manhattan", 4.0, out=out, geocode_fn=lambda q: RESULT, route_fn=fake_route(6437.376))
    assert code == 0
    fc = json.loads(out.read_text())
    assert fc["features"][0]["properties"]["actual_miles"] == pytest.approx(4.0)
    text = capsys.readouterr().out
    assert "11 MADISON AVENUE" in text and "4.00 mi" in text and "geojson.io" in text


def test_says_so_when_the_distance_misses_the_target(tmp_path, capsys):
    run("11 Madison Ave, Manhattan", 4.0, out=tmp_path / "l.geojson", geocode_fn=lambda q: RESULT, route_fn=fake_route(4881.76))
    text = capsys.readouterr().out
    assert "3.03 mi" in text and "-24" in text
    assert "outside" in text  # outside the +/-5% target, stated plainly


def test_close_enough_gets_no_warning(tmp_path, capsys):
    run("11 Madison Ave, Manhattan", 4.0, out=tmp_path / "l.geojson", geocode_fn=lambda q: RESULT, route_fn=fake_route(6437.376 * 1.02))
    assert "outside" not in capsys.readouterr().out


def test_geocode_failure_prints_the_reason_and_writes_nothing(tmp_path, capsys):
    def ambiguous(q):
        raise AmbiguousAddressError("11 Madison Avenue exists in Manhattan and Staten Island. Add a borough or zip code.", ["Manhattan", "Staten Island"])

    out = tmp_path / "l.geojson"
    code = run("11 Madison Ave", 4.0, out=out, geocode_fn=ambiguous, route_fn=fake_route(1))
    assert code == 2 and not out.exists()
    assert "Staten Island" in capsys.readouterr().err


def test_routing_failure_exits_nonzero(tmp_path, capsys):
    def down(*a, **k):
        raise RoutingUnavailableError("Could not reach GraphHopper. Try: docker compose up -d graphhopper")

    code = run("11 Madison Ave, Manhattan", 4.0, out=tmp_path / "l.geojson", geocode_fn=lambda q: RESULT, route_fn=down)
    assert code == 3
    assert "docker compose" in capsys.readouterr().err


@pytest.mark.parametrize("miles", [0, -1, 60])
def test_rejects_unreasonable_distances(miles, tmp_path, capsys):
    assert run("11 Madison Ave, Manhattan", miles, out=tmp_path / "l.geojson", geocode_fn=lambda q: RESULT, route_fn=fake_route(1)) == 4


def test_default_output_path_is_under_out_and_named_from_the_inputs():
    path = output_path_for("11 Madison Ave, Manhattan", 4.0, seed=0)
    assert path.parent.name == "out" and path.suffix == ".geojson"
    assert "11-madison-ave-manhattan" in path.name and "4mi" in path.name


def test_main_parses_arguments(tmp_path, monkeypatch):
    import api.scripts.make_loop as mod

    monkeypatch.setattr(mod, "geocode", lambda q: RESULT)
    monkeypatch.setattr(mod, "request_round_trip", fake_route(6437.376))
    out = tmp_path / "x.geojson"
    assert main(["11 Madison Ave, Manhattan", "4", "--out", str(out)]) == 0
    assert out.exists()
