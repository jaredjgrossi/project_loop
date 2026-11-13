"""Route names from what a route is (phone test, 2026-11-11; decision 044).

A generator's label says how a route was made ("loop on Riverside Walk, heading 19 degrees" is the anchored-loop
job), not what came out: that job can return a route that is mostly retraced. The name shown to the runner (the
route card, its eyebrow, the route file, saved routes) starts from the kind measured on the geometry, and keeps only
the place from the label: "Out-and-back on Riverside Walk".
"""

import re

from api.copy import render

_PLACE = re.compile(r"\b(on|through|along|with a lap of)\s+(.+?)(?:\s+and beyond)?(?:,|\s+to the end|\s+from the start|$)")


def display_name(kind: str, label: str) -> str:
    """'Out-and-back on Riverside Walk', 'Loop through Central Park', 'Loop on the street grid', 'One way'."""
    word = render(f"name.kind.{kind}")
    if label.startswith("rectangle"):  # a grid rectangle: corners on the street grid
        return render("name.on_the_grid", kind=word)
    m = _PLACE.search(label)
    if not m:
        return render("name.shortest", kind=word) if label.startswith("the shortest way") else word
    return render("name.with_place", kind=word, prep=m.group(1), place=m.group(2).strip())


MAIN_SHARE = 0.4  # a stretch that carries this much of the route names it


def main_stretch(stretches: list[dict]) -> dict | None:
    """The stretch (by name and kind) the route runs most, its pieces added up: {name, kind, length_m, share}. The
    stretches are the route file's stretch properties (api/segments.py)."""
    totals: dict[tuple[str, str], float] = {}
    for s in stretches:
        key = (s.get("name") or "", s.get("kind") or "")
        totals[key] = totals.get(key, 0.0) + s.get("length_m", 0)
    whole = sum(totals.values())
    if not whole:
        return None
    (name, kind), length = max(totals.items(), key=lambda kv: kv[1])
    return {"name": name, "kind": kind, "length_m": length, "share": length / whole}


def _has_a_real_name(name: str) -> bool:
    """Not "unnamed path", "waterfront path", or "waterfront path near E 23rd St": those say nothing."""
    return not name.startswith(("unnamed", "waterfront path"))


def route_name(kind: str, label: str, stretches: list[dict]) -> str:
    """The name from what the route measured: "Out-and-back on East River Esplanade" (UI review: the generator's
    "on East River Esplanade and beyond" and "on the waterfront" were weak). The main stretch names the route when it
    carries at least MAIN_SHARE of it and has a real name; a park is run through. Otherwise the generator's label
    decides, as `display_name`: "Loop on the street grid" when no street stands out."""
    main = main_stretch(stretches)
    if main is None or main["share"] < MAIN_SHARE or not _has_a_real_name(main["name"]):
        return display_name(kind, label)
    prep = "through" if main["kind"] == "park" else "on"
    return render("name.with_place", kind=render(f"name.kind.{kind}"), prep=prep, place=main["name"])
