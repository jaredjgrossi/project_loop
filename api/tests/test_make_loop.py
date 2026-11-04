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
    # main() wires the Postgres-backed closures and stretches; a unit test must not need the database (CI has none).
    monkeypatch.setattr(mod, "db_closures", lambda lat, lon, miles: [])
    monkeypatch.setattr(mod, "db_stretches", lambda coords, elevation, start=None: [])
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


def test_stretches_elevation_and_hour_go_into_the_geojson(tmp_path):
    stretch = {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
               "properties": {"feature": "stretch", "name": "East River Esplanade"}}
    assert go(tmp_path, fake_generate([candidate()]), stretch_fn=lambda coords, ele, start: [stretch], start_time="06:30") == 0
    fc = json.loads((tmp_path / "loop.geojson").read_text())
    props = fc["features"][0]["properties"]
    assert props["start_hour"] == 6
    assert props["elevation"]["status"] == "not_scored"  # the fake route has no elevation
    assert fc["features"][-1]["properties"]["name"] == "East River Esplanade"


def test_mile_and_turnaround_points_go_into_the_geojson(tmp_path):
    # The fake square's geometry is 2.4 mi (its 4 mi distance is only a label): miles 1-2, and no turnaround.
    assert go(tmp_path, fake_generate([candidate()])) == 0
    feats = json.loads((tmp_path / "loop.geojson").read_text())["features"]
    miles = [f["properties"] for f in feats if f["properties"].get("feature") == "mile"]
    assert [m["mile"] for m in miles] == [1, 2]
    assert all(m["status"] == "measured" for m in miles)
    assert not any(f["properties"].get("feature") == "turnaround" for f in feats)


def test_the_route_carries_a_summary_with_trust_labels(tmp_path):
    assert go(tmp_path, fake_generate([candidate()])) == 0
    summary = json.loads((tmp_path / "loop.geojson").read_text())["features"][0]["properties"]["summary"]
    assert summary["distance"]["status"] == "measured" and summary["distance"]["router_meters"] == round(4 * 1609.344)
    assert summary["waterfront_pct"]["status"] == "not_scored"  # no stretches here, so no shares: never zero
    assert summary["turnarounds"] == []


def test_the_pool_is_written_with_the_request_and_timing(tmp_path):
    pool_file = tmp_path / "pool.json"

    def with_pool(lat, lon, miles, grid, route_fn, round_trip_fn, top_n=3, **kw):
        r = fake_generate([candidate()])(lat, lon, miles, grid, route_fn, round_trip_fn, top_n)
        r.pool = [{"method": "rectangle", "status": "chosen", "metrics": {"turns_per_mile": 2.0}}]
        r.timing = {"first_candidate_s": 0.2, "winner_arrived_s": 0.4, "total_s": 1.0}
        return r

    assert go(tmp_path, with_pool, pool_out=pool_file) == 0
    data = json.loads(pool_file.read_text())
    assert data["pool"][0]["status"] == "chosen" and data["timing"]["first_candidate_s"] == 0.2
    assert data["request"]["distance_mi"] == 4.0


def test_lights_setting_reaches_the_router_and_the_context(tmp_path, monkeypatch):
    import api.scripts.make_loop as mod

    seen = {}
    real = mod.routers_for

    def spy_routers(zones, lights, closures=()):
        seen["router_lights"] = lights
        return real(zones, lights, closures)

    monkeypatch.setattr(mod, "routers_for", spy_routers)

    def factory(lights, grid, start):
        seen["context_lights"] = lights
        return lambda coords: None

    assert go(tmp_path, fake_generate([candidate()]), lights="waits", context_factory=factory) == 0
    assert seen["router_lights"] == "waits" and seen["context_lights"] == "waits"


def test_waiting_runners_get_the_signal_penalty_in_every_request():
    from api.scripts.make_loop import routers_for

    waits = routers_for([], "waits")
    zigzags = routers_for([], "zigzags")
    assert waits[0].keywords["custom_model"]["priority"][0]["if"] == "crossing == TRAFFIC_SIGNALS"
    assert waits[1].keywords["custom_model"]["priority"][0]["if"] == "crossing == TRAFFIC_SIGNALS"
    assert zigzags[0].keywords["custom_model"] is None


def test_known_closures_reach_the_router_and_the_rules(tmp_path, capsys, monkeypatch):
    import api.scripts.make_loop as mod
    from api.closures import Closure

    ring = [[[-73.99, 40.74], [-73.98, 40.74], [-73.98, 40.75], [-73.99, 40.74]]]
    reported = Closure(7, "report", "a closed stretch", "closed", "runner report #1", "listed", ring, in_router=True)
    seen = {}
    real = mod.routers_for

    def spy_routers(zones, lights, closures=()):
        seen["router"] = list(closures)
        return real(zones, lights, closures)

    def generate_fn(*a, **kw):
        seen["rules"] = list(kw["closures"])
        return fake_generate([candidate()])(*a, **kw)

    monkeypatch.setattr(mod, "routers_for", spy_routers)
    assert go(tmp_path, generate_fn, closures_fn=lambda lat, lon, miles: [reported]) == 0
    assert seen["router"] == seen["rules"] == [reported]
    assert "1 known closures within reach" in capsys.readouterr().out
    route_fn = real([], "zigzags", [reported])[0]
    assert route_fn.keywords["custom_model"]["priority"] == [{"if": "in_closure_7", "multiply_by": "0"}]


def test_identical_router_requests_in_one_generation_are_sent_once(monkeypatch):
    # Decision 018: 6-14% of a generation's requests repeat an earlier one exactly; GraphHopper answers them the same.
    import threading

    import api.scripts.make_loop as mod
    from api.routing import RoutingError

    sent = []
    lock = threading.Lock()

    def fake_route(points, custom_model=None):
        with lock:
            sent.append(tuple(points))
        if points[0] == (0.0, 0.0):
            raise RoutingError("no route")
        return Route(distance_m=1000.0, time_s=1, coordinates=[[p[1], p[0]] for p in points])

    monkeypatch.setattr(mod, "request_route", fake_route)
    route_fn, _, area_fn = mod.routers_for([], "zigzags")
    a = [(40.74, -73.98), (40.75, -73.98)]
    area = {"type": "Polygon", "coordinates": [[[-73.99, 40.73], [-73.97, 40.73], [-73.97, 40.76], [-73.99, 40.73]]]}
    threads = [threading.Thread(target=route_fn, args=(list(a),)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert route_fn(list(a)).distance_m == 1000.0
    area_fn(list(a), area)
    area_fn(list(a), area)
    assert len(sent) == 2  # once plain, once with the feature area
    for _ in range(2):
        with pytest.raises(RoutingError):
            route_fn([(0.0, 0.0), (40.75, -73.98)])
    assert len(sent) == 3  # a failure is reused too
    fresh, _, _ = mod.routers_for([], "zigzags")
    fresh(list(a))
    assert len(sent) == 4  # a new request's routers start empty


def test_shape_left_unset_is_shown_as_a_default_and_the_request_goes_into_the_geojson(tmp_path, capsys):
    assert go(tmp_path, fake_generate([candidate()])) == 0
    assert "Shape: any (default)" in capsys.readouterr().out
    request = json.loads((tmp_path / "loop.geojson").read_text())["features"][0]["properties"]["request"]
    assert {"key": "shape", "title": "Shape", "value": "any", "origin": "default"} in request
    assert go(tmp_path, fake_generate([candidate()]), shape="any") == 0
    assert "Shape: any (you said)" in capsys.readouterr().out


def test_a_start_time_without_a_day_gets_the_next_day_it_comes_round(tmp_path, capsys):
    from datetime import datetime

    seen = {}

    def factory(lights, grid, start):
        seen["start"] = start
        return None

    assert go(tmp_path, fake_generate([candidate()]), start_time="07:00", context_factory=factory,
              now_fn=lambda: datetime(2026, 11, 3, 21, 0)) == 0
    assert seen["start"] == datetime(2026, 11, 4, 7, 0)  # 9 pm now: tomorrow, a Wednesday
    assert "Day: Wednesday 2026-11-04 (default)" in capsys.readouterr().out
