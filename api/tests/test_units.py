import pytest

from api.units import meters_to_miles, miles_to_meters, percent_off


def test_one_mile_is_1609_344_meters():
    assert miles_to_meters(1) == pytest.approx(1609.344)


def test_round_trip_conversion():
    assert meters_to_miles(miles_to_meters(6.2)) == pytest.approx(6.2)


def test_four_miles():
    assert miles_to_meters(4) == pytest.approx(6437.376)


def test_zero_is_allowed():
    assert miles_to_meters(0) == 0


def test_negative_distance_rejected():
    with pytest.raises(ValueError):
        miles_to_meters(-1)


def test_percent_off_is_signed_relative_to_requested():
    assert percent_off(requested=4.0, actual=4.4) == pytest.approx(10.0)
    assert percent_off(requested=4.0, actual=3.6) == pytest.approx(-10.0)


def test_percent_off_requires_positive_request():
    with pytest.raises(ValueError):
        percent_off(requested=0, actual=1)
