"""Every string the runner sees, by key (decision 025). The UI chat owns the wording; code owns the keys.

Data carries keys, never these words: a field's source is "said", "preset", "default" or "usual", and `render`
turns it into "you said", "Training preset", "default" or "your usual". Claude never writes any of this text; it
only supplies place and route names that fill the placeholders.

Phase 3, step 3 holds the source words and the request list's strings. Step 4 adds chips, questions, can't-do lines
and notes.
"""

TEMPLATES: dict[str, str] = {
    # Where a field's value came from (contract: chip source)
    "source.said": "you said",
    "source.preset": "{mode} preset",
    "source.default": "default",
    "source.usual": "your usual",

    # The request list in the route file (decision 020): titles
    "request.title.start": "Start",
    "request.title.end": "End",
    "request.title.via": "Through",
    "request.title.distance": "Distance",
    "request.title.tolerance": "Within",
    "request.title.shape": "Shape",
    "request.title.mode": "Mode",
    "request.title.lights": "Lights",
    "request.title.crowds": "Crowds",
    "request.title.scenery": "Scenery",
    "request.title.surface": "Surface",
    "request.title.turns": "Turns",
    "request.title.familiar": "Matches routes you run",
    "request.title.hills": "Hills",
    "request.title.avoid": "Avoid",
    "request.title.amenity": "Stop",
    "request.title.start_time": "Start time",
    "request.title.start_date": "Day",
    "request.title.reuse": "Route",
    "request.title.reverse": "Direction",

    # The request list: values
    "request.start.my_location": "your location",
    "request.place": "{name}, {borough}",
    "request.saved_place": "{name}",
    "request.distance": "{miles} mi",
    "request.distance.shortest": "the shortest way",
    "request.distance.reused": "the route's",
    "request.tolerance": "{pct}%",
    "request.mode.unset": "not set",
    "request.avoid.along": "along {name}",
    "request.amenity": "{kind} near mile {mile} (within {within} mi)",
    "request.start_time": "{time} (hour {hour}; sets the crowd band)",
    "request.start_time.unset": "not set, so crowds are not scored",
    "request.start_date": "{day}",
    "request.reuse": "{route}",
    "request.reverse": "other direction",

    # Preference values
    "pref.lights.waits": "waits for the light",
    "pref.lights.zigzags": "zig-zags with the lights",
    "pref.crowds.avoid": "avoid",
    "pref.crowds.some": "some",
    "pref.crowds.dont_mind": "don't mind",
    "pref.scenery.park_or_water": "park or water",
    "pref.scenery.some": "some",
    "pref.scenery.dont_mind": "don't mind",
    "pref.surface.paths": "paths",
    "pref.surface.any": "any",
    "pref.turns.fewer": "fewer",
    "pref.turns.dont_mind": "don't mind",
    "pref.familiar.favor": "favor routes you run",
    "pref.familiar.some": "some",
    "pref.familiar.new": "new ground",
    "pref.hills.avoid": "flat",
    "pref.hills.dont_mind": "don't mind",
}


def render(key: str, **values) -> str:
    """The template for `key`, filled in. A missing key is a bug, so it raises."""
    return TEMPLATES[key].format(**values)


def source_word(source: str, mode: str | None = None) -> str:
    """'said' -> 'you said'; 'preset' -> 'Training preset'."""
    return render(f"source.{source}", mode=(mode or "").capitalize())
