"""Tier-B/C adapter tests (expanded scope) — aider (accessible) + AA (gated)."""
import os
from pathlib import Path

import pytest

from llm_pareto.adapters import aider_polyglot, artificial_analysis
from llm_pareto.adapters.base import SchemaDriftError
from llm_pareto.fetch import Snapshot, load_fixture

FIX = Path("tests/fixtures")
AS_OF = "2026-06-18"


@pytest.mark.skipif(not (FIX / "aider_polyglot" / "sample.txt").exists(), reason="fixture missing")
def test_aider_parses_agent_systems():
    res = aider_polyglot.parse(load_fixture("aider_polyglot", "sample.txt"), AS_OF)
    assert len(res.benchmarks) == 1
    assert res.benchmarks[0].metadata["task_family"] == "coding_agent"
    assert res.benchmarks[0].direction == "higher_is_better"
    assert all(e.entity_type == "agent_system" for e in res.entities)
    assert all(o.relation == "exact_system" for o in res.observations)
    assert len(res.observations) > 10
    # cost carried as metadata, not a normalization cohort
    assert any("total_cost_usd" in e.metadata for e in res.entities)


def test_aider_fails_closed_on_schema_drift():
    bad = Snapshot("aider_polyglot", "x", b"- foo: 1\n", 200, "text/plain", AS_OF, None)
    with pytest.raises(SchemaDriftError):
        aider_polyglot.parse(bad, AS_OF)


def test_artificial_analysis_blocked_without_optin(monkeypatch):
    monkeypatch.delenv("AA_OPT_IN", raising=False)
    snap = Snapshot("artificial_analysis", "x", b'{"error":"gated"}', 401, "application/json", AS_OF, None)
    res = artificial_analysis.parse(snap, AS_OF)
    # terms-gated: recorded as blocked, zero fabricated rows
    assert res.sources[0].status == "partial-blocked"
    assert len(res.observations) == 0
    assert len(res.prices) == 0
