from api.scripts.ui_fixture import build_fixture, top3_entry

DISTANCE = {"value": 3.07, "unit": "mi", "status": "measured", "source": "route geometry", "meters": 4938,
            "router_meters": 4958}


def ranked(rank, miles):
    distance = {**DISTANCE, "value": miles}
    return {"type": "FeatureCollection", "features": [{
        "type": "Feature", "geometry": {"type": "LineString", "coordinates": [[-73.97, 40.74], [-73.96, 40.74]]},
        "properties": {"rank": rank, "kind": "out_and_back", "label": f"Route {rank}", "score": 90 - rank,
                       "request": [{"key": "distance", "title": "Distance", "value": "3 mi", "origin": "you said"}],
                       "summary": {"distance": distance}}}]}


POOL = {"pool": [{"status": "ok"}, {"status": "ok"}, {"status": "too_long"}], "best_of": 2, "timing": {}}


def test_every_top3_distance_carries_its_unit_trust_label_and_source():
    fixture = build_fixture([ranked(1, 3.07), ranked(2, 2.98), ranked(3, 3.11)], POOL, "abc1234", "2026-11-04T09:00")
    assert [t["rank"] for t in fixture["top3"]] == [1, 2, 3]
    for t in fixture["top3"]:
        d = t["distance"]
        assert d["unit"] == "mi" and d["status"] == "measured" and d["source"]
    assert [t["distance"]["value"] for t in fixture["top3"]] == [3.07, 2.98, 3.11]


def test_the_first_of_the_top3_is_the_route_shown():
    first = ranked(1, 3.07)
    fixture = build_fixture([first, ranked(2, 2.98), ranked(3, 3.11)], POOL, "abc1234", "2026-11-04T09:00")
    assert fixture["top3"][0]["distance"] == first["features"][0]["properties"]["summary"]["distance"]
    assert fixture["top3"][0]["geometry"] == fixture["route"]["features"][0]["geometry"]
    assert fixture["pool"] == {"candidates": 3, "best_of": 2, "statuses": {"ok": 2, "too_long": 1}, "timing": {}}
    assert top3_entry(2, ranked(2, 2.98))["label"] == "Route 2"
