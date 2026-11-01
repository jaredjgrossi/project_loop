"""Names for catalog corridors (decision 014). They become stretch names in the UI ("Mile 1 · East River Greenway"),
so a street or a bridge that only crosses the corridor must not name it.

Order: the longest path-type way name that covers at least MIN_NAME_SHARE of the corridor; otherwise the OSM park
holding at least MIN_PARK_SHARE of it ("<park> waterfront"); otherwise "unnamed <kind> path".
"""

import re

MIN_NAME_SHARE = 0.20
MIN_PARK_SHARE = 0.30
MIN_BRIDGE_SHARE = 0.50  # a bridge name only names a corridor that is mostly that bridge
PATH_WORDS = re.compile(
    r"\b(greenway|esplanade|promenade|boardwalk|walk|path|pathway|footpath|trail|bikeway|mile|pier|loop|bike path)\b",
    re.I,
)
DRIVE = re.compile(r"\bdrive\b", re.I)
BRIDGE = re.compile(r"\bbridge\b", re.I)
KIND_WORD = {"waterfront": "waterfront", "greenway": "greenway", "park_drive": "drives"}


def _is_path_name(name: str, kind: str) -> bool:
    # "Harlem River Drive Greenway" is a greenway; "Harlem River Drive" is a road; "West Drive" in a park is a drive.
    return bool(PATH_WORDS.search(name)) or (kind == "park_drive" and bool(DRIVE.search(name)))


def choose_name(way_names: list[tuple[str, float]], parks: list[tuple[str, float]], kind: str,
                total_m: float) -> tuple[str, str]:
    """way_names: (name, meters of the corridor on ways with that name); parks: (park name, meters of the corridor
    inside it). Returns (name, source) where source is "way", "park" or "none"."""
    eligible = []
    for name, meters in way_names:
        share = meters / total_m if total_m else 0
        if not _is_path_name(name, kind) or share < MIN_NAME_SHARE:
            continue
        if BRIDGE.search(name) and share < MIN_BRIDGE_SHARE:
            continue
        eligible.append((meters, name))
    if eligible:
        return max(eligible)[1], "way"
    best_park = max(parks, key=lambda p: p[1], default=None)
    if best_park and total_m and best_park[1] / total_m >= MIN_PARK_SHARE:
        word = KIND_WORD.get(kind, "path")
        # "Hunter's Point South Waterfront Park", not "... Waterfront Park waterfront".
        return (best_park[0] if word.lower() in best_park[0].lower() else f"{best_park[0]} {word}"), "park"
    return f"unnamed {kind.replace('_', ' ')} path", "none"
