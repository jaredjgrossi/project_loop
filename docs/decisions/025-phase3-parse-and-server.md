# 025: Phase 3 — requests parsed on the server, routes streamed to the phone

**Status:** accepted (2026-11-05). The plan is `docs/phase3/build-brief-v1.md`; the data contract is
`docs/phase3/parse-contract-v1.md`; the test set is `docs/phase3/parse-evals-v1.md`.

## Decision
- **The phone sends text; the server parses and builds.** `POST /v1/runs` on FastAPI, on Jared's Mac, reached
  over Tailscale. The reply is server-sent events: `parsed`, then `top3` / `provisional` / `final` (the engine's
  decision 018 stream), or one `question`, then `done` or `error`.
- **One Claude call per parse, server-side, as a single tool call.** Its schema holds what the runner said, not
  `RunConstraints`. Deterministic code resolves places, applies the eval rules (R1–R18), and builds
  `RunConstraints`, chips, can't-do lines, notes or the one question. The cheapest model that passes the parse evals
  wins, starting with Haiku 5.5. Claude never receives coordinates and never writes text the runner sees, apart from
  place and route names it echoes back.
- **Source words in the data are the contract's keys:** `said`, `preset`, `default`, `usual`. `api/copy.py` turns
  them into display words ("you said", "Training preset", "your usual"). Every string the runner sees comes from
  `api/copy.py`; evals match on keys and gap ids, never wording.
- **Tolerance folds into the distance chip** ("3–4 mi"). There is no separate tolerance chip.
- **Places come from an OSM `places` table built from our extract.** One match: use it (trust `listed`). Several:
  ask. None: ask for an address. Decision 005 stands: the same address in several boroughs asks.
- **`llm_calls` logs the request text, model, tokens, cost and latency** for every Claude call, never the runner's
  location.

## Repo
- Phase 3 work happens on branch `phase3`, in its own worktree, one commit per step. The three design docs are
  copied into `docs/phase3/`.
- The contract's example coordinates for "Home" and the current location were replaced in the repo copy with the
  Kips Bay Library stand-in (40.7438, -73.9799), the public stand-in used across the evals.

## Open, to bring back to Jared when reached
- Same address or crossing in several boroughs: always ask, or use the one near the runner (places step).
- How long a pending question stays open (API step).
- The major-park list and radius for "the park"; how fuzzy place matching is before it asks.
- Whether a larger model is worth its cost if Haiku 5.5 fails cases.
