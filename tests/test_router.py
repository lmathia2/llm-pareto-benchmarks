"""Pre-call router tests — cheapest-passing logic (Doc-1)."""
from pathlib import Path

import pytest

from llm_pareto.adapters import openevals, openrouter
from llm_pareto.fetch import load_fixture
from llm_pareto.pipeline import recompute_normalized
from llm_pareto.router import route, predict_pass
from llm_pareto.store import Store

FIX = Path("tests/fixtures")
AS_OF = "2026-06-18"
PROFILE = "profiles/coding_agent_balanced.toml"
pytestmark = pytest.mark.skipif(not (FIX / "hf_openevals" / "sample.json").exists(),
                                reason="fixtures not captured yet")


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "r.db")
    s.init_schema()
    s.write_result(openevals.parse(load_fixture("hf_openevals", "sample.json"), AS_OF))
    s.write_result(openrouter.parse(load_fixture("openrouter_models", "sample.json"), AS_OF))
    recompute_normalized(s)
    return s


def test_predict_pass_monotone():
    assert predict_pass(0) == 0.0
    assert predict_pass(100) == 1.0
    assert predict_pass(60) < predict_pass(80)


def test_cheapest_passing(store):
    res = route(store, PROFILE, AS_OF, quality_threshold=0.5)
    assert res["decision"] is not None
    chosen_cost = res["decision"]["cost"]
    # the chosen route is the cheapest among those clearing the threshold
    assert res["n_passing"] >= 1
    assert res["decision"]["predicted_pass"] >= res["request"]["effective_threshold"]
    # it should not be more expensive than the always-top baseline
    assert chosen_cost <= res["always_frontier_baseline"]["cost"]


def test_higher_risk_is_stricter(store):
    low = route(store, PROFILE, AS_OF, risk_tier="low")
    high = route(store, PROFILE, AS_OF, risk_tier="critical")
    assert high["request"]["effective_threshold"] > low["request"]["effective_threshold"]
    assert high["n_passing"] <= low["n_passing"]


def test_no_pass_escalates(store):
    res = route(store, PROFILE, AS_OF, quality_threshold=0.999)
    assert res["decision"] is None
    assert "escalat" in res["escalation_flag"].lower()
