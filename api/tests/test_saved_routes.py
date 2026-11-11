"""Every build is stored (step 7, decision 030): saved_routes keeps the route id, what kind of request it was, the
constraints and the final payload. Never the raw text (R8: it can hold health details) and never the phone's
location or profile. The Postgres tests run against the local database and skip when it isn't up."""

import psycopg
import pytest

from api.saved_routes import PgRouteStore, stored_request

REQUEST = {"v": 1, "text": "6 mi, my knee is sore so keep it flat",
           "client": {"now": "2026-11-08T06:40:00-05:00", "tz": "America/New_York",
                      "location": {"lat": 40.7438, "lon": -73.9799, "accuracy_m": 15}},
           "profile": {"usual_distance_mi": 3.1, "saved_places": [{"id": "home", "lat": 40.7438, "lon": -73.9799}]},
           "recent_routes": [{"id": "rt_a", "date": "2026-10-27", "name": "East River out-and-back"}]}


def test_the_stored_request_keeps_no_text_location_or_profile():
    kept = stored_request(REQUEST, "text", "p_1234")
    assert kept == {"v": 1, "kind": "text", "parse_id": "p_1234",
                    "client": {"now": "2026-11-08T06:40:00-05:00", "tz": "America/New_York"}}
    flat = repr(kept)
    assert "knee" not in flat and "40.74" not in flat and "rt_a" not in flat


def _db():
    from etl.load import database_url
    try:
        return psycopg.connect(database_url(), connect_timeout=2, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("Postgres isn't running (make up)")


FINAL = {"event": "final", "v": 1, "route_id": "r_test_saved", "routes": [{"id": "r_test_saved.1", "rank": 1}],
         "route": None, "pool_size": 3, "pool": {"candidates": 9, "best_of": 3}, "notes": []}


@pytest.fixture
def store():
    conn = _db()
    yield PgRouteStore()
    conn.execute("DELETE FROM saved_routes WHERE route_id LIKE 'r_test_%'")
    conn.close()


def test_a_saved_build_loads_back_from_a_fresh_store(store):
    store.save("r_test_saved", stored_request(REQUEST, "text", "p_1"), {"distance_mi": 6.0}, FINAL)
    again = PgRouteStore()  # as after a server restart: nothing in memory
    assert again.load("r_test_saved") == FINAL
    assert again.load("r_test_missing") is None


def test_the_row_holds_constraints_and_the_request_kind(store):
    store.save("r_test_saved", stored_request(REQUEST, "answer", "p_2"), {"distance_mi": 6.0}, FINAL)
    with _db() as conn:
        row = conn.execute("SELECT request, constraints, final->>'route_id' FROM saved_routes "
                           "WHERE route_id = 'r_test_saved'").fetchone()
    assert row[0]["kind"] == "answer" and row[1] == {"distance_mi": 6.0} and row[2] == "r_test_saved"


def test_saving_the_same_build_twice_keeps_one_row(store):
    store.save("r_test_saved", stored_request(REQUEST, "text", "p_1"), {}, FINAL)
    store.save("r_test_saved", stored_request(REQUEST, "text", "p_1"), {}, FINAL | {"pool_size": 4})
    assert PgRouteStore().load("r_test_saved")["pool_size"] == 4


def test_a_database_that_is_down_is_reported_not_raised(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")
    s = PgRouteStore()
    assert s.save("r_test_x", {}, {}, FINAL) is False
    assert s.load("r_test_x") is None
    assert "saved_routes" in capsys.readouterr().err
