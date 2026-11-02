"""Expected wait at lights, on hand-made routes in a grid rotated like Manhattan's (29 degrees)."""

import math

import pytest

from api.constraints import Lights
from api.lights import (
    WAIT_PER_SIGNAL_S,
    expected_wait,
    signal_penalty_model,
    signal_positions,
)
from api.route_context import Crossing

LAT0, LON0 = 40.74, -73.98
KX = 111_320 * math.cos(math.radians(LAT0))
KY = 110_574
GRID = 29.0


def grid_xy(u, v):
    """Meters along (u) and across (v) a grid rotated GRID degrees east of north."""
    a = math.radians(GRID)
    return u * math.sin(a) + v * math.cos(a), u * math.cos(a) - v * math.sin(a)


def ll(points_uv):
    return [[LON0 + x / KX, LAT0 + y / KY] for x, y in (grid_xy(u, v) for u, v in points_uv)]


def densify(points_uv, step=20):
    out = [points_uv[0]]
    for (u0, v0), (u1, v1) in zip(points_uv, points_uv[1:]):
        n = max(1, int(math.hypot(u1 - u0, v1 - v0) // step))
        out += [(u0 + (u1 - u0) * k / n, v0 + (v1 - v0) * k / n) for k in range(1, n + 1)]
    return out


STRAIGHT = densify([(0, 0), (2000, 0)])  # 2 km up one avenue
STAIRCASE = densify([p for k in range(12) for p in ((k * 160, k * 80), ((k + 1) * 160, k * 80))])  # zig-zag NE


def signals_every(route_uv, every_m):
    """A signalized crosswalk across the route every `every_m` (crosswalks drawn along the route, 15 m long)."""
    coords = ll(route_uv)
    out, along = [], 0.0
    pts = route_uv
    for (u0, v0), (u1, v1) in zip(pts, pts[1:]):
        seg = math.hypot(u1 - u0, v1 - v0)
        if int((along + seg) // every_m) > int(along // every_m):
            out.append(Crossing(len(out), True, ll([(u0, v0), (u1, v1)])))
        along += seg
    return coords, out


def test_signal_positions_are_ordered_along_the_route():
    coords, crossings = signals_every(STRAIGHT, 250)
    pos = signal_positions(coords, crossings)
    assert len(pos) == len(crossings) == 8  # at 250, 500, ... 2000 m
    assert pos == sorted(pos) and pos[0] == pytest.approx(250, abs=30)


def test_a_runner_who_waits_waits_at_every_signal():
    coords, crossings = signals_every(STRAIGHT, 250)
    w = expected_wait(coords, crossings, GRID, grid_strong=True, lights=Lights.WAITS)
    assert w["status"] == "estimate"
    assert w["seconds"] == pytest.approx(len(crossings) * WAIT_PER_SIGNAL_S, rel=0.01)
    assert w["credited"] == 0


def test_a_zigzagger_on_a_straight_avenue_has_no_alternative():
    coords, crossings = signals_every(STRAIGHT, 250)
    w = expected_wait(coords, crossings, GRID, grid_strong=True, lights=Lights.ZIGZAGS)
    assert w["credited"] == 0 and w["seconds"] == pytest.approx(len(crossings) * WAIT_PER_SIGNAL_S, rel=0.01)


def test_a_zigzagger_on_a_staircase_turns_on_the_red():
    coords, crossings = signals_every(STAIRCASE, 200)
    waits = expected_wait(coords, crossings, GRID, grid_strong=True, lights=Lights.WAITS)
    zig = expected_wait(coords, crossings, GRID, grid_strong=True, lights=Lights.ZIGZAGS)
    assert zig["credited"] >= 0.7 * len(crossings)
    assert zig["seconds"] < 0.4 * waits["seconds"]


def test_no_credit_without_a_street_grid():
    coords, crossings = signals_every(STAIRCASE, 200)
    w = expected_wait(coords, crossings, GRID, grid_strong=False, lights=Lights.ZIGZAGS)
    assert w["credited"] == 0


def test_no_credit_near_a_turnaround():
    # Out 600 m and back: the way ahead doubles back, so turning off doesn't keep the same length.
    out_back = densify([(0, 0), (600, 0), (600, 5), (0, 5)])
    coords, crossings = signals_every(out_back, 150)
    w = expected_wait(coords, crossings, GRID, grid_strong=True, lights=Lights.ZIGZAGS)
    assert w["credited"] == 0


def test_the_penalty_model_targets_signalized_crossings_only():
    m = signal_penalty_model()
    assert m["priority"] == [{"if": "crossing == TRAFFIC_SIGNALS", "multiply_by": "0.2"}]


def test_lights_can_be_given_as_a_plain_string():
    # The review renderer passes preferences as ("lights", "waits"); this used to raise and hang generation.
    coords, crossings = signals_every(STRAIGHT, 250)
    assert expected_wait(coords, crossings, GRID, grid_strong=True, lights="waits")["lights"] == "waits"
    assert expected_wait(coords, crossings, GRID, grid_strong=True, lights="zigzags")["lights"] == "zigzags"
