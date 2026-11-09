"""The eval contexts' past routes, stored in saved_routes so past-route cases (H01–H05) find their lines (step 11).

    uv run python -m evals.past_routes      (with make up; the evals call seed() themselves)

evals/parse/recent_routes.json lists three routes by id, name and distance, as the phone would. Their lines are
routed by GraphHopper through public waypoints near the Kips Bay Library stand-in, never a real run, and stored as
`fixture` builds under those ids. Seeding is idempotent (same ids, upserted).
- rt_a "East River esplanade out-and-back": east to the esplanade, north past the E 34th St ferry landing, back.
- rt_c "Gramercy street rectangle": a street loop through Gramercy, nowhere near a ferry.
- rt_b "Stuyvesant Cove both ways": south along the esplanade to Stuyvesant Cove, back the same way.
"""

from functools import cache

from api.routing import request_route

KIPS = (40.7438, -73.9799)  # Kips Bay Library, the contexts' public stand-in start
WAYPOINTS = {
    # Tuned so each line is about the distance recent_routes.json lists (3.0, 4.0 and 3.1 mi).
    "rt_a": [KIPS, (40.7385, -73.9740), (40.7439, -73.9712), (40.7486, -73.9690)],  # out; back the same way
    "rt_b": [KIPS, (40.7380, -73.9745), (40.7255, -73.9725)],  # out; back the same way
    "rt_c": [KIPS, (40.7330, -73.9890), (40.7385, -73.9960), (40.7485, -73.9875), KIPS],  # round
}
OUT_AND_BACK = {"rt_a", "rt_b"}
NAMES = {"rt_a": "East River esplanade out-and-back", "rt_b": "Stuyvesant Cove both ways",
         "rt_c": "Gramercy street rectangle"}


def final_for(route_id: str) -> dict:
    pts = WAYPOINTS[route_id]
    if route_id in OUT_AND_BACK:
        pts = [*pts, *reversed(pts[:-1])]
    r = request_route(pts)
    kind = "out_and_back" if route_id in OUT_AND_BACK else "loop"
    entry = {"id": route_id, "rank": 1, "kind": kind, "label": NAMES[route_id], "score": None,
             "distance": {"value": round(r.distance_m / 1609.344, 2), "unit": "mi", "status": "measured"},
             "geometry": {"type": "LineString", "coordinates": [c[:2] for c in r.coordinates]}}
    return {"event": "final", "v": 1, "route_id": route_id, "routes": [entry], "route": None, "notes": [],
            "fixture": "evals/past_routes.py"}


@cache
def seed() -> dict[str, float]:
    """Store the three fixture routes; returns each one's distance in miles."""
    from api.saved_routes import PgRouteStore
    store = PgRouteStore()
    out = {}
    for rid in WAYPOINTS:
        final = final_for(rid)
        store.save(rid, {"v": 1, "kind": "fixture", "parse_id": None, "client": {}}, {"fixture": True}, final)
        out[rid] = final["routes"][0]["distance"]["value"]
    return out


if __name__ == "__main__":
    for rid, miles in seed().items():
        print(rid, NAMES[rid], f"{miles} mi")
