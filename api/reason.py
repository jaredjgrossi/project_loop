"""One line on why a route fits, from its measured fields (UI review, "park-aware reason").

Code writes it from numbers the route already has (shares, lights, climb); the LLM never does. Parts, in this order,
at most three: how much of it is park (naming the park) or waterfront, its lights, and whether it's flat or hilly.
A route that is mostly park is not called a waterfront route because a sliver of it is by the water.
"""

from api.copy import render

PARK_NAMED_PCT = 40.0  # this much park and one park carries it: "82% through Central Park"
PARK_PCT = 20.0  # this much, otherwise: "35% in parks"
WATER_PCT = 20.0
FLAT_M_PER_MILE = 8.0
HILLY_M_PER_MILE = 25.0
MAX_PARTS = 3
SOURCE = "this route's measured shares, lights and climb (api/reason.py)"


def route_reason(*, waterfront_pct: float | None, park_pct: float | None, park_name: str | None, lights: int | None,
                 climb_m: float | None, miles: float) -> dict:
    """{text, parts: [{key, text, status}], status, source}; text is None when nothing about the route stands out."""
    parts: list[dict] = []

    def add(key: str, text: str, status: str = "measured") -> None:
        parts.append({"key": key, "text": text, "status": status})

    if park_pct is not None and park_pct >= PARK_NAMED_PCT and park_name:
        add("park", render("reason.park", pct=round(park_pct), name=park_name))
    elif park_pct is not None and park_pct >= PARK_PCT:
        add("park", render("reason.parks", pct=round(park_pct)))
    if waterfront_pct is not None and waterfront_pct >= WATER_PCT:
        add("water", render("reason.water", pct=round(waterfront_pct)))
    if lights is not None:
        add("lights", render("reason.no_lights" if lights == 0 else "reason.light" if lights == 1 else "reason.lights",
                             n=lights))
    if climb_m is not None and miles > 0:
        per_mile = climb_m / miles
        if per_mile < FLAT_M_PER_MILE:
            add("flat", render("reason.flat"), "estimate")
        elif per_mile > HILLY_M_PER_MILE:
            add("hilly", render("reason.hilly", m=round(climb_m)), "estimate")
    parts = parts[:MAX_PARTS]
    text = ", ".join(p["text"] for p in parts)
    return {"text": (text[0].upper() + text[1:]) if text else None, "parts": parts,
            "status": "estimate" if any(p["status"] == "estimate" for p in parts) else "measured", "source": SOURCE}
