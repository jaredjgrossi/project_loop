# Loop UI brief — v1
*Copy of the Project doc ui/brief-v1.md (Project Loop), saved 2026-11-01. The Project copy is the source of truth.*

*Status: **DEFERRED** (2026-10-31). UI work pauses until the engine returns real routes worth showing. The bar is "wow the user, feel like an ultra-premium app," so the UI will be approached deliberately (see "Approach when UI resumes"). Until then, the only UI-related work is keeping the engine's output rich (see "What the engine must provide," items 1, 2, 4 and 8). No thin UI slice after step 2; the HTML review page stays for route reviews.*
*Mockup v1 (superseded, kept for reference): https://claude.ai/artifact/SdHK1UPKtB9bZy9ibXA8gb*

## Approach when UI resumes
1. **Reference study.** Jared picks 5–10 apps that feel ultra premium (maps, fitness or anything else). For each, name the specific thing that creates the feel: motion, typography, restraint, sound, haptics.
2. **Design system before screens.** Type, color, spacing, motion rules and the map style, defined first. Every screen comes from the same small rule set.
3. **Two or three signature moments, polished far past normal:** the live route build, the flyover preview, and possibly sending a route to the watch. Everything else stays quiet.
4. **Prototype on real routes only,** never sample data.
5. **Test with runners**, starting with Discovery Runners 1 and 2.

## Feedback on mockup v1 (from Jared)
"It's a start — not horrible but far from what I'd want. Too busy."
Every feature was on screen at once: two side panels, a chips bar, a status card, a profile strip, six layers and trust tags on every line.

**Direction:** a full-bleed map with the route as the hero; one floating request bar; one route card that expands; preferences and layers behind a single control; trust labels on tap, not everywhere. Fewer things on screen, more polish on each.

## Map UI principles to apply
Adapted from Eleken, "Map UI design" (https://www.eleken.co/blog-posts/map-ui-design).
1. **Quiet base map.** Muted streets and few labels. Color goes to the route, parks and water. Airbnb's muted map is the reference.
2. **Clear hierarchy.** The route is always the top visual layer. Panels can hide so the map takes over.
3. **Grouped layers, not a long toggle list.** For example: *Route details* (stoplights, crowds), *Places* (parks, water, restrooms, fountains), *You* (your runs, your reports, closures).
4. **Detail by zoom level.** Stoplight dots, restroom and fountain icons and street labels appear only when zoomed in. Zoomed out: route and segment colors only.
5. **Navigation separate from selection.** Tapping a stretch never pans the map, and dragging never selects. The selected stretch stays highlighted while the user pans.
6. **One meaning per color, everywhere.** Waterfront blue, park green, street neutral or accent, used the same in map, cards and profile. Warning colors only for problems (closed, packed).
7. **Readable on any background.** Dark outline or casing on the route and markers; test on dark and light map styles.
8. **Smooth performance.** Progressive loading, simplified geometry when zoomed out, fits the latency budget below.
9. **Predictable interaction.** Every tappable map object opens the same kind of card in the same place.

## Borrowed from the NYC Marathon course format
NYC runners know the marathon's course presentation: a course preview video, runner-POV previews by borough, mile-by-mile tours and an elevation chart. Take the format, not NYRR's visual style.
1. **Route preview (optional, on demand).** A "Preview" button flies the camera along the route in about 15–30 s, tilted with 3D buildings, captioning each stretch as it passes ("Mile 1 · East River Greenway"). Skippable. A candidate signature moment, and a shareable clip later. MapLibre camera animation along the line plus a deck.gl animated trail. Needs 3D building data from the basemap provider.
2. **Chapters.** Tell the route stretch by stretch, one card at a time. Detail lives in chapters instead of permanent panels.
3. **Mile markers** on the route, matching how runners and watch splits think.
4. **Named climbs** on the elevation profile (bridge ramps, park hills).
5. **Water and restrooms by mile**, like aid stations. Still unconfirmed by Discovery, so markers rather than a headline feature.
Skip: street-level runner POV video (needs licensed imagery or filming; the 3D flyover gets most of the effect).

## Goal
An interactive map where the route builds itself live, the runner can explore and edit it, and every stretch can take feedback. The UI should be a reason people come back, not a skin on the engine.

## Features (from v1; keep the features, reduce what's shown at once)
- **Request bar:** plain-English request, with the parsed `RunConstraints` shown as chips labeled *you said*, *preset* or *default* (this is `describe()`).
- **Live build:** the first route draws within about 1 second, segment by segment; other candidates can be hinted at.
- **Top 3 routes:** match score, composition (street / waterfront / park), lights per mile, crowds at the chosen hour, share on streets you already run.
- **Why this route:** a few reasons, each with a trust label (*measured*, *estimate*, *listed*).
- **Map:** pan, zoom and fit. The route is colored by segment type; layers for stoplights, crowds by hour, parks and water, your runs, restrooms and fountains, and closures. Tapping a stretch opens its details and feedback.
- **Feedback:** per stretch (*Great stretch*, *Too crowded*, *Path closed*, *Avoid this*); per route (*Send to watch*, *I ran it*, *Not for me* plus a reason). "Not for me" becomes an eval, and closure reports feed the closures layer.
- **Profile:** elevation and composition along the route, with a scrubber that moves a marker on the map.
- **Preferences:** Training / Exploring presets; stoplights, crowds, parks and water, streets I already run; *I wait* vs *I zig-zag* at red lights; departure time. Changes re-rank instantly, without a new routing call.

## What the engine must provide
1. Routes as GeoJSON with **per-segment properties** (type, length, signals, crowd estimate, surface, a human-readable stretch name for chapters and captions) and a trust label on each value. *(Do now, in Phase 2.)*
2. A **candidate pool** of about 20 routes with full metric vectors, so the client re-ranks on preference changes. *(Do now.)*
3. A **streaming** build: server-sent events or WebSocket, first route first.
4. **Hour of day** as an input everywhere (crowds, closures). *(Do now.)*
5. **Feedback endpoints**: segment reports, route rejections with a reason (written as eval fixtures), closure confirmations.
6. Edit operations: drag start or waypoint, draw an avoid area (GraphHopper via-points and per-request avoid areas).
7. Latency budget: first route in about 1 s, a full pool in about 5 s.
8. Elevation along the route with named climbs, and mile positions for markers. *(Do now.)*

## Stack (proposed)
React + TypeScript, MapLibre GL JS for the vector map, deck.gl for animated route and heat layers, on the existing FastAPI. Open decision: basemap tile provider (free OSM tile servers restrict heavy use; the route preview needs 3D buildings).

## Open questions
- Map or route list as the primary surface on phone width?
- Basemap provider and style (3D buildings needed for the preview).
- Does "navigate" ever mean turn-by-turn during a run? Discovery v1 found no demand yet; hold for iOS.
