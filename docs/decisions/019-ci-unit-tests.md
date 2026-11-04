# 019: CI runs the unit tests on every push and pull request; the evals stay local

**Status:** proposed (2026-11-03). Numbered after 018 (speed), which was assigned first.

## Context
Until now every test ran only on the reviewer's laptop, which has Postgres, GraphHopper and the loaded NYC data running. A unit test that quietly needed one of them would pass there and nobody would notice. That had happened: `test_main_parses_arguments` ran the CLI's `main()`, which since decision 017 loads closures from Postgres. It was reading the local database.

## Decision
- **Workflow** (`.github/workflows/unit-tests.yml`): on every push and pull request, `uv sync --frozen` and `pytest` with the testpaths `api`, `etl`, `routing` and `ci`. It runs on ubuntu-latest with Python 3.12 from `astral-sh/setup-uv`, with the uv cache keyed on `uv.lock`, and a 10-minute timeout.
- **Unit tests need no services.** CI points `DATABASE_URL` and `GRAPHHOPPER_URL` at a closed port and loads `ci/no_network.py`. That plugin makes any outbound socket connection fail the test that made it. Postgres goes through libpq, not Python sockets, which is why the closed database port is needed too. So a unit test that reaches for a service fails in CI instead of passing on a laptop.
- **The one test that needed Postgres** now stubs the CLI's two database calls (`db_closures`, `db_stretches`). No test needed GraphHopper, a geocoder or personal data: a clean checkout without `data/`, `apple_health_export/`, `out/` or `etl/data/` passes. So no test is skipped in CI.
- **The evals** (`evals/`) are not run in CI. They need the live stack and the loaded data, which CI doesn't have.
- **Badge** in the README.

## Checked
- A clean checkout, run with the same environment and command as CI: 358 passed, with the network blocked and both services unreachable.
- Not yet run on GitHub. It runs on the first push of this branch.

## If a test does need a service later
It belongs in `evals/`. If it has to stay a unit test, mark it with a skip that names the service and the reason. Don't let it reach the network.
