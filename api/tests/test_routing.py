import json
from pathlib import Path

import httpx
import pytest

from api.routing import (
    Route,
    RoutingError,
    RoutingUnavailableError,
    build_round_trip_request,
    parse_route,
    request_round_trip,
    route_to_geojson,
)
from api.units import meters_to_miles

FIXTURES = Path(__file__).parent / "fixtures"
START = (40.741518, -73.986485)  # lat, lon: 11 Madison Ave, Manhattan


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_request_asks_for_a_foot_round_trip_in_meters_with_geojson_points():
    body = build_round_trip_request(*START, distance_m=6437.376, seed=3)
    assert body["profile"] == "foot"
    assert body["algorithm"] == "round_trip"
    assert body["points"] == [[-73.986485, 40.741518]]  # GraphHopper wants lon, lat
    assert body["round_trip.distance"] == pytest.approx(6437.376)
    assert body["round_trip.seed"] == 3
    assert body["points_encoded"] is False


def test_parse_real_graphhopper_response():
    route = parse_route(load("graphhopper_round_trip.json"), seed=0)
    assert route.distance_m == pytest.approx(4881.76)
    assert meters_to_miles(route.distance_m) == pytest.approx(3.03, abs=0.01)
    assert route.coordinates[0] == route.coordinates[-1]  # it is a loop
    assert all(len(c) == 2 for c in route.coordinates)  # lon, lat only


def test_parse_error_response_names_the_problem():
    # A real error body: a start point outside the map.
    with pytest.raises(RoutingError, match="out of bounds"):
        parse_route(load("graphhopper_error_point_not_found.json"), seed=0)


def test_geojson_has_route_and_start_with_the_miss_spelled_out():
    route = parse_route(load("graphhopper_round_trip.json"), seed=0)
    fc = route_to_geojson(route, start_lat=START[0], start_lon=START[1], start_label="11 MADISON AVENUE", requested_miles=4.0)
    assert fc["type"] == "FeatureCollection"
    line, start = fc["features"]
    assert line["geometry"]["type"] == "LineString"
    assert line["properties"]["requested_miles"] == 4.0
    assert line["properties"]["actual_miles"] == pytest.approx(3.03, abs=0.01)
    assert line["properties"]["percent_off"] == pytest.approx(-24.2, abs=0.2)
    assert start["geometry"] == {"type": "Point", "coordinates": [-73.986485, 40.741518]}
    assert start["properties"]["label"] == "11 MADISON AVENUE"


def test_request_round_trip_posts_to_graphhopper_and_returns_a_route():
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=load("graphhopper_round_trip.json"))

    route = request_round_trip(*START, distance_m=6437.376, seed=0, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert isinstance(route, Route)
    assert seen[0].method == "POST" and seen[0].url.path == "/route"
    assert json.loads(seen[0].content)["algorithm"] == "round_trip"


def test_graphhopper_400_surfaces_its_message():
    def handler(request):
        return httpx.Response(400, json=load("graphhopper_error_point_not_found.json"))

    with pytest.raises(RoutingError, match="out of bounds"):
        request_round_trip(0, 0, 6437, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_graphhopper_down_says_how_to_start_it():
    def boom(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(RoutingUnavailableError, match="docker compose up"):
        request_round_trip(*START, distance_m=6437, client=httpx.Client(transport=httpx.MockTransport(boom)))


def test_shape_fields_are_added_to_the_route_properties():
    route = parse_route(load("graphhopper_round_trip.json"), seed=0)
    shape = {"distance_miles": 3.03, "turns": 11, "turns_per_mile": 3.6}
    fc = route_to_geojson(route, START[0], START[1], "11 MADISON AVENUE", 4.0, shape)
    props = fc["features"][0]["properties"]
    assert props["turns"] == 11 and props["turns_per_mile"] == 3.6
    assert "distance_miles" not in props  # actual_miles already carries the routed distance
