"""Geocoder behavior, pinned against real GeoSearch responses (see fixtures/README.md).

What the live service actually does (found while building this):
- Every NYC address comes back from layer "venue" / source "nycpad"; there is no
  separate "address" layer, so filtering by layer returns nothing.
- Confidence is 0.8 / match_type "fallback" for valid street addresses too, so it
  cannot be used as a quality signal.
- The real hazards are: the same number+street existing in several boroughs, a
  "fallback" answer with a different house number, and place names resolving to
  an arbitrary building.
"""

import json
from pathlib import Path

import httpx
import pytest

from api.geocoding import (
    AmbiguousAddressError,
    GeocodeError,
    GeocodeUnavailableError,
    LowConfidenceError,
    NoMatchError,
    NotAnAddressError,
    geocode,
    normalize_street,
    parse_address_query,
    resolve,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"geosearch_{name}.json").read_text())


# --- normalization / query parsing -------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("5th Ave", "5 AVENUE"),
        ("Madison Ave.", "MADISON AVENUE"),
        ("W 4th St", "WEST 4 STREET"),
        ("E 14th St", "EAST 14 STREET"),
        ("EAST 14 STREET", "EAST 14 STREET"),
        ("Central Park West", "CENTRAL PARK WEST"),
        ("1st Ave", "1 AVENUE"),
        ("22nd Street", "22 STREET"),
    ],
)
def test_normalize_street(raw, expected):
    assert normalize_street(raw) == expected


def test_parse_simple_address_with_borough():
    q = parse_address_query("11 Madison Ave, Manhattan")
    assert (q.housenumber, q.street, q.borough, q.postalcode) == ("11", "MADISON AVENUE", "Manhattan", None)


def test_parse_zip_without_commas():
    q = parse_address_query("350 5th Ave 11215")
    assert (q.housenumber, q.street, q.borough, q.postalcode) == ("350", "5 AVENUE", None, "11215")


def test_parse_trailing_borough_without_comma():
    q = parse_address_query("350 5th Ave Brooklyn")
    assert (q.street, q.borough) == ("5 AVENUE", "Brooklyn")


def test_borough_word_inside_street_name_is_not_a_borough_hint():
    q = parse_address_query("100 Brooklyn Ave")
    assert q.street == "BROOKLYN AVENUE"
    assert q.borough is None


def test_parse_queens_hyphenated_number():
    q = parse_address_query("59-11 Madison St, Queens")
    assert (q.housenumber, q.street, q.borough) == ("59-11", "MADISON STREET", "Queens")


def test_parse_place_name_has_no_housenumber():
    assert parse_address_query("Union Square").housenumber is None


# --- resolving real responses -------------------------------------------------


def test_resolves_manhattan_address():
    r = resolve("11 Madison Ave, Manhattan", load("madison_ave_manhattan"))
    assert r.label == "11 MADISON AVENUE, New York, NY, USA"
    assert r.borough == "Manhattan"
    assert (r.lon, r.lat) == pytest.approx((-73.986485, 40.741518))
    assert r.source == "nycpad"


def test_borough_hint_beats_service_ranking():
    # Even if the service ranks Staten Island first, an explicit borough wins.
    r = resolve("11 Madison Ave, Manhattan", load("madison_ave_bare"))
    assert r.borough == "Manhattan"


def test_same_address_in_two_boroughs_fails_instead_of_guessing():
    # The service ranks Staten Island first for the bare query. We must not take it.
    with pytest.raises(AmbiguousAddressError) as exc:
        resolve("11 Madison Ave", load("madison_ave_bare"))
    assert set(exc.value.boroughs) == {"Manhattan", "Staten Island"}
    assert "Manhattan" in str(exc.value) and "Staten Island" in str(exc.value)


def test_fifth_ave_ambiguous_then_resolved_by_borough_or_zip():
    resp = load("fifth_ave_two_boroughs")
    with pytest.raises(AmbiguousAddressError):
        resolve("350 5th Ave", resp)
    assert resolve("350 5th Ave, Brooklyn", resp).borough == "Brooklyn"
    assert resolve("350 5th Ave 10118", resp).borough == "Manhattan"


def test_wrong_house_number_is_rejected_with_nearest_named():
    # "100 Main St": the service answers with other numbers at 0.8 "fallback".
    with pytest.raises(LowConfidenceError) as exc:
        resolve("100 Main St", load("main_st_wrong_number"))
    assert "100" in str(exc.value)
    assert exc.value.nearest  # tells the user what the service offered instead


def test_place_name_is_not_accepted_as_a_start_point():
    # "Union Square" resolves to "5 UNION SQUARE", an arbitrary building.
    with pytest.raises(NotAnAddressError) as exc:
        resolve("Union Square", load("union_square_place"))
    assert "street address" in str(exc.value)


def test_no_results():
    with pytest.raises(NoMatchError):
        resolve("ASDFGHJKL zzz", load("nonsense"))


def test_result_outside_nyc_is_rejected():
    resp = {
        "features": [
            {
                "geometry": {"type": "Point", "coordinates": [-87.6, 41.8]},
                "properties": {
                    "housenumber": "11",
                    "street": "MADISON AVENUE",
                    "borough": "Manhattan",
                    "label": "11 MADISON AVENUE",
                    "source": "nycpad",
                    "source_id": "1",
                    "match_type": "exact",
                    "confidence": 1,
                },
            }
        ]
    }
    with pytest.raises(LowConfidenceError):
        resolve("11 Madison Ave", resp)


def test_all_geocode_errors_share_a_base_class():
    for cls in (NoMatchError, AmbiguousAddressError, LowConfidenceError, NotAnAddressError, GeocodeUnavailableError):
        assert issubclass(cls, GeocodeError)


# --- the HTTP wrapper ------------------------------------------------------------


def client_returning(payload=None, status=200, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=payload if payload is not None else {})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_geocode_sends_text_and_asks_for_enough_candidates_to_see_ambiguity():
    seen: list[httpx.Request] = []
    r = geocode("11 Madison Ave, Manhattan", client=client_returning(load("madison_ave_manhattan"), seen=seen))
    assert r.borough == "Manhattan"
    params = dict(seen[0].url.params)
    assert params["text"] == "11 Madison Ave, Manhattan"
    assert int(params["size"]) >= 10


def test_http_error_is_reported_as_service_unavailable():
    with pytest.raises(GeocodeUnavailableError):
        geocode("11 Madison Ave, Manhattan", client=client_returning(status=503))


def test_network_failure_is_reported_as_service_unavailable():
    def boom(request):
        raise httpx.ConnectError("no network")

    with pytest.raises(GeocodeUnavailableError):
        geocode("11 Madison Ave, Manhattan", client=httpx.Client(transport=httpx.MockTransport(boom)))
