"""Distance conversions. GraphHopper speaks meters; runners speak miles."""

METERS_PER_MILE = 1609.344


def miles_to_meters(miles: float) -> float:
    if miles < 0:
        raise ValueError("distance must be non-negative")
    return miles * METERS_PER_MILE


def meters_to_miles(meters: float) -> float:
    return meters / METERS_PER_MILE


def percent_off(requested: float, actual: float) -> float:
    """Signed miss as a percent of the request: +10 means 10% too long."""
    if requested <= 0:
        raise ValueError("requested distance must be positive")
    return (actual - requested) / requested * 100
