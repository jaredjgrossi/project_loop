# Loop UI references — v1
*Status: reference study, step 1 of "Approach when UI resumes" in `ui/brief-v1.md` (2026-11-01). Jared picked the 9 apps. No screens, code or design system yet: this feeds step 2 (design system) and step 3 (signature moments).*

**How to read this.** Each app lists only the things that create its premium feel, grouped by motion, type, color and restraint, map, loading, sound and haptics, empty states, and what it leaves out. Claims marked *(source)* are backed by a linked page. Claims marked *(check on device)* come from using the apps and should be confirmed on a phone before anything is built on them.

## The list

| App | Category | Why it's here |
|---|---|---|
| Apple Maps | Maps | 3D city detail, Flyover tours, custom out-and-back and loop routes with elevation |
| Google Earth | Maps | The fly-to camera arc, and stop-by-stop Voyager stories |
| Flighty | Maps / live data | A live journey told in plain words with reasons, on the lock screen as well as in the app |
| Airbnb | Maps / marketplace | The muted map (the brief's reference) and objects that morph between list, map and detail |
| Apple Fitness + Watch | Fitness | Completion moments, haptics on the wrist and routes colored by pace |
| Oura | Fitness / health | One score up front, detail one tap away, very little chrome |
| Linear | Productivity | Feels instant, and a whole theme generated from three inputs |
| Things 3 | Productivity | Restraint, and one floating control that does several jobs by where you drop it |
| Halide | Camera | Pro controls that feel physical, through haptic clicks and gestures in place of dials |

## The apps

### Apple Maps
- **Map styling.** In the detailed city maps, landmarks are custom 3D models, and trees, elevation and road markings are drawn, while ordinary buildings stay plain *(check on device)*. The detail goes where people orient themselves, not everywhere.
- **Motion.** Flyover city tours fly a slow, steady camera around a city's landmarks with no cuts and no speed changes mid-shot *(check on device)*. Tilting the map by two-finger drag eases into 3D rather than snapping.
- **Routes.** iOS 18 custom routes: tap points on the map, then pick **Out & Back** or **Close Loop**. Distance, time and an elevation graph update as you build *([MacRumors](https://www.macrumors.com/2024/06/12/apple-maps-hiking-features-on-ios-18/), [Tom's Guide](https://tomsguide.com/phones/iphones/apple-maps-ios-18-lets-you-create-custom-routes-heres-how-to-do-it))*. Saved routes work offline. This is the closest existing product to Loop's route card: the route type is a choice, not a buried setting.
- **Route line.** The route is the most saturated thing on the map and has a darker casing, so it reads on any background *(check on device)*.
- **One primary action.** Directions end in one large **Go** button. Everything else is secondary text *(check on device)*.
- **Haptics.** With navigation on Apple Watch, the wrist gets different tap patterns before a right turn and before a left turn, so you don't have to look *(check on device; Apple documents the patterns in its Watch user guide)*.
- **Leaves out.** Ads, a cluttered pin layer at low zoom, and labels the current zoom level doesn't need.
- **For Loop.** Put 3D detail only on landmarks a runner steers by: bridges, the Stuy Cove pier, park gates. Out-and-back vs loop as a visible choice. Distinct left and right turn haptics on the watch.

### Google Earth
- **Motion: the fly-to.** Going from one place to another is one continuous arc: the camera pulls up, travels, then descends, easing in and out, with no cut *(check on device)*. Distance is felt, not shown.
- **Loading.** On launch you see the whole globe first, and detail streams in as you descend. Low-resolution imagery sharpens in place instead of showing a spinner *(check on device)*.
- **Chapters.** Voyager stories are a run of cards, and each card flies the camera to its stop *(check on device)*. Story and camera move together.
- **Related: Google Maps Immersive View for routes.** A 3D preview of a walking, cycling or driving route before you leave, with a time slider that shows the route at another hour along with that hour's weather and traffic *([MacRumors](https://www.macrumors.com/2023/10/27/google-maps-immersive-view-for-routes), [PetaPixel](https://petapixel.com/2023/05/10/you-can-now-preview-google-maps-routes-with-ai-powered-immersion))*. New York was in the launch cities.
- **Leaves out.** During a fly-to there are no controls, captions or progress bar. The motion is the content.
- **For Loop.** The flyover preview should be one continuous camera move, from overview down into mile 1, along the route, and back up to overview. Captions per stretch, like Voyager cards. The departure-time slider is the Immersive View idea applied to crowds.

### Flighty
- **Origin and type.** It's built on airport signage and departure-board conventions *([Apple, Behind the Design](https://cur.at/VcCahLU?m=web))*. Numbers that change (times, gates) are set so they don't jitter as they update *(check on device)*.
- **Status as a sentence.** Delay predictions come *with reasons* *([App Store listing](https://apps.apple.com/app/apple-store/id1358823008?mt=8))*. The app tells you what's happening and why, not just a color.
- **Live beyond the app.** Live Activities and the Dynamic Island carry the trip once it's under way *([Behind the Design](https://cur.at/VcCahLU?m=web))*. "Where's my plane" tracks the inbound aircraft up to 25 hours ahead *([App Store](https://apps.apple.com/app/apple-store/id1358823008?mt=8))*.
- **Color.** Mostly neutral. Color is kept for state: on time, delayed, cancelled *(check on device)*. The flight path on the map is the brightest line *(check on device)*.
- **Speed as premium.** Reviewers single out how fast its notifications arrive *([The Sweet Setup](https://thesweetsetup.com/flightys-beautiful-design-fast-push-notifications-make-it-one-of-the-best-flight-tracking-apps-on-the-app-store/))*. Being first with the news is part of the feel.
- **Year in review.** "Passport" turns your flight history into a lifetime summary *(check on device)*.
- **Leaves out.** Raw data tables up front. Detail is behind a tap; the main view is one line per flight.
- **For Loop.** "Best of 20" with one reason in plain words ("fewest lights of any 6-mile route from here"). Trust labels written like Flighty's reasons. After sending to the watch, a Live Activity carries the run. A year-end "every stretch you ran" summary, later.

### Airbnb
- **Map styling.** A muted base map where the price pins carry nearly all the color and contrast. The selected pin inverts (dark fill, light text) instead of growing or adding a badge *(check on device)*. This is the brief's own reference for a quiet base map.
- **Selection.** Tapping a pin brings up a card in the same place every time, and the map doesn't jump *(check on device)*. That's principle 9 in the brief.
- **Motion.** A listing photo grows into the detail view instead of a new screen sliding in *(check on device)*. The May 2025 redesign moved to "dimensional" 3D animated icons, away from flat design *([It's Nice That](https://www.itsnicethat.com/articles/airbnb-app-redesign-140525), [Wallpaper](https://www.wallpaper.com/travel/airbnb-launches-experiences-services-brian-chesky-interview))*.
- **Leaves out.** Street-level clutter on the map. Points of interest are faded so the pins win.
- **For Loop.** Mute the base map until the route is the only saturated object. A selected stretch inverts or brightens; it doesn't sprout a label. Shared-element motion: the route card expands from the route itself.

### Apple Fitness + Watch
- **Completion moment.** Closing a ring plays a short celebratory animation with a haptic, then gets out of the way *(check on device)*. Overshooting is shown as the ring wrapping past itself in a deeper shade, with no extra badge *(check on device)*.
- **One meaning per color.** Move, Exercise and Stand each keep their color everywhere: watch face, app, widgets, notifications *(check on device)*. This is the brief's map principle 6, applied across an entire platform.
- **Route maps.** After a workout, the route is colored by pace along its length *(check on device for the exact scale)*. The data lives on the line instead of in a separate chart.
- **Start.** A workout begins with a 3-2-1 countdown ring you can tap to skip *(check on device)*.
- **Watch handoff.** Custom workouts can now be built on iPhone and sync to the watch to start from the wrist *([BGR on iOS 26](https://bgr.com/2003927/ios-26-fitness-hidden-apple-watch-feature/), [Apple Support](https://support.apple.com/guide/watch/create-a-custom-workout-apd66fcd5c5c/11/watchos))*.
- **Leaves out.** Text on the wrist during a workout. Haptics and a few large numbers carry it.
- **For Loop.** Sending to the watch is a completion moment: one animation and one haptic, then quiet. Segment colors stay identical on the map, card, profile and watch. A run's after-view colors the line by what happened (pace or stops), not by a chart beside it.

### Oura
- **Hierarchy.** The 2024 redesign cut five tabs to three: Today, Vitals and My Health *([Oura](https://ouraring.com/blog/new-oura-app-experience/))*. Today is meant to work like a news app's "Top Stories" page. The most important score and a quick read of the day sit at the top, and unusual metrics surface only when they're unusual *([Droid Life](https://www.droid-life.com/2025/11/13/oura-ring-app-gets-big-facelift-ai-gets-more-access-to-your-metrics/))*.
- **Color.** In Vitals, color marks your body's state against your own baseline, not a fixed scale *([Oura](https://ouraring.com/blog/new-oura-app-experience/))*.
- **Motion and tone.** Slow, soft transitions and a calm, mostly dark palette *(check on device)*. Nothing flashes or celebrates loudly. Premium here means composure.
- **Leaves out.** Every metric at once. Detail sits under the score, never beside it.
- **For Loop.** One number on the route card (the match score), and everything else under it. Only flag what's unusual for *this* runner ("more lights than you usually accept"). Keep motion slow outside the signature moments.

### Linear
- **Color system.** Themes are generated in LCH from three inputs (base color, accent color, contrast) instead of 98 hand-set variables *([Linear](https://linear.app/now/how-we-redesigned-the-linear-ui))*. Because LCH is perceptually uniform, surfaces at the same lightness look equally light in any theme.
- **Restraint.** The redesign limited how much accent color the chrome uses, and a later refresh dimmed less important chrome so the work area stands out *([Linear](https://linear.app/now/how-we-redesigned-the-linear-ui), [Linear changelog](https://linear.app/changelog/2026-03-12-ui-refresh))*.
- **Type.** Inter Display for headings, Inter for everything else *([Linear](https://linear.app/now/how-we-redesigned-the-linear-ui))*.
- **Speed.** Actions take effect on screen immediately and sync after. Nothing waits on a spinner *(check on device)*. Motion is short and only shows that something moved.
- **Leaves out.** Decoration, illustration in working views, and confirmation dialogs for undoable actions.
- **For Loop.** Generate the light and dark map and UI from a few LCH inputs, so segment colors keep equal weight in both. Re-ranking on a preference change must be instant and local, as the brief already requires: no spinner, and the cards reorder with motion.

### Things 3
- **One control, several jobs.** The Magic Plus button sits bottom-right. Tap it to add a task, or drag it to drop a task exactly where it should go, and drag it to the left edge in a project to make a section instead *([MacStories](https://www.macstories.net/reviews/things-3-beauty-and-delight-in-a-task-manager/), [9to5Mac](https://9to5mac.com/2017/05/19/friday-5-things-3-video-top-features/))*. Reviewers drag it just to watch the animation.
- **Completion.** Checking a task is a small animation and haptic, and the task lingers a beat before leaving the list *(check on device)*.
- **Type and space.** Generous whitespace, bold headings, and almost no lines or boxes *(check on device)*. It won Apple Design Awards *([9to5Mac](https://9to5mac.com/2017/05/19/friday-5-things-3-video-top-features/))*.
- **Leaves out.** Settings in the main view, colored tags everywhere, and badges.
- **For Loop.** The single preferences-and-layers control could work like Magic Plus: tap for preferences, or drag it onto the map to add a waypoint or draw an avoid area (brief, engine item 6). A finished action lingers a beat before it leaves.

### Halide
- **Physical feel.** Exposure and focus are swipes, and the team tuned haptic and visual feedback together so the controls feel like camera dials with click stops *([Dead Pixels Society](https://thedeadpixelssociety.com/halide-1-5-the-camera-app-designed-from-scratch-for-iphone-x/), [Lux](https://www.lux.camera/introducing-halide/))*. A focus ring becomes a horizontal swipe.
- **Restraint with pro controls.** The founders set out to avoid camera apps that look like flight simulators *([TechCrunch](https://techcrunch.com/2017/05/30/ex-apple-designer-former-twitter-engineer-launch-halide-a-premium-iphone-camera-app/?ncid=rss))*. Dense controls hide until you reach for them.
- **Award.** Halide Mark II won an Apple Design Award *([Apple, Behind the Design](https://cur.at/IHKzSGc?m=web))*.
- **Leaves out.** Labels on controls you've already learned. Gestures become muscle memory *([Lux](https://www.lux.camera/introducing-halide/))*.
- **For Loop.** Haptic detents on the elevation scrubber at each mile and on the departure-time slider at each hour. The preference sliders click at meaningful steps ("I wait" vs "I zig-zag"), not at every percent.

## Patterns that fit Loop's signature moments

### 1. Live route build
| Pattern | From | How Loop applies it |
|---|---|---|
| The route is the only saturated thing | Airbnb, Apple Maps | Quiet base map; the route draws in full segment color with a dark casing |
| One continuous stroke at a steady pace | Google Earth's unbroken camera arc | The first route draws from the start in one stroke at a constant speed, like a runner, in about 1 s. No pauses at segment joins |
| Show the result now, refine in place | Linear | First route on screen at about 1 s. As the rest of the pool arrives, the card updates in place without moving. If a better route wins, the line changes shape instead of being redrawn |
| Status as a sentence with a reason | Flighty | "Best of 20 · fewest lights of any 6-mile route from here." Trust label on tap |
| One score, detail underneath | Oura | The match score is the only number until the card is opened |
| One beat when it settles | Apple Fitness rings, Things checkbox | When the ranking settles, the route brightens once with a single light haptic. No confetti |
| Candidates as a hint, never competition | (Loop's own) | Other candidates appear as faint, short-lived strokes behind the route, then fade. They never take color |

### 2. Flyover preview
| Pattern | From | How Loop applies it |
|---|---|---|
| One unbroken camera move | Google Earth fly-to, Apple Maps Flyover | Overview → descend to the start → follow the line at a steady height and tilt → rise back to overview. Ease only at the ends. 15–30 s, skippable |
| Detail only where it orients | Apple Maps landmarks | 3D buildings stay plain; bridges, piers and park gates stand out |
| Chapters ride the camera | Google Earth Voyager | One caption per stretch, timed to the camera ("Mile 1 · East River Greenway"). Captions fade; they don't stack |
| The hour changes the scene | Google Immersive View for routes | Scrubbing the departure time during preview changes the crowd shading along the route |
| No controls during the move | Google Earth | Only Skip. A tap pauses |
| Ends on a decision | Apple Maps "Go" | The flyover lands on the overview with Send to watch as the only action |

### 3. Send to watch
| Pattern | From | How Loop applies it |
|---|---|---|
| A completion beat, then quiet | Apple Fitness rings | The button turns into the route shape, which shrinks toward the bottom edge, with one firm haptic on the phone. A matching tap arrives on the watch when it lands |
| Instant confirmation, sync behind | Linear | The phone shows "On your watch" at once; a problem surfaces only if the sync fails |
| The run lives outside the app | Flighty Live Activities | A Live Activity or lock-screen widget: route name, distance, start time, then live mile once running |
| Haptics carry the route | Apple Watch turn taps | Distinct taps for left and right turns. A different pattern for "restroom ahead" or "the route rejoins the greenway" (held for iOS, per the brief's open question) |
| Same colors on the wrist | Apple Fitness | Segment colors on the watch match the phone exactly |

## Cross-cutting rules for the design system (step 2)
1. **Color goes to the route, state and nothing else.** Generate light and dark themes from a few LCH inputs (Linear) so waterfront blue, park green and street neutral keep the same weight in both.
2. **One number per surface.** Every card has a single lead value (Oura); the rest is behind a tap.
3. **Write status as sentences with reasons** (Flighty). The trust label is the reason's source, shown on tap.
4. **Motion is either a signature moment or near-invisible.** Long, continuous and eased for the build and flyover; short and functional everywhere else (Linear, Oura).
5. **Haptics mark steps that mean something** (Halide, Things): miles on the scrubber, hours on the time slider, the build settling, the route landing on the watch. Nothing else vibrates.
6. **Sound: none.** No pick depends on sound for its premium feel. Loop stays silent; the watch speaks in haptics.
7. **No spinners.** Show the first route, then refine (Linear, Google Earth's progressive imagery).
8. **Leave out labels, badges and toggles the current zoom or task doesn't need** (Apple Maps, Airbnb, Things).

## Open items before step 2
- Confirm every *(check on device)* claim on a phone, especially the Apple Watch turn-tap patterns and the Fitness pace colors.
- Pick the basemap provider. The flyover needs 3D buildings, and the landmark-only detail above may require a custom style.
- Decide whether the watch handoff uses the Fitness custom-workout path or Loop's own watch app. That affects how much of moment 3 is possible.
