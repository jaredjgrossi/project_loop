"""The reviewer's Apple Health prior (runner_prior) applies to their install id only (full review 6.3).

On a shared server every other install got candidates "on a route you run" and a "Matches routes you run" score from
the reviewer's own corridors. The prior is now off for every install except the ones in LOOP_PRIOR_INSTALL_IDS.
"""

from api.engine import Engine, Start, prior_installs_from_env
from api.tests.test_engine import engine, fake_generate, rc
from api.tests.test_make_loop import candidate

OWNER = "owner-install-0001"
OTHER = "tester-install-0002"
FAMILIAR = object()  # stands for ml.familiar_anchors


def spy_engine(**kw):
    seen = {}

    def generate_fn(lat, lon, miles, grid, route_fn, round_trip_fn, **gen_kw):
        seen["anchor_fn"] = gen_kw.get("anchor_fn")
        return fake_generate([candidate()])(lat, lon, miles, grid, route_fn, round_trip_fn, **gen_kw)

    def context_for_fn(lights, grid, use_prior=True, start=None):
        seen["use_prior"] = use_prior

    return engine(generate_fn, anchor_fn=FAMILIAR, context_for_fn=context_for_fn,
                  prior_installs=frozenset({OWNER}), **kw), seen


def build_for(install):
    eng, seen = spy_engine()
    eng.for_install(install).build(rc(), Start(40.7438, -73.9799, "My location"), lambda e: None, "r_1")
    return seen


def test_the_owners_install_gets_the_prior():
    assert build_for(OWNER) == {"anchor_fn": FAMILIAR, "use_prior": True}


def test_every_other_install_gets_no_prior():
    assert build_for(OTHER) == {"anchor_fn": None, "use_prior": False}


def test_a_request_with_no_install_id_gets_no_prior():
    assert build_for(None) == {"anchor_fn": None, "use_prior": False}


def test_an_engine_with_no_install_list_keeps_the_prior_for_scripts_and_evals():
    eng = Engine(anchor_fn=FAMILIAR)  # prior_installs left unset: the reviewer's own scripts and live evals
    assert eng.for_install(OTHER) is eng and eng.for_install(None) is eng


def test_the_engine_for_another_install_shares_the_shape_edit_pools():
    eng, _ = spy_engine()
    other = eng.for_install(OTHER)
    other.remember_pool("r_1", [candidate()])
    assert eng.pools == other.pools and "r_1" in eng.for_install(OTHER).pools


def test_the_install_list_comes_from_the_environment(monkeypatch):
    monkeypatch.delenv("LOOP_PRIOR_INSTALL_IDS", raising=False)
    assert prior_installs_from_env() == frozenset()  # unset: nobody has the prior
    monkeypatch.setenv("LOOP_PRIOR_INSTALL_IDS", f" {OWNER} , ,{OTHER}")
    assert prior_installs_from_env() == frozenset({OWNER, OTHER})
