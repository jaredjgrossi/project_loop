"""Every string the runner sees, by key (decision 025). The UI chat owns the wording; code owns the keys.

Data carries keys, never these words: a field's source is "said", "preset", "default" or "usual", and `render`
turns it into "you said", "Training preset", "default" or "your usual". Claude never writes any of this text; it
only supplies place and route names that fill the placeholders.

Sections: source words, the route file's request list (decision 020), preference values, and the parsed event's chips,
questions, options, can't-do lines, notes and errors (Phase 3 contract).
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

    # Chips in the parsed event (contract): short and plain
    "chip.asked": "{words}",  # a chip the question is about, before it has a value: the runner's own words
    "chip.start.my_location": "From your location",
    "chip.start.place": "From {name}, {borough}",
    "chip.start.saved": "From {name}",
    "chip.end.place": "End: {name}, {borough}",
    "chip.end.saved": "End: {name}",
    "chip.via.place": "Through {name}, {borough}",
    "chip.via.lap": "A lap of {name}, {borough}",
    "chip.distance": "{miles} mi",
    "chip.distance.range": "{low}–{high} mi",
    "chip.distance.shortest": "Shortest way",
    "chip.distance.reused": "Same distance as before",
    "chip.distance.lap": "The lap and the way there",
    "chip.time.now": "Now",
    "chip.time.today": "Today, {time}",
    "chip.time.today_now": "Today, now",
    "chip.time.day": "{day}, {time}",
    "chip.shape.loop": "Loop",
    "chip.shape.out_and_back": "Out and back",
    "chip.shape.any": "Loop or out and back",
    "chip.mode.training": "Training",
    "chip.mode.exploring": "Exploring",
    "chip.lights.waits": "Fewer lights",
    "chip.lights.zigzags": "Zig-zag with the lights",
    "chip.crowds.avoid": "Avoid crowds",
    "chip.crowds.some": "Some crowds are fine",
    "chip.crowds.dont_mind": "Crowds are fine",
    "chip.scenery.park_or_water": "Park or water",
    "chip.scenery.some": "Some scenery",
    "chip.scenery.dont_mind": "Any scenery",
    "chip.surface.paths": "Paths",
    "chip.surface.any": "Any surface",
    "chip.turns.fewer": "Fewer turns",
    "chip.turns.dont_mind": "Turns are fine",
    "chip.familiar.favor": "Routes you run",
    "chip.familiar.some": "Some familiar",
    "chip.familiar.new": "New ground",
    "chip.hills.avoid": "Flat",
    "chip.hills.dont_mind": "Hills are fine",
    "chip.avoid.along": "Not along {name}",
    "chip.avoid.area": "Avoid {name}",
    "chip.amenity.restroom": "Restroom near mile {mile}",
    "chip.amenity.water": "Water near mile {mile}",
    "chip.reuse": "{route}",
    "chip.reverse": "Other direction",

    # Questions (at most one per response)
    "question.distance.how_far": "How far?",
    "question.distance.minutes": "About how many miles is {minutes} minutes for you?",
    "question.distance.long_run": "How far today?",
    "question.distance.workout": "How far in total, warm-up and cool-down included?",
    "question.distance.typo": "Did you mean {miles} miles?",
    "question.distance.too_short": "Loop builds runs from 0.5 mi. Make it 0.5 mi?",
    "question.distance.too_long": "Loop builds runs up to 30 mi. Make it 30 mi?",
    "question.distance.longer": "How much longer?",
    "question.place.which": "Which {name}?",
    "question.place.which_park": "Which park?",
    "question.place.not_found": "Couldn't find {name}. What's the address?",
    "question.place.outside_nyc": "Loop only covers New York City. Where should it start?",
    "question.place.outside_nyc_end": "Loop only covers New York City. Where should it end?",
    "question.place.saved_unknown": "What's the {word}'s address?",
    "question.place.neighborhood": "Where in {name} should it start?",
    "question.start.where": "Where should it start?",
    "question.start.subjective": "Which spot should it start at?",
    "question.end.subjective": "Which spot should it finish at?",
    "question.reuse.which": "Which one?",
    "question.reuse.none": "No recent run matches that. Which one did you mean?",
    # From the engine (contract: the question event, from "engine")
    "question.engine.shortest": "The shortest way there is {miles} mi. Make it {miles} mi?",
    "question.engine.via_far": "Going through {name} takes at least {miles} mi. Make it {miles} mi?",
    "question.engine.lap_far": "A lap of {name} and the way there takes at least {miles} mi. Make it {miles} mi?",
    "option.miles": "{miles} mi",
    "option.plus_miles": "+{miles} mi",
    "option.place": "{name}, {borough}",
    "option.side": "{side} side ({at})",
    "option.borough": "{borough}",
    "option.route": "{weekday} · {name}",

    # Can't-do lines, by gap id (decision 025: evals match on gap, never on wording)
    "cant.G1.bridges": "Can't prefer bridges in general yet",
    "cant.G1.whole_way": "Can't stay on one street or path the whole way yet",
    "cant.G3": "Can't steer away from a place without avoiding it yet",
    "cant.G8": "Can't build routes around workout segments yet",
    "cant.G9": "Can't plan around street lighting or safety yet",
    "cant.bike_lanes": "Can't avoid bike lanes yet",
    # ... and what the engine can't build yet (step 5; each later step removes its line). Gap "later".
    "cant.later.reuse_route_id": "Can't rebuild a past route yet, so no routes were built",
    "cant.later.planned": "Can't plan the second run yet; only the first was built",
    "cant.avoid_unknown": "Can't avoid {name} yet: it isn't on the list of places Loop can avoid",
    "cant.lap_unrouted": "Can't run laps of {name} yet: it isn't in Loop's path data. These routes go to it",
    "cant.around_shape": "Can't run a lap of {name}: it isn't a loop. These routes go through it",

    # Notes: caveats that aren't refusals
    "note.crowds_estimated": "Crowds near schools and ferry landings are estimated for {time}; other stretches aren't scored",
    "note.fountains_seasonal": "Fountains may be off for the season",
    "note.distance_off.short": "No route came within {tolerance}% of {miles} mi. The closest is {actual} mi, {pct}% short.",
    "note.distance_off.long": "No route came within {tolerance}% of {miles} mi. The closest is {actual} mi, {pct}% long.",
    "note.no_route": "Couldn't build a route from this start. Try another start or distance.",
    "note.avoid_not_found": "Couldn't find {name} near the start, so these routes don't avoid it",

    # Errors
    "error.parse_failed": "Couldn't read that request. Try saying it another way.",
    "error.engine_unavailable": "Can't build routes right now. Try again in a minute.",
    "error.bad_request": "Something was wrong with that request.",
    "error.expired": "That question timed out, so the request is being sent again.",
}


def render(key: str, **values) -> str:
    """The template for `key`, filled in. A missing key is a bug, so it raises."""
    return TEMPLATES[key].format(**values)


def source_word(source: str, mode: str | None = None) -> str:
    """'said' -> 'you said'; 'preset' -> 'Training preset'."""
    return render(f"source.{source}", mode=(mode or "").capitalize())
