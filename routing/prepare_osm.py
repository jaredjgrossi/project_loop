"""Build routing/data/nyc.osm.pbf: the New York State OSM extract clipped to the five boroughs.

    python -m routing.prepare_osm [--refresh]

Needs `osmium` (brew install osmium-tool). Everything it writes is under
routing/data/, which is gitignored and can be rebuilt at any time.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import httpx

DATA_DIR = Path(__file__).parent / "data"
STATE_PBF_URL = "https://download.geofabrik.de/north-america/us/new-york-latest.osm.pbf"
# NYC DCP "Borough Boundaries (water areas included)". The land-only version
# (gthc-hcne) would cut off piers, esplanades and greenway sections over water.
BOUNDARY_URL = "https://data.cityofnewyork.us/resource/wh2p-dxnf.geojson"
STATE_PBF = DATA_DIR / "new-york-latest.osm.pbf"
BOUNDARY = DATA_DIR / "nyc_boundary.geojson"
NYC_PBF = DATA_DIR / "nyc.osm.pbf"


def merge_boroughs(feature_collection: dict) -> dict:
    """Combine the five borough features into one MultiPolygon (osmium wants a single shape)."""
    features = feature_collection["features"]
    if len(features) != 5:
        raise ValueError(f"expected five borough features, got {len(features)}")
    polygons: list = []
    for feature in features:
        geometry = feature["geometry"]
        if geometry["type"] == "MultiPolygon":
            polygons.extend(geometry["coordinates"])
        elif geometry["type"] == "Polygon":
            polygons.append(geometry["coordinates"])
        else:
            raise ValueError(f"unexpected boundary geometry {geometry['type']}")
    return {"type": "MultiPolygon", "coordinates": polygons}


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=60) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        done = 0
        with tmp.open("wb") as fh:
            for chunk in resp.iter_bytes(1 << 20):
                fh.write(chunk)
                done += len(chunk)
                if total:
                    print(f"\r  {done / 1e6:6.0f} / {total / 1e6:.0f} MB", end="", flush=True)
    print()
    tmp.rename(dest)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true", help="re-download even if files already exist")
    args = ap.parse_args(argv)

    if shutil.which("osmium") is None:
        print("osmium not found. Install it with:  brew install osmium-tool", file=sys.stderr)
        return 1

    if args.refresh or not STATE_PBF.exists():
        print(f"Downloading New York State extract from Geofabrik -> {STATE_PBF}")
        download(STATE_PBF_URL, STATE_PBF)

    print("Fetching borough boundaries ...")
    resp = httpx.get(BOUNDARY_URL, params={"$limit": 10}, timeout=60)
    resp.raise_for_status()
    BOUNDARY.write_text(json.dumps(merge_boroughs(resp.json())))

    print(f"Clipping to the five boroughs -> {NYC_PBF}")
    subprocess.run(
        ["osmium", "extract", "--overwrite", "-p", str(BOUNDARY), "-o", str(NYC_PBF), str(STATE_PBF)],
        check=True,
    )
    info = subprocess.run(["osmium", "fileinfo", "-e", str(NYC_PBF)], capture_output=True, text=True, check=True)
    print(info.stdout)
    print(f"Done: {NYC_PBF} ({NYC_PBF.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
