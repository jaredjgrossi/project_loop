"""No-go zones: places no runner should be routed through (decision 010).

A hard rule in two places: GraphHopper gets each zone as an area with priority 0 in the per-request custom model
(decision 009 tested that this routes around it), and any route that still touches a zone is rejected. Zones live in
routing/no_go_zones.geojson with their source; default zones apply to every request, the rest when a runner names one.
"""

import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from api.geometry import line_touches_polygon

ZONES_FILE = Path(__file__).resolve().parents[1] / "routing" / "no_go_zones.geojson"
_ID = re.compile(r"^[a-z_][a-z0-9_]*$")  # becomes part of a GraphHopper expression: in_<id>


@dataclass(frozen=True)
class NoGoZone:
    id: str
    name: str
    aliases: tuple[str, ...]
    default: bool
    reason: str
    source: str
    rings: list  # GeoJSON polygon rings, [lon, lat]

    def __post_init__(self):
        if not _ID.match(self.id):
            raise ValueError(f"no-go zone id {self.id!r} must be lowercase letters, digits and underscores")

    def names(self) -> set[str]:
        return {self.name.lower(), *(a.lower() for a in self.aliases)}


@cache
def load_zones(path: Path = ZONES_FILE) -> tuple[NoGoZone, ...]:
    features = json.loads(path.read_text())["features"]
    return tuple(
        NoGoZone(
            id=f["id"], name=f["properties"]["name"], aliases=tuple(f["properties"].get("aliases", ())),
            default=bool(f["properties"].get("default")), reason=f["properties"]["reason"],
            source=f["properties"]["source"], rings=f["geometry"]["coordinates"],
        )
        for f in features
    )


def resolve(names: list[str], zones=None) -> tuple[list[NoGoZone], list[str]]:
    """The zones for a request: every default zone plus the named ones, and the names that matched nothing."""
    zones = load_zones() if zones is None else zones
    found = [z for z in zones if z.default]
    unknown = []
    for name in names:
        match = next((z for z in zones if name.strip().lower() in z.names()), None)
        if match is None:
            unknown.append(name)
        elif match not in found:
            found.append(match)
    return found, unknown


def custom_model(zones: list[NoGoZone]) -> dict | None:
    """A GraphHopper per-request custom model that makes each zone impassable, or None when there are none."""
    if not zones:
        return None
    return {
        "priority": [{"if": f"in_{z.id}", "multiply_by": "0"} for z in zones],
        "areas": {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "id": z.id, "properties": {}, "geometry": {"type": "Polygon", "coordinates": z.rings}}
                for z in zones
            ],
        },
    }


def touched(coords: list[list[float]], zones: list[NoGoZone]) -> list[NoGoZone]:
    return [z for z in zones if line_touches_polygon(coords, z.rings)]
