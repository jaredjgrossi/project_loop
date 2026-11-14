"""Export a simplified outline of the five boroughs for the iOS app to bundle (decision 056).

    python -m etl.export_coverage [path/to/nyc_boundary.geojson]

The phone checks its own location against this outline, so the coordinates never go to the server. The source is the
polygon the routing extract was clipped to (`python -m routing.prepare_osm` writes routing/data/nyc_boundary.geojson:
NYC Planning "Borough Boundaries (water areas included)"), so the outline is exactly the area Loop routes in, water
edges included.

The outline is grown by SIMPLIFY_DEG and then simplified by the same amount, so it always contains the whole of the
source polygon: a point Loop covers is never outside it. It can run up to about twice SIMPLIFY_DEG (about 100 m)
beyond the true edge, over water or at a borough line, so a point just across the line can read as inside. The server
still decides each request by the place the runner names.
"""

import json
import sys
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.geometry.polygon import orient

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "routing" / "data" / "nyc_boundary.geojson"
OUT = ROOT / "docs" / "phase3" / "coverage-nyc.geojson"
SIMPLIFY_DEG = 0.0006  # about 65 m north-south and 50 m east-west at NYC's latitude
DECIMALS = 5  # about 1 m
NAME = "New York City"


def outline(geometry, tolerance: float = SIMPLIFY_DEG):
    """The simplified outline of `geometry`: it contains all of it, as MultiPolygon with coordinates rounded to
    DECIMALS and rings wound as RFC 7946 asks (outer counter-clockwise)."""
    grown = geometry.buffer(tolerance).simplify(tolerance, preserve_topology=True)
    polys = list(grown.geoms) if isinstance(grown, MultiPolygon) else [grown]
    return MultiPolygon([orient(p, sign=1.0) for p in polys if isinstance(p, Polygon)])


def feature_collection(geometry) -> dict:
    def rounded(coords):
        return [[round(x, DECIMALS), round(y, DECIMALS)] for x, y in coords]

    polys = []
    for p in geometry.geoms:
        polys.append([rounded(p.exterior.coords)] + [rounded(i.coords) for i in p.interiors])
    return {"type": "FeatureCollection", "features": [{
        "type": "Feature",
        "properties": {"name": NAME, "covers": "the five boroughs",
                       "source": "NYC DCP Borough Boundaries (water areas included), simplified",
                       "simplified_deg": SIMPLIFY_DEG},
        "geometry": {"type": "MultiPolygon", "coordinates": polys}}]}


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else SOURCE
    if not path.exists():
        sys.exit(f"{path} not found. Build it first:  python -m routing.prepare_osm")
    source = shape(json.loads(path.read_text()))
    collection = feature_collection(outline(source))
    out = shape(collection["features"][0]["geometry"])
    missed = source.difference(out).area / source.area
    if missed > 1e-6:  # rounding to DECIMALS may shave a sliver; anything more is a bug
        sys.exit(f"the outline misses {missed:.2e} of the source area")
    OUT.write_text(json.dumps(collection, separators=(",", ":")) + "\n")
    print(f"{OUT.relative_to(ROOT)}: {OUT.stat().st_size} bytes, "
          f"{sum(len(p.exterior.coords) for p in out.geoms)} outer points, {len(out.geoms)} polygons")


if __name__ == "__main__":
    main()
