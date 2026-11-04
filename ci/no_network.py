"""pytest plugin for CI (decision 019): any outbound socket connection fails the test that made it.

Unit tests must not need Postgres, GraphHopper, a geocoder or any network; the evals do, and don't run in CI.
Postgres is reached through libpq, not Python sockets, so CI also points DATABASE_URL at a closed port.
Load it with: PYTHONPATH=. uv run pytest -p ci.no_network
"""

import socket

_real_connect = socket.socket.connect


def _blocked(self, address):
    if self.family == socket.AF_UNIX:
        return _real_connect(self, address)
    raise RuntimeError(f"unit tests must not use the network (decision 019): connect to {address}")


def pytest_configure(config):
    socket.socket.connect = _blocked
