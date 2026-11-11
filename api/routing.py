"""GraphHopper client: ask for a round-trip foot route and shape it as GeoJSON."""

import os
from dataclasses import dataclass

import httpx

from api.units import meters_to_miles, percent_off

DEFAULT_GRAPHHOPPER_URL = "http://localhost:8989"


class RoutingError(Exception):
    """GraphHopper rejected the request (e.g. start point outside the map)."""


class RoutingUnavailableError(RoutingError):
    """GraphHopper could not be reached."""


@dataclass(frozen=True)
class Route:
    distance_m: float
    time_s: float
    coordinates: list[list[float]]  # [lon, lat]
    seed: int = 0  # round-trip seed; 0 for routes through chosen waypoints
    elevation: list[float] | None = None  # meters, one per coordinate, when GraphHopper has elevation (decision 014)


def graphhopper_url() -> str:
    return os.environ.get("GRAPHHOPPER_URL", DEFAULT_GRAPHHOPPER_URL)


def _with_model(body: dict, custom_model: dict | None) -> dict:
    # Merged by GraphHopper into the profile's model (loop_foot.json); works because the profile has no CH (decision 009).
    return {**body, "custom_model": custom_model} if custom_model else body


def build_round_trip_request(
    lat: float, lon: float, distance_m: float, seed: int = 0, custom_model: dict | None = None
) -> dict:
    return _with_model({
        "points": [[lon, lat]],  # GraphHopper takes lon, lat
        "profile": "foot",
        "algorithm": "round_trip",
        "round_trip.distance": distance_m,
        "round_trip.seed": seed,
        "points_encoded": False,  # plain GeoJSON coordinates instead of an encoded polyline
        "instructions": False,
        "elevation": True,
    }, custom_model)


def build_waypoint_request(points: list[tuple[float, float]], custom_model: dict | None = None) -> dict:
    """Route through (lat, lon) points in order."""
    return _with_model({
        "points": [[lon, lat] for lat, lon in points],
        "profile": "foot",
        "points_encoded": False,
        "instructions": False,
        "elevation": True,
    }, custom_model)


def parse_route(response: dict, seed: int) -> Route:
    paths = response.get("paths")
    if not paths:
        raise RoutingError(response.get("message") or "GraphHopper returned no route")
    path = paths[0]
    coords = path["points"]["coordinates"]
    return Route(
        distance_m=path["distance"],
        time_s=path["time"] / 1000,
        coordinates=[c[:2] for c in coords],
        seed=seed,
        elevation=[c[2] for c in coords] if coords and all(len(c) > 2 for c in coords) else None,
    )


def _post_route(body: dict, seed: int, client: httpx.Client | None, base_url: str | None) -> Route:
    owns_client = client is None
    client = client or httpx.Client(timeout=60)
    try:
        resp = client.post(f"{base_url or graphhopper_url()}/route", json=body)
    except httpx.HTTPError as exc:
        raise RoutingUnavailableError(
            f"Could not reach GraphHopper ({exc}). Is it running? Try: docker compose up -d graphhopper"
        ) from exc
    finally:
        if owns_client:
            client.close()
    try:
        payload = resp.json()
    except ValueError:
        raise RoutingError(f"GraphHopper returned HTTP {resp.status_code} with a non-JSON body") from None
    return parse_route(payload, seed)


def request_round_trip(
    lat: float,
    lon: float,
    distance_m: float,
    seed: int = 0,
    client: httpx.Client | None = None,
    base_url: str | None = None,
    custom_model: dict | None = None,
) -> Route:
    return _post_route(build_round_trip_request(lat, lon, distance_m, seed, custom_model), seed, client, base_url)


def request_route(
    points: list[tuple[float, float]],
    client: httpx.Client | None = None,
    base_url: str | None = None,
    custom_model: dict | None = None,
) -> Route:
    """A foot route through (lat, lon) points in order."""
    if len(points) < 2:
        raise ValueError("a route needs at least two points")
    return _post_route(build_waypoint_request(points, custom_model), 0, client, base_url)


def route_to_geojson(
    route: Route,
    start_lat: float,
    start_lon: float,
    start_label: str,
    requested_miles: float,
    shape: dict | None = None,
    extra_properties: dict | None = None,
    name: str = "Route",
) -> dict:
    """`shape` is ShapeMetrics.as_dict(); its fields are added to the route's properties."""
    actual_miles = meters_to_miles(route.distance_m)
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": route.coordinates},
                "properties": {
                    "name": name,  # decision 044: from the route's measured kind, never a fixed "Loop route"
                    "requested_miles": requested_miles,
                    "actual_miles": round(actual_miles, 3),
                    "percent_off": round(percent_off(requested_miles, actual_miles), 1),
                    "estimated_minutes_walking_pace": round(route.time_s / 60),
                    "seed": route.seed,
                    "profile": "foot",
                    **{k: v for k, v in (shape or {}).items() if k != "distance_miles"},
                    **(extra_properties or {}),
                    "stroke": "#e8590c",
                    "stroke-width": 4,
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [start_lon, start_lat]},
                "properties": {"name": "Start / finish", "label": start_label, "marker-color": "#2b8a3e"},
            },
        ],
    }
