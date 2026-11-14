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


# --- routing through chosen waypoints (used by the rectangle generator) ------------

from api.routing import build_waypoint_request, request_route  # noqa: E402


def test_waypoint_request_lists_points_in_order_as_lon_lat():
    body = build_waypoint_request([(40.74, -73.98), (40.75, -73.97), (40.74, -73.98)])
    assert body["points"] == [[-73.98, 40.74], [-73.97, 40.75], [-73.98, 40.74]]
    assert body["profile"] == "foot"
    assert "algorithm" not in body  # a plain multi-point route, not a round trip
    assert body["points_encoded"] is False


def test_request_route_returns_the_routed_path():
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=load("graphhopper_round_trip.json"))

    route = request_route([START, (40.75, -73.97), START], client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert route.distance_m == pytest.approx(4881.76)
    assert len(json.loads(seen[0].content)["points"]) == 3


def test_request_route_needs_at_least_two_points():
    with pytest.raises(ValueError):
        request_route([START])


def test_request_route_reports_graphhopper_errors():
    def handler(request):
        return httpx.Response(400, json=load("graphhopper_error_point_not_found.json"))

    with pytest.raises(RoutingError, match="out of bounds"):
        request_route([START, (0, 0)], client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_custom_model_is_sent_only_when_given():
    model = {"priority": [{"if": "in_x", "multiply_by": "0"}], "areas": {"type": "FeatureCollection", "features": []}}
    assert "custom_model" not in build_waypoint_request([(40.7, -73.9), (40.71, -73.9)])
    assert build_waypoint_request([(40.7, -73.9), (40.71, -73.9)], custom_model=model)["custom_model"] == model
    assert build_round_trip_request(40.7, -73.9, 5000, custom_model=model)["custom_model"] == model


def test_requests_ask_for_elevation_and_routes_keep_it():
    assert build_waypoint_request([(40.7, -73.9), (40.71, -73.9)])["elevation"] is True
    assert build_round_trip_request(40.7, -73.9, 5000)["elevation"] is True
    with_ele = {"paths": [{"distance": 10, "time": 1000, "points": {"coordinates": [[-73.9, 40.7, 12.5], [-73.9, 40.71, 13.0]]}}]}
    r = parse_route(with_ele, seed=0)
    assert r.coordinates == [[-73.9, 40.7], [-73.9, 40.71]] and r.elevation == [12.5, 13.0]
    flat = {"paths": [{"distance": 10, "time": 1000, "points": {"coordinates": [[-73.9, 40.7], [-73.9, 40.71]]}}]}
    assert parse_route(flat, seed=0).elevation is None


# ---- turn instructions for the final routes (decision 054) ---------------------------------------------------------------


def line(n=11, step=0.0003):
    """A straight northbound line of n points, about 33 m apart."""
    return [[-73.98, 40.74 + i * step] for i in range(n)]


def gh_path(coords, instructions, distance=100.0):
    return {"paths": [{"distance": distance, "time": 1000, "points": {"coordinates": coords},
                       "instructions": [{"sign": s, "interval": [a, b], "street_name": "", "distance": 1, "text": ""}
                                        for s, a, b in instructions]}]}


class FakeClient:
    def __init__(self, payload, status=200):
        self.payload, self.status, self.posted = payload, status, []

    def post(self, url, json=None):
        self.posted.append((url, json))
        return httpx.Response(self.status, json=self.payload)


def test_requests_stay_without_instructions_so_the_candidates_geometry_is_unchanged():
    """With `instructions: true` GraphHopper keeps different vertices (same path, same length): every candidate would
    change, and the pinned top 3 with it. Only the final routes are asked again, with instructions."""
    assert build_waypoint_request([(40.7, -73.9), (40.71, -73.9)])["instructions"] is False
    assert build_round_trip_request(40.7, -73.9, 5000)["instructions"] is False


def test_a_routed_route_remembers_its_request_but_it_is_not_part_of_what_it_is():
    resp = {"paths": [{"distance": 10, "time": 1000, "points": {"coordinates": line(3)}}]}
    client = FakeClient(resp)
    route = request_route([(40.74, -73.98), (40.7406, -73.98)], client=client, base_url="http://gh.test")
    assert route.request == ("http://gh.test", client.posted[0][1])
    assert route.instructions is None
    assert route == parse_route(resp, seed=0)  # equality is on the line, not the request


def test_instructions_are_asked_for_again_on_the_same_request_and_placed_by_distance_along_the_route():
    from api.routing import with_instructions
    coords = line(11)
    first = FakeClient({"paths": [{"distance": 332.0, "time": 1000, "points": {"coordinates": coords}}]})
    route = request_route([(40.74, -73.98), (40.743, -73.98)], client=first, base_url="http://gh.test")
    # The second answer has another vertex (GraphHopper keeps the instruction points): same path, same length.
    extra = coords[:5] + [[-73.98, 40.7413]] + coords[5:]
    second = FakeClient(gh_path(extra, [(0, 0, 5), (2, 5, 8), (4, 11, 11)], distance=332.0))
    got = with_instructions(route, client=second)
    assert second.posted[0][1] == {**first.posted[0][1], "instructions": True}
    assert [s for s, _ in got.instructions] == [0, 2, 4]
    assert got.instructions[0][1] == 0 and got.instructions[2][1] == pytest.approx(333, abs=3)
    assert got.instructions[1][1] == pytest.approx(143.7, abs=1)  # the extra vertex, (40.7413 - 40.74) * 110,574 m along
    assert got.coordinates == route.coordinates  # the route's own line is untouched


def test_without_a_request_or_with_an_answer_that_doesnt_match_there_are_no_instructions():
    from api.routing import with_instructions
    route = parse_route({"paths": [{"distance": 10, "time": 1000, "points": {"coordinates": line(5)}}]}, seed=0)
    assert with_instructions(route).instructions is None  # a stored line was never routed
    routed = request_route([(40.74, -73.98), (40.7412, -73.98)], client=FakeClient(
        {"paths": [{"distance": 133.0, "time": 1000, "points": {"coordinates": line(5)}}]}), base_url="http://gh.test")
    other = FakeClient(gh_path(line(5, 0.0006), [(0, 0, 4), (4, 4, 4)]))  # a different path altogether
    assert with_instructions(routed, client=other).instructions is None
    assert with_instructions(routed, client=FakeClient({"message": "boom"}, status=500)).instructions is None
    down = FakeClient({})
    down.post = lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down"))
    assert with_instructions(routed, client=down).instructions is None
