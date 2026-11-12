# 046: The Apple Health prior applies to the owner's install only

**Status:** accepted (2026-11-12). From the full product review (6.3, 4.3).

## The problem
`Engine` read `runner_prior` (1,424 street segments from the reviewer's Apple Health runs) for every request, in
two places: candidates "on a route you run" (`anchor_fn`) and the "Matches routes you run" score (`use_prior`).
On a shared server every tester near Kips Bay got routes built from, and scored against, one person's habits, and
those routes showed where that person runs. "8 flat miles" from Williamsburg led with "Out-and-back on a route you
run".

## Decision
- The prior is on for the installs in `LOOP_PRIOR_INSTALL_IDS` (`.env`, comma separated) and off for every other
  install, and for a request with no `X-Loop-Install` header. Unset means nobody.
- `Engine.for_install(install_id)` returns the engine itself for a listed install, else a copy with `use_prior=False`
  and `anchor_fn=None`. The copy shares the shape-edit pools, so an edit finds its build.
- Every server path takes its engine from it: a build, a shape edit from the pool, "run again", and the planned run.
- `Engine.prior_installs` defaults to None: no limit. That's the reviewer's own scripts and live evals, which call
  the engine directly. The server always passes the env list.
- With the prior off, "matches routes you run" is unscored, as the honest eval setting already did (decision 019),
  not zero.
- The id is the app's random install id (never a name). It's read from `.env`, which is git-ignored.

## Not changed
- Stored routes (`saved_routes`) and who can read them: the review's other 6.3 points (retention, per-install reads)
  stay open for the beta work.
- "Run again" and past-route rebuilds use the runner's own stored line, not the prior.

## Tests
- `api/tests/test_prior_scope.py`: the owner gets the anchors and the score; another install and a missing id get
  neither; an engine with no list keeps them; the copy shares the pools; the list is read from the environment.
- `api/tests/test_server.py`: the install header reaches `for_install`, with and without an id.
- `evals/routes/test_review_fixes.py` (live): 8 flat miles from Williamsburg gives a guest and a request with no id
  no "route you run", and gives the owner one.
