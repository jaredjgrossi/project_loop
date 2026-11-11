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
