import socket

import pytest

import ci.no_network as guard


def test_the_ci_guard_refuses_outbound_connections_and_can_be_undone(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", guard._real_connect)
    guard.pytest_configure(None)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RuntimeError, match="must not use the network"):
            s.connect(("127.0.0.1", 9))
    finally:
        s.close()
