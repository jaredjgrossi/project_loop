"""Decision 045: a spur at one of the route's own waypoints is moved to its base and routed again.

The fake network is one path running north from the start, with dead ends running east off it. A waypoint east of
the path is reached up its dead end and left the same way, as GraphHopper does with a waypoint off the main line:
from Kips Bay the nearest point of the East River Esplanade is 75 m south of E 34th St, where the streets reach it.
"""

import math

from api.generate import without_waypoint_spurs
from api.markers import spurs
from api.routing import Route

LAT0, LON0 = 40.78, -73.985
KX = 111_320 * math.cos(math.radians(LAT0))
KY = 110_574


def _ll(e, n):
    """(lat, lon), as the generator passes waypoints."""
    return (LAT0 + n / KY, LON0 + e / KX)


def _en(p):
    return ((p[1] - LON0) * KX, (p[0] - LAT0) * KY)


def _line(corners, step=10):
    out = []
    for (e0, n0), (e1, n1) in zip(corners, corners[1:]):
        k = max(int(math.hypot(e1 - e0, n1 - n0) / step), 1)
        out += [(e0 + (e1 - e0) * i / k, n0 + (n1 - n0) * i / k) for i in range(k)]
    out.append(corners[-1])
    return [[LON0 + e / KX, LAT0 + n / KY] for e, n in out]


class FakeNetwork:
    """Routes along the north path; a waypoint more than 20 m east of it is reached up its own dead end and left the
    same way. `extra_spur_at` adds a dead end the router takes on its own (not at any waypoint)."""

    def __init__(self, extra_spur_at=None):
        self.calls = []
        self.extra = extra_spur_at

    def __call__(self, points):
        self.calls.append(list(points))
        corners = []
        for p in points:
            e, n = _en(p)
            if e > 20:
                corners += [(0, n), (e, n), (0, n)]
            else:
                corners.append((0, n))
        if self.extra is not None:
            i = next(i for i, c in enumerate(corners) if i and c[1] > self.extra)
            corners[i:i] = [(0, self.extra), (250, self.extra), (0, self.extra)]
        line = _line(corners)
        length = sum(math.dist(_en((a[1], a[0])), _en((b[1], b[0]))) for a, b in zip(line, line[1:]))
        return Route(distance_m=length, time_s=length / 1.4, coordinates=line)


def test_a_spur_at_a_waypoint_moves_the_waypoint_to_the_spur_base():
    net = FakeNetwork()
    entry, turn = _ll(250, 1000), _ll(0, 4000)
    route = without_waypoint_spurs(net)([_ll(0, 0), entry, turn, entry, _ll(0, 0)])
    assert len(net.calls) == 2  # routed once more, with the waypoint moved
    moved = net.calls[1]
    # Both visits moved to the base: on the main line, at most REACH_SAME_M (30 m) before the junction, as the reach
    # counts the main line that close to the way back
    e, n = _en(moved[1])
    assert abs(e) <= 1 and 970 <= n <= 1000 and moved[3] == moved[1]
    assert moved[0] == _ll(0, 0) and moved[2] == turn  # the start, the end and other waypoints stay
    assert spurs(route.coordinates) == []
    assert route.distance_m < 8000 + 50  # the 2 x 250 m of padding is gone


def test_a_route_without_spurs_is_routed_once():
    net = FakeNetwork()
    route = without_waypoint_spurs(net)([_ll(0, 0), _ll(0, 4000), _ll(0, 0)])
    assert len(net.calls) == 1 and spurs(route.coordinates) == []


def test_a_spur_away_from_every_waypoint_is_left_for_the_spur_rule():
    net = FakeNetwork(extra_spur_at=1500)
    route = without_waypoint_spurs(net)([_ll(0, 0), _ll(0, 4000), _ll(0, 0)])
    assert len(net.calls) == 1  # nothing of ours to move: the generator's spur rule rejects the route
    assert len(spurs(route.coordinates)) == 1


def test_extra_router_arguments_pass_through():  # area_route_fn(points, area)
    seen = []
    net = FakeNetwork()

    def area_router(points, area):
        seen.append(area)
        return net(points)

    without_waypoint_spurs(area_router)([_ll(0, 0), _ll(250, 1000), _ll(0, 4000), _ll(0, 0)], "the area")
    assert seen == ["the area", "the area"]
