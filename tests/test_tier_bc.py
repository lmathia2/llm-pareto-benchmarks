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


def test_artificial_analysis_parses_evals_and_price_when_opted_in(monkeypatch):
    monkeypatch.setenv("AA_OPT_IN", "1")
    res = artificial_analysis.parse(load_fixture("artificial_analysis", "sample_data.json"), AS_OF)
    assert len(res.entities) == 2
    # org-prefixed join_key (lines up with OpenRouter pricing convention)
    keys = {e.metadata["join_key"] for e in res.entities}
    assert "acme-acme-reasoner-x-high" in keys
    # granular evals feed task families; composite index is informational only
    by_metric = {b.metric_name: b for b in res.benchmarks}
    assert by_metric["gpqa"].metadata["task_family"] == "reasoning"
    assert by_metric["terminalbench_v2_1"].metadata["task_family"] == "coding_agent"
    assert by_metric["tau_banking"].metadata["task_family"] == "finance"
    assert by_metric["artificial_analysis_intelligence_index"].metadata["task_family"] is None
    # null evals skipped; AA pricing emitted per model
    assert all(o.raw_score is not None for o in res.observations)
    assert len(res.prices) == 2
    assert any(p.blended_usd_per_million for p in res.prices)


def test_artificial_analysis_schema_drift(monkeypatch):
    monkeypatch.setenv("AA_OPT_IN", "1")
    bad = Snapshot("artificial_analysis", "x", b'{"data": {"not": "a list"}}', 200,
                   "application/json", AS_OF, None)
    with pytest.raises(SchemaDriftError):
        artificial_analysis.parse(bad, AS_OF)
