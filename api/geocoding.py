"""Address geocoding via the NYC Planning Labs GeoSearch API.

The service answers almost any text with something, and its own confidence
score is not informative (valid addresses come back as 0.8 "fallback"). So this
module verifies the answer instead of trusting it: the house number and street
must match what was asked, a number+street that exists in several boroughs must
be disambiguated by the caller, and place names are refused. When it can't be
sure, it raises an error that says why. It never picks quietly.
"""

import re
from dataclasses import dataclass

import httpx

GEOSEARCH_URL = "https://geosearch.planninglabs.nyc/v2/search"
CANDIDATES_REQUESTED = 10  # enough to see the same address in other boroughs

# Rough NYC bounding box, as a sanity check on what the service returns.
NYC_LAT_RANGE = (40.45, 40.95)
NYC_LON_RANGE = (-74.30, -73.65)


class GeocodeError(Exception):
    """Base class: the address could not be turned into a trustworthy point."""


class GeocodeUnavailableError(GeocodeError):
    """The geocoding service could not be reached or returned an error."""


class NoMatchError(GeocodeError):
    """The service returned nothing."""


class NotAnAddressError(GeocodeError):
    """The query has no house number and street, e.g. a place name."""


class LowConfidenceError(GeocodeError):
    """The service answered, but not with the address that was asked for."""

    def __init__(self, message: str, nearest: str | None = None):
        super().__init__(message)
        self.nearest = nearest


class AmbiguousAddressError(GeocodeError):
    """The same house number and street exists in more than one borough."""

    def __init__(self, message: str, boroughs: list[str]):
        super().__init__(message)
        self.boroughs = boroughs


@dataclass(frozen=True)
class GeocodeResult:
    lat: float
    lon: float
    label: str
    borough: str
    postalcode: str | None
    housenumber: str
    street: str
    source: str
    source_id: str
    match_type: str | None
    confidence: float | None


@dataclass(frozen=True)
class AddressQuery:
    raw: str
    housenumber: str | None
    street: str | None
    borough: str | None
    postalcode: str | None


# --- parsing ----------------------------------------------------------------

_STREET_WORDS = {
    "AVE": "AVENUE",
    "ST": "STREET",
    "RD": "ROAD",
    "BLVD": "BOULEVARD",
    "PL": "PLACE",
    "DR": "DRIVE",
    "PKWY": "PARKWAY",
    "LN": "LANE",
    "CT": "COURT",
    "E": "EAST",
    "W": "WEST",
    "N": "NORTH",
    "S": "SOUTH",
}
_ORDINAL = re.compile(r"^(\d+)(?:ST|ND|RD|TH)$")

# Longest phrases first so "STATEN ISLAND" wins over anything shorter.
_BOROUGHS = [
    ("STATEN ISLAND", "Staten Island"),
    ("THE BRONX", "Bronx"),
    ("BRONX", "Bronx"),
    ("BROOKLYN", "Brooklyn"),
    ("QUEENS", "Queens"),
    ("MANHATTAN", "Manhattan"),
    ("NEW YORK", "Manhattan"),  # GeoSearch labels Manhattan addresses "New York, NY"
]
_HOUSENUMBER = re.compile(r"^(\d+(?:-\d+)?[A-Z]?)\s+(.+)$")
_TRAILING_ZIP = re.compile(r"\s+(\d{5})(?:-\d{4})?$")
_TRAILING_STATE = re.compile(r"\s+(?:NY|NYC)$")


def normalize_street(street: str) -> str:
    """Put a typed street name in GeoSearch's form: '5th Ave' -> '5 AVENUE'."""
    words = []
    for word in street.upper().replace(".", " ").split():
        m = _ORDINAL.match(word)
        words.append(m.group(1) if m else _STREET_WORDS.get(word, word))
    return " ".join(words)


def _find_borough(text: str) -> str | None:
    for phrase, name in _BOROUGHS:
        if re.search(rf"\b{phrase}\b", text):
            return name
    return None


def parse_address_query(query: str) -> AddressQuery:
    text = " ".join(query.upper().replace(".", " ").split())
    head, *rest = [part.strip() for part in text.split(",")]
    borough = postalcode = None

    if rest:
        tail = " ".join(rest)
        m = re.search(r"\b(\d{5})\b", tail)
        postalcode = m.group(1) if m else None
        borough = _find_borough(tail)
    else:
        # "350 5th Ave Brooklyn 11215": peel zip, state, borough off the end.
        # A borough word inside the street name ("100 Brooklyn Ave") is left alone.
        m = _TRAILING_ZIP.search(head)
        if m:
            postalcode, head = m.group(1), head[: m.start()]
        head = _TRAILING_STATE.sub("", head)
        for phrase, name in _BOROUGHS:
            if head.endswith(" " + phrase):
                borough, head = name, head[: -len(phrase) - 1]
                break
        head = _TRAILING_STATE.sub("", head)

    m = _HOUSENUMBER.match(head)
    if not m:
        return AddressQuery(query, None, None, borough, postalcode)
    return AddressQuery(query, m.group(1), normalize_street(m.group(2)), borough, postalcode)


# --- resolving ----------------------------------------------------------------


def _to_result(feature: dict) -> GeocodeResult:
    p = feature["properties"]
    lon, lat = feature["geometry"]["coordinates"][:2]
    return GeocodeResult(
        lat=lat,
        lon=lon,
        label=p["label"],
        borough=p["borough"],
        postalcode=p.get("postalcode"),
        housenumber=p["housenumber"],
        street=p["street"],
        source=p["source"],
        source_id=str(p["source_id"]),
        match_type=p.get("match_type"),
        confidence=p.get("confidence"),
    )


def _in_nyc(feature: dict) -> bool:
    lon, lat = feature["geometry"]["coordinates"][:2]
    return NYC_LAT_RANGE[0] <= lat <= NYC_LAT_RANGE[1] and NYC_LON_RANGE[0] <= lon <= NYC_LON_RANGE[1]


def _matches(feature: dict, q: AddressQuery) -> bool:
    p = feature["properties"]
    return (
        str(p.get("housenumber", "")).upper() == q.housenumber
        and normalize_street(str(p.get("street", ""))) == q.street
    )


def resolve(query: str, response: dict) -> GeocodeResult:
    """Pick the one address in a GeoSearch response that the query asked for, or raise."""
    features = response.get("features") or []
    if not features:
        raise NoMatchError(f"No result for {query!r}.")

    q = parse_address_query(query)
    if q.housenumber is None or not q.street:
        raise NotAnAddressError(
            f"{query!r} is not a street address. Give a house number and street, "
            "e.g. '11 Madison Ave, Manhattan'."
        )

    nearest = features[0]["properties"]["label"]
    matches = [f for f in features if _matches(f, q)]
    if not matches:
        raise LowConfidenceError(
            f"No exact match for {query!r}: house number {q.housenumber} on {q.street} "
            f"was not found. The closest the service offered was {nearest}.",
            nearest=nearest,
        )

    matches = [f for f in matches if _in_nyc(f)]
    if not matches:
        raise LowConfidenceError(f"{query!r} resolved to a point outside NYC.", nearest=nearest)

    found_boroughs = sorted({f["properties"]["borough"] for f in matches})
    if q.postalcode:
        matches = [f for f in matches if f["properties"].get("postalcode") == q.postalcode]
    if q.borough:
        matches = [f for f in matches if f["properties"]["borough"] == q.borough]
    if not matches:
        raise LowConfidenceError(
            f"{query!r} was found only in {', '.join(found_boroughs)}, "
            "which doesn't match the borough or zip you gave.",
            nearest=nearest,
        )

    boroughs = sorted({f["properties"]["borough"] for f in matches})
    if len(boroughs) > 1:
        raise AmbiguousAddressError(
            f"{q.housenumber} {q.street.title()} exists in {' and '.join(boroughs)}. "
            "Add a borough or zip code.",
            boroughs=boroughs,
        )
    return _to_result(matches[0])


def geocode(query: str, client: httpx.Client | None = None) -> GeocodeResult:
    owns_client = client is None
    client = client or httpx.Client(timeout=10)
    try:
        resp = client.get(GEOSEARCH_URL, params={"text": query, "size": CANDIDATES_REQUESTED})
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise GeocodeUnavailableError(f"GeoSearch request failed: {exc}") from exc
    finally:
        if owns_client:
            client.close()
    return resolve(query, payload)
