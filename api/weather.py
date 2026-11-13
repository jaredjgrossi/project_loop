"""NYC weather for the app's line under the wordmark (decision 051).

A real station observation from the National Weather Service (api.weather.gov, no key): Central Park first, then
LaGuardia and JFK. The reading carries the station's own observation time, never the request's, and a source. The
endpoint is for the city, so the phone's location is never sent here or on to the provider. A reading is cached for a few
minutes; when no station gives a fresh one the caller gets an error, never an old reading dressed as fresh.
"""

import threading
import time
from datetime import datetime, timezone
from typing import Callable

import httpx

STATIONS = [("KNYC", "Central Park"), ("KLGA", "LaGuardia Airport"), ("KJFK", "JFK Airport")]
OBSERVATION_URL = "https://api.weather.gov/stations/{station}/observations/latest"
USER_AGENT = "LoopRunBuilder/1.0"  # NWS asks clients to say who they are; no contact details go in it
CACHE_S = 300  # polling inside this window never reaches the provider
FAILURE_S = 60  # a failed lookup is remembered this long, so a phone polling an outage doesn't hammer NWS
MAX_AGE_S = 3600  # an observation older than this is no reading (the phone hides anything over 30 minutes itself)
FUTURE_SLACK_S = 300  # a clock that far ahead of ours is still believed
SOURCE = "National Weather Service, {station} {place}"


class WeatherUnavailable(Exception):
    """No station gave a fresh reading."""


def _utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def condition_of(text: str | None, present: list | None = None) -> str:
    """One of clear, partly_cloudy, cloudy, fog, rain, snow, thunderstorm, other, from the station's own words.
    Precipitation wins over fog and sky ("Light Rain Fog/Mist" is rain); freezing rain counts as rain, sleet and ice
    pellets as snow. The station's wording itself travels along as `description`."""
    words = " ".join([(text or "")] + [str(p.get("weather") or "") for p in (present or []) if isinstance(p, dict)]).lower()
    if "thunder" in words:
        return "thunderstorm"
    if any(w in words for w in ("snow", "sleet", "flurr", "ice pellet", "blizzard")):
        return "snow"
    if any(w in words for w in ("rain", "drizzle", "shower")):
        return "rain"
    if "fog" in words or "mist" in words:
        return "fog"
    if "partly" in words:
        return "partly_cloudy"
    if "mostly cloudy" in words or "overcast" in words or "cloudy" in words:
        return "cloudy"
    if any(w in words for w in ("clear", "fair", "few clouds")):
        return "clear"
    return "other"


def parse_observation(data: dict, station: str, now: float) -> dict | None:
    """The reading in a station's latest observation, or None when it has no temperature or time we can believe."""
    props = data.get("properties") if isinstance(data, dict) else None
    if not isinstance(props, dict):
        return None
    temp = (props.get("temperature") or {}).get("value")
    stamp = props.get("timestamp")
    if not isinstance(temp, (int, float)) or not isinstance(stamp, str):
        return None
    try:
        observed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if observed.tzinfo is None:
        return None
    t = observed.timestamp()
    if now - t > MAX_AGE_S or t - now > FUTURE_SLACK_S:
        return None
    place = dict(STATIONS).get(station, "")
    text = props.get("textDescription")
    return {"temp_f": round(temp * 9 / 5 + 32), "condition": condition_of(text, props.get("presentWeather")),
            "description": text or None, "observed_at": _utc_iso(t), "station": station,
            "source": SOURCE.format(station=station, place=place).strip(), "status": "measured"}


def fetch_latest(station: str) -> dict:
    r = httpx.get(OBSERVATION_URL.format(station=station), headers={"User-Agent": USER_AGENT,
                                                                   "Accept": "application/geo+json"}, timeout=5)
    r.raise_for_status()
    return r.json()


class WeatherService:
    """The cached reading. `fetch(station)` returns a station's latest-observation JSON (fakes in tests)."""

    def __init__(self, fetch: Callable[[str], dict] | None = None, clock: Callable[[], float] = time.time):
        self.fetch, self.clock = fetch or fetch_latest, clock
        self._lock = threading.Lock()
        self._reading: dict | None = None
        self._read_at = 0.0
        self._failed_at: float | None = None

    def reading(self) -> dict:
        with self._lock:
            now = self.clock()
            if self._reading is not None and now - self._read_at < CACHE_S and \
                    now - _parse_utc(self._reading["observed_at"]) <= MAX_AGE_S:
                return dict(self._reading)
            if self._failed_at is not None and now - self._failed_at < FAILURE_S:
                raise WeatherUnavailable("no station gave a fresh reading a moment ago")
            for station, _ in STATIONS:
                try:
                    found = parse_observation(self.fetch(station), station, now)
                except (httpx.HTTPError, ValueError):
                    continue  # this station is down or sent something that isn't JSON; the next may answer
                if found:
                    self._reading, self._read_at, self._failed_at = found, now, None
                    return dict(found)
            self._reading, self._failed_at = None, now
            raise WeatherUnavailable("no station gave a fresh reading")


def _parse_utc(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
