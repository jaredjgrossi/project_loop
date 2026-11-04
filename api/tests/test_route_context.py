"""Share-of-route and crossing counts on hand-made geometry (meters converted to lon/lat)."""

import math

import pytest

from api.route_context import (
    COMPOSITION,
    Crossing,
    composition_by_range,
    crossing_counts,
    crossing_passes,
    familiar_share,
    park_or_water_share,
    park_share,
    pieces_by_range,
    sample_classes,
    waterfront_share,
)

LAT0, LON0 = 40.74, -73.98
KY = 110_574
KX = 111_320 * math.cos(math.radians(LAT0))


def ll(points_m):
    return [[LON0 + x / KX, LAT0 + y / KY] for x, y in points_m]


STRAIGHT = ll([(0, 0), (1000, 0)])  # 1 km east


def test_park_share_is_the_share_of_the_route_inside_a_park():
    park = [ll([(250, -50), (750, -50), (750, 50), (250, 50), (250, -50)])]
    assert park_share(STRAIGHT, [park]) == pytest.approx(50, abs=1.5)


def test_park_share_with_no_parks_is_zero():
    assert park_share(STRAIGHT, []) == 0


def test_overlapping_parks_are_not_double_counted():
    a = [ll([(0, -50), (600, -50), (600, 50), (0, 50), (0, -50)])]
    b = [ll([(400, -50), (1000, -50), (1000, 50), (400, 50), (400, -50)])]
    assert park_share(STRAIGHT, [a, b]) == pytest.approx(100, abs=1)


def test_waterfront_share_counts_route_within_the_distance_of_the_shore():
    shore = [ll([(0, 40), (500, 40)])]  # 40 m north of the first half, then nothing
    # Within 60 m up to x = 500 + sqrt(60^2 - 40^2) = 545 m, past the shoreline's end.
    assert waterfront_share(STRAIGHT, shore, within_m=60) == pytest.approx(54.5, abs=1)
    assert waterfront_share(STRAIGHT, shore, within_m=30) == 0


def test_a_crossing_the_route_walks_along_is_counted_and_one_it_passes_is_not():
    on_route = Crossing(way_id=1, signals=True, coords=ll([(300, 0), (320, 0)]))  # route uses the crosswalk
    signal_beside = Crossing(way_id=2, signals=True, coords=ll([(500, 10), (500, 30)]))  # perpendicular, not walked
    unsignalized = Crossing(way_id=3, signals=False, coords=ll([(700, 0), (715, 0)]))
    count, signals = crossing_counts(STRAIGHT, [on_route, signal_beside, unsignalized])
    assert count == 2
    assert signals == 1


def test_a_crossing_only_touched_at_one_end_is_not_counted():
    # The route turns at the corner where a crosswalk starts but doesn't cross the street.
    corner = Crossing(way_id=4, signals=True, coords=ll([(1000, 0), (1000, 20)]))
    assert crossing_counts(STRAIGHT, [corner]) == (0, 0)


def test_park_or_water_counts_each_stretch_once():
    park = [ll([(0, -50), (600, -50), (600, 50), (0, 50), (0, -50)])]
    shore = [ll([(400, 30), (800, 30)])]  # overlaps the park from 400 to 600 m
    # Park 0-600, water from 400 - 50 (60 m radius, 30 m off) to 800 + 52: union is 0-852 m of 1000.
    assert park_or_water_share(STRAIGHT, [park], shore) == pytest.approx(85, abs=2)


def test_familiar_share_is_the_route_on_ways_already_run():
    run_before = [ll([(0, 3), (300, 3)])]
    assert familiar_share(STRAIGHT, run_before) == pytest.approx(30.8, abs=1.5)
    assert familiar_share(STRAIGHT, []) == 0


# --- decision 018: no crowd sampling without a start time ---------------------------------


class _OnlyRegclass:
    """A connection that answers the crowd table check and fails on anything else."""

    def __init__(self, loaded=True):
        self.loaded, self.queries = loaded, []

    def execute(self, sql, args=None):
        self.queries.append(sql)
        assert "to_regclass('sidewalk_crowd')" in sql, f"unexpected query without a start time: {sql[:80]}"
        loaded = self.loaded

        class _R:
            def fetchone(self):
                return (loaded,)

        return _R()


def test_without_a_start_time_crowds_are_not_sampled_and_the_summary_is_unchanged():
    from api.route_context import _crowd_fields

    coords = [[-73.98, 40.74], [-73.98, 40.75], [-73.97, 40.75]]
    conn = _OnlyRegclass()
    assert _crowd_fields(conn, coords, None) == {
        "crowd_high_pct": 0.0, "crowd_medium_pct": 0.0, "crowd_low_pct": 0.0, "crowd_not_scored_pct": 100.0,
        "crowd_band": None, "crowd_reason": "no start time given", "crowd_start_band": None}
    assert len(conn.queries) == 1


def test_without_crowd_data_loaded_the_reason_says_so_as_before():
    from api.route_context import _crowd_fields

    fields = _crowd_fields(_OnlyRegclass(loaded=False), [[-73.98, 40.74], [-73.98, 40.75]], None)
    assert fields["crowd_reason"] == "crowd data not loaded" and fields["crowd_not_scored_pct"] == 100.0


# --- decision 018: prefilters and shared samples give the same numbers ----------------------

import random  # noqa: E402

from api.route_context import (  # noqa: E402
    CROSSING_COVERED, Crossing, _Frame, _samples, _SegmentIndex, crossing_counts, park_or_water_share, park_share,
    shares, waterfront_share,
)


def _reference_crossing_counts(coords, crossings):
    """crossing_counts as it was before decision 018: every crosswalk sampled, no prefilter."""
    if not crossings:
        return 0, 0
    frame = _Frame(coords[0][1])
    route = _SegmentIndex([coords], frame, 4.0)
    count = signals = 0
    for c in crossings:
        pts = _samples(c.coords, frame, step=1.0)
        near = [route.near(p) for p in pts]
        if sum(near) / len(near) >= CROSSING_COVERED:
            count += 1
            signals += c.signals
    return count, signals


def _random_case(seed):
    rnd = random.Random(seed)
    lon0, lat0 = -73.98, 40.74
    m = lambda dx, dy: [lon0 + dx / 84_300, lat0 + dy / 110_574]
    route, x, y = [m(0, 0)], 0.0, 0.0
    for _ in range(rnd.randint(3, 12)):
        x, y = x + rnd.uniform(-300, 300), y + rnd.uniform(-300, 300)
        route.append(m(x, y))
    crossings = []
    for k in range(80):
        if k % 2:  # on or right beside the route: a vertex plus an offset of 0-6 m, so cell edges are exercised
            a = rnd.choice(route)
            cx, cy = (a[0] - lon0) * 84_300 + rnd.uniform(-6, 6), (a[1] - lat0) * 110_574 + rnd.uniform(-6, 6)
        else:
            cx, cy = rnd.uniform(-1500, 1500), rnd.uniform(-1500, 1500)
        ang, half = rnd.uniform(0, math.pi), rnd.uniform(3, 12)
        line = [m(cx - half * math.cos(ang), cy - half * math.sin(ang)), m(cx + half * math.cos(ang), cy + half * math.sin(ang))]
        crossings.append(Crossing(k, bool(rnd.getrandbits(1)), line))
    parks = [[[m(-200, -200), m(200, -200), m(200, 200), m(-200, 200), m(-200, -200)]]]
    shore = [[m(-1000, 150), m(1000, 160)]]
    return route, crossings, parks, shore


@pytest.mark.parametrize("seed", range(40))
def test_prefiltered_crossing_counts_match_the_unfiltered_ones(seed):
    route, crossings, _, _ = _random_case(seed)
    assert crossing_counts(route, crossings) == _reference_crossing_counts(route, crossings)


@pytest.mark.parametrize("seed", range(40))
def test_every_crossing_is_never_fewer_than_each_crosswalk_once(seed):
    route, crossings, _, _ = _random_case(seed)
    made = crossing_passes(route, crossings)
    count, signals = crossing_counts(route, crossings)
    assert len(made) >= count and sum(s for _, s in made) >= signals
    assert [a for a, _ in made] == sorted(a for a, _ in made)


def test_an_out_and_back_crosses_each_crosswalk_twice():
    # Out 1 km and back on the same line, a 16 m crosswalk on it every 200 m (a crosswalk way runs the way you
    # walk across the street, so the route covers it lengthwise).
    route = ll([(0, 0), (1000, 0), (0, 0)])
    crossings = [Crossing(k, True, ll([(x - 8, 0), (x + 8, 0)])) for k, x in enumerate(range(100, 1000, 200))]
    made = crossing_passes(route, crossings)
    assert crossing_counts(route, crossings) == (5, 5)  # the ranking's input: each crosswalk once
    assert len(made) == 10 and all(s for _, s in made)
    assert made[0][0] == pytest.approx(100, abs=10) and made[-1][0] == pytest.approx(1900, abs=10)


def test_a_route_that_never_comes_back_crosses_each_crosswalk_once():
    crossings = [Crossing(k, k % 2 == 0, ll([(x - 8, 0), (x + 8, 0)])) for k, x in enumerate(range(100, 1000, 200))]
    made = crossing_passes(STRAIGHT, crossings)
    assert len(made) == 5 and sum(s for _, s in made) == 3


@pytest.mark.parametrize("seed", range(20))
def test_shared_samples_give_the_same_three_shares(seed):
    route, _, parks, shore = _random_case(seed)
    for p, s in ((parks, shore), ([], shore), (parks, []), ([], [])):
        assert shares(route, p, s) == (park_share(route, p), waterfront_share(route, s), park_or_water_share(route, p, s))


# --- composition (decision 020) ---

def _composition_scene():
    # 1 km east: a park over 200-400 m, a catalog path beside 400-600 m, the shore 30 m off from 600 m on, and a
    # park that is also by the water at 900-1000 m (counted as waterfront, never twice).
    parks = [[ll([(200, -50), (400, -50), (400, 50), (200, 50), (200, -50)])],
             [ll([(900, -50), (1000, -50), (1000, 50), (900, 50), (900, -50)])]]
    shore = [ll([(600, 30), (1200, 30)])]
    path = [ll([(400, 5), (600, 5)])]
    return parks, shore, path


def test_sample_classes_split_the_route_without_overlap():
    parks, shore, path = _composition_scene()
    classes, along = sample_classes(STRAIGHT, parks, shore, path)
    assert len(classes) == len(along) and along[-1] == pytest.approx(1000, abs=1)
    share = {k: 100 * classes.count(k) / len(classes) for k in COMPOSITION}
    assert sum(share.values()) == pytest.approx(100)
    assert share["park"] == pytest.approx(20, abs=1.5)
    assert share["path"] == pytest.approx(15, abs=2)  # 400-600 m, less the part already within 60 m of the shore
    assert share["street"] == pytest.approx(20, abs=1.5)


def test_waterfront_and_park_classes_match_the_route_shares_exactly():
    parks, shore, path = _composition_scene()
    classes, _ = sample_classes(STRAIGHT, parks, shore, path)
    n = len(classes)
    assert 100 * classes.count("waterfront") / n == pytest.approx(waterfront_share(STRAIGHT, shore))
    assert 100 * (classes.count("waterfront") + classes.count("park")) / n == pytest.approx(
        park_or_water_share(STRAIGHT, parks, shore))


def test_stretch_compositions_add_up_to_the_route():
    parks, shore, path = _composition_scene()
    classes, along = sample_classes(STRAIGHT, parks, shore, path)
    parts = composition_by_range(classes, along, [0.0, 300.0, 700.0])
    assert len(parts) == 3
    total = along[-1]
    for k in COMPOSITION:
        assert sum(p[k] for p in parts) == pytest.approx(total * classes.count(k) / len(classes))
    assert parts[0]["street"] == pytest.approx(200, abs=10) and parts[0]["park"] == pytest.approx(100, abs=10)
    assert parts[2]["park"] == 0  # the park at 900-1000 m is by the water: waterfront


def test_pieces_split_at_every_change_of_class_and_of_range():
    parks, shore, path = _composition_scene()
    classes, along = sample_classes(STRAIGHT, parks, shore, path)
    bounds = [0.0, 300.0, 700.0]
    pieces = pieces_by_range(STRAIGHT, classes, along, bounds)
    for a, b in zip(pieces, pieces[1:]):
        assert (a["kind"], a["range"]) != (b["kind"], b["range"])  # neighbors differ in kind or stretch
        assert a["end_m"] == b["start_m"] and a["range"] <= b["range"]
    assert pieces[0]["start_m"] == 0 and pieces[-1]["end_m"] == pytest.approx(along[-1])
    assert [p["kind"] for p in pieces if p["range"] == 0] == ["street", "park"]  # 0-200 street, 200-300 park


def test_pieces_add_up_to_the_stretch_compositions_exactly():
    parks, shore, path = _composition_scene()
    classes, along = sample_classes(STRAIGHT, parks, shore, path)
    bounds = [0.0, 300.0, 700.0]
    parts = composition_by_range(classes, along, bounds)
    pieces = pieces_by_range(STRAIGHT, classes, along, bounds)
    for i, part in enumerate(parts):
        for k in COMPOSITION:
            assert sum(p["length_m"] for p in pieces if p["range"] == i and p["kind"] == k) == pytest.approx(part[k])


def test_piece_lines_join_up_and_cover_the_route():
    parks, shore, path = _composition_scene()
    classes, along = sample_classes(STRAIGHT, parks, shore, path)
    pieces = pieces_by_range(STRAIGHT, classes, along, [0.0, 300.0, 700.0])
    assert all(len(p["coordinates"]) >= 2 for p in pieces)
    for a, b in zip(pieces, pieces[1:]):
        assert a["coordinates"][-1] == pytest.approx(b["coordinates"][0])
    assert pieces[0]["coordinates"][0] == pytest.approx(STRAIGHT[0])
    assert pieces[-1]["coordinates"][-1] == pytest.approx(STRAIGHT[-1])
