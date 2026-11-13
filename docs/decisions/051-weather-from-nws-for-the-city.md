# 051 · Weather for the header line, from the National Weather Service

*2026-11-13 · branch `weather`*

## Decision
The server gives the app one city-level reading at `GET /v1/weather/nyc` (contract: `docs/phase3/parse-contract-v1.md`).
The iPhone app has no weather source of its own: WeatherKit needs the paid developer program (decision 024), and a
direct call to a weather service would send the phone's coordinates to a third party.

## Choices worth knowing
- **Provider: National Weather Service observations (api.weather.gov), not Open-Meteo.** NWS gives what a station
  measured, with the time it measured it; Open-Meteo's "current" is a model value on a 15-minute grid, so its time would
  not be an observation's. NWS needs no key; the client names itself `LoopRunBuilder/1.0` and gives no contact details.
- **Stations in order: KNYC (Central Park), KLGA, KJFK.** The first that has a temperature and an observation under an
  hour old answers. KNYC reports whole degrees Celsius, so its Fahrenheit value moves in steps of about 2 degrees.
- **The city, not the phone.** No latitude or longitude comes in or goes out, so nothing about the runner's location
  reaches NWS and there is nothing to log. Weather at the runner's own spot is a different feature (not built).
- **Honest time.** `observed_at` is the station's timestamp in UTC. A reading in the future by over 5 minutes or older
  than an hour is no reading.
- **Cache 5 minutes, in memory, one lock.** Polling inside the window never reaches NWS. A failed pass over all three
  stations is remembered for 60 seconds so a phone polling during an outage doesn't hammer the provider. A cached reading
  is dropped as soon as its observation passes the hour, whatever the cache window says.
- **Failure is a 503, never an old reading.** After the cache expires nothing stale is served "just in case".
- **Conditions:** `clear`, `partly_cloudy`, `cloudy`, `fog`, `rain`, `snow`, `thunderstorm`, `other`, from the station's
  wording (precipitation first, so "Light Rain Fog/Mist" is rain; freezing rain is rain, sleet and ice pellets snow).
  The wording itself travels as `description`.
- **Source and trust:** every reading carries `source` ("National Weather Service, KNYC Central Park") and
  `status: "measured"`, like the route summary's numbers.

## Not done
- Weather at the run's location, a forecast, wind, or a feels-like temperature.
- A shared cache across server processes (the server is one process).
- NWS terms: the API is public and free; if it ever asks for a contact address we would add a generic project one, not a
  personal one.
