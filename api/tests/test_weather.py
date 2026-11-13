"""The weather line under the wordmark (decision 051): a real station observation with its own timestamp, cached for
a few minutes, an error rather than an old reading dressed as fresh."""

from datetime import datetime, timezone

import httpx
import pytest

from api.weather import CACHE_S, MAX_AGE_S, WeatherService, WeatherUnavailable, condition_of, parse_observation

NOW = datetime(2026, 11, 13, 19, 0, tzinfo=timezone.utc).timestamp()


def obs(temp_c=5.0, text="Cloudy", at="2026-11-13T18:51:00+00:00", present=()):
    return {"properties": {"timestamp": at, "textDescription": text,
                           "temperature": {"unitCode": "wmoUnit:degC", "value": temp_c, "qualityControl": "V"},
                           "presentWeather": [{"weather": w} for w in present]}}


# ---- reading one observation ---------------------------------------------------------------------------------------


def test_an_observation_becomes_a_reading_with_its_own_time_and_source():
    r = parse_observation(obs(5.0), "KNYC", NOW)
    assert r["temp_f"] == 41 and r["condition"] == "cloudy" and r["description"] == "Cloudy"
    assert r["observed_at"] == "2026-11-13T18:51:00Z"  # the station's time, not the request's
    assert r["station"] == "KNYC" and "National Weather Service" in r["source"] and "Central Park" in r["source"]
    assert r["status"] == "measured"


@pytest.mark.parametrize("c, f", [(0.0, 32), (-1.0, 30), (6.1, 43), (21.1, 70), (-17.8, 0)])
def test_celsius_is_rounded_to_whole_fahrenheit(c, f):
    assert parse_observation(obs(c), "KLGA", NOW)["temp_f"] == f


def test_a_timestamp_with_an_offset_is_shown_in_utc():
    assert parse_observation(obs(at="2026-11-13T13:51:00-05:00"), "KNYC", NOW)["observed_at"] == "2026-11-13T18:51:00Z"


@pytest.mark.parametrize("bad", [
    obs(None),  # a station that reports no temperature
    obs(at="2026-11-13T17:00:00+00:00"),  # older than the limit
    obs(at="2026-11-13T19:30:00+00:00"),  # from the future
    {"properties": {"timestamp": None, "temperature": {"value": 5.0}}},
    {"properties": {"timestamp": "yesterday", "temperature": {"value": 5.0}}},
    {},
])
def test_an_observation_that_cant_be_trusted_is_no_reading(bad):
    assert parse_observation(bad, "KNYC", NOW) is None


def test_the_age_limit_is_an_hour():
    assert MAX_AGE_S == 3600
    just_in = datetime.fromtimestamp(NOW - MAX_AGE_S + 60, timezone.utc).isoformat()
    assert parse_observation(obs(at=just_in), "KNYC", NOW) is not None


@pytest.mark.parametrize("text, present, condition", [
    ("Clear", (), "clear"), ("Fair", (), "clear"), ("Mostly Clear", (), "clear"), ("A Few Clouds", (), "clear"),
    ("Partly Cloudy", (), "partly_cloudy"), ("Mostly Cloudy", (), "cloudy"), ("Overcast", (), "cloudy"),
    ("Cloudy", (), "cloudy"), ("Light Rain", ("rain",), "rain"), ("Rain", (), "rain"), ("Drizzle", (), "rain"),
    ("Light Rain Fog/Mist", ("rain", "mist"), "rain"), ("Freezing Rain", (), "rain"),
    ("Light Snow", ("snow",), "snow"), ("Snow Showers", (), "snow"), ("Sleet", (), "snow"), ("Flurries", (), "snow"),
    ("Thunderstorm", (), "thunderstorm"), ("Thunderstorm in Vicinity Light Rain", (), "thunderstorm"),
    ("Fog/Mist", (), "fog"), ("Haze", (), "other"), ("", (), "other"), (None, (), "other"),
])
def test_conditions_come_from_the_stations_words(text, present, condition):
    assert condition_of(text, [{"weather": w} for w in present]) == condition


def test_the_description_is_the_stations_own_words():
    assert parse_observation(obs(text="Haze"), "KNYC", NOW)["description"] == "Haze"
    assert parse_observation(obs(text=None), "KNYC", NOW)["description"] is None


# ---- the service: stations in order, a cache, honest failure ------------------------------------------------------------


class Fetcher:
    def __init__(self, by_station):
        self.by_station, self.calls = by_station, []

    def __call__(self, station):
        self.calls.append(station)
        v = self.by_station[station]
        if isinstance(v, Exception):
            raise v
        return v


class Clock:
    def __init__(self, t=NOW):
        self.t = t

    def __call__(self):
        return self.t


def service(by_station, clock=None):
    f, c = Fetcher(by_station), clock or Clock()
    return WeatherService(fetch=f, clock=c), f, c


def test_central_park_answers_first_and_alone():
    s, f, _ = service({"KNYC": obs(5.0), "KLGA": obs(9.0), "KJFK": obs(9.0)})
    assert s.reading()["station"] == "KNYC" and f.calls == ["KNYC"]


def test_the_next_station_answers_when_the_first_fails_or_has_no_temperature():
    s, f, _ = service({"KNYC": httpx.ConnectError("down"), "KLGA": obs(None), "KJFK": obs(6.1)})
    r = s.reading()
    assert f.calls == ["KNYC", "KLGA", "KJFK"] and r["station"] == "KJFK" and "JFK" in r["source"]


def test_a_station_with_an_old_reading_is_skipped():
    s, f, _ = service({"KNYC": obs(at="2026-11-13T16:00:00+00:00"), "KLGA": obs(7.0), "KJFK": obs(7.0)})
    assert s.reading()["station"] == "KLGA"


def test_when_no_station_answers_it_is_an_error_not_an_old_reading():
    s, _, _ = service({"KNYC": httpx.ReadTimeout("slow"), "KLGA": obs(None), "KJFK": ValueError("not json")})
    with pytest.raises(WeatherUnavailable):
        s.reading()


def test_polling_inside_the_cache_window_asks_the_provider_once():
    s, f, c = service({"KNYC": obs(5.0), "KLGA": obs(5.0), "KJFK": obs(5.0)})
    first = s.reading()
    c.t += CACHE_S - 1
    assert s.reading() == first and f.calls == ["KNYC"]
    c.t += 2
    s.reading()
    assert f.calls == ["KNYC", "KNYC"]


def test_the_cache_is_a_few_minutes():
    assert 60 <= CACHE_S <= 600


def test_a_failure_after_the_cache_expires_does_not_serve_the_old_reading():
    by = {"KNYC": obs(5.0), "KLGA": obs(5.0), "KJFK": obs(5.0)}
    s, f, c = service(by)
    s.reading()
    c.t += CACHE_S + 1
    by.update({k: httpx.ConnectError("down") for k in by})
    with pytest.raises(WeatherUnavailable):
        s.reading()


def test_a_cached_reading_is_not_served_once_its_observation_is_too_old():
    old = obs(at="2026-11-13T18:02:00+00:00")  # 58 minutes old at NOW: just inside the limit
    s, f, c = service({"KNYC": old, "KLGA": old, "KJFK": old})
    assert s.reading()["observed_at"] == "2026-11-13T18:02:00Z"
    c.t += 60  # inside the cache window, observation now 59 minutes old
    assert s.reading() and f.calls == ["KNYC"]
    c.t += 120  # still inside the cache window (180 s), but the observation is now over the hour
    with pytest.raises(WeatherUnavailable):
        s.reading()
    assert f.calls[1:] == ["KNYC", "KLGA", "KJFK"]  # it looked again rather than serve the old reading


def test_a_failed_lookup_is_remembered_briefly_so_polling_doesnt_hammer_the_provider():
    s, f, c = service({"KNYC": httpx.ConnectError("down"), "KLGA": httpx.ConnectError("down"),
                       "KJFK": httpx.ConnectError("down")})
    for _ in range(3):
        with pytest.raises(WeatherUnavailable):
            s.reading()
    assert len(f.calls) == 3  # one pass over the three stations, not nine calls
    c.t += 61
    with pytest.raises(WeatherUnavailable):
        s.reading()
    assert len(f.calls) == 6
