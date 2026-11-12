"""The curated landmarks file (decision 047): what the loader relies on, and what a lookup must never trip over."""

from api.places import KIND_PRIORITY, LANDMARK_KINDS, SAME_NAME_ORDER, PlaceMatch, normalize, one_per_name
from etl.load_landmarks import BOROUGHS, landmark_rows, read_landmarks

NYC_BOX = (40.49, 40.92, -74.27, -73.68)  # south, north, west, east: the five boroughs


def test_every_landmark_has_what_the_loader_needs():
    for row in read_landmarks():
        assert row["name"].strip() and row["what"].strip(), row
        assert row["borough"] in BOROUGHS, row
        south, north, west, east = NYC_BOX
        assert south <= row["lat"] <= north and west <= row["lon"] <= east, row  # a swapped lat and lon fails here
        assert all(a.strip() for a in row["aliases"]), row


def test_a_name_or_alias_belongs_to_one_landmark():
    seen = {}
    for row in read_landmarks():
        for name in [row["name"], *row["aliases"]]:
            key = normalize(name)
            assert seen.setdefault(key, row["name"]) == row["name"], f"{name!r} names {seen[key]} and {row['name']}"


def test_the_loader_rows_carry_a_source_and_a_trust_label():
    rows = landmark_rows(read_landmarks())
    assert len(rows) == len(read_landmarks()) >= 30
    for r in rows:
        assert r["kind"] == "landmark" and r["source"] and r["source_dataset_id"] == "loop:landmarks"
        assert r["source_row_id"].startswith("landmark/")


def test_the_main_landmarks_are_there():
    names = {r["name"] for r in read_landmarks()}
    for want in ("Metropolitan Museum of Art", "Guggenheim Museum", "Whitney Museum of American Art",
                 "Empire State Building", "Chrysler Building", "Flatiron Building", "One World Trade Center",
                 "Madison Square Garden", "Gracie Mansion", "Grant's Tomb", "American Museum of Natural History",
                 "Yankee Stadium", "Barclays Center", "Brooklyn Museum"):
        assert want in names, want


def test_a_landmark_beats_a_shop_with_its_name_and_is_kept_by_a_partial_match():
    assert "landmark" in KIND_PRIORITY and "landmark" in LANDMARK_KINDS
    assert SAME_NAME_ORDER.index("landmark") < SAME_NAME_ORDER.index("shop")
    museum = PlaceMatch("Metropolitan Museum of Art", "landmark", "Manhattan", 40.7794, -73.9634, "The Met", "Loop", ())
    shop = PlaceMatch("Met", "shop", "Manhattan", 40.74, -73.99, "Met", "OpenStreetMap", ())
    assert one_per_name([shop, museum]) == [shop, museum]  # different names: both stay; the rule is per name
    same = PlaceMatch("Yankee Stadium", "landmark", "Bronx", 40.8296, -73.9265, "Yankee Stadium", "Loop", ())
    bar = PlaceMatch("Yankee Stadium", "amenity", "Bronx", 40.83, -73.92, "Yankee Stadium", "OpenStreetMap", ())
    assert one_per_name([bar, same]) == [same]
