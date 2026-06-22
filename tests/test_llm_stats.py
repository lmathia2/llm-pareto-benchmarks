"""llm-stats aggregator adapter: gating, schema-drift, and parse correctness."""
import os

import pytest

from llm_pareto.adapters import llm_stats
from llm_pareto.adapters.base import SchemaDriftError
from llm_pareto.fetch import Snapshot, load_fixture


def _snap():
    return load_fixture(llm_stats.SOURCE_ID, "sample.json")


def test_blocked_without_opt_in(monkeypatch):
    monkeypatch.delenv("LLMSTATS_OPT_IN", raising=False)
    res = llm_stats.parse(_snap(), "2026-06-18")
    assert res.observations == []
    assert res.sources and res.sources[0].metadata.get("blocked") is True


def test_parses_when_opted_in(monkeypatch):
    monkeypatch.setenv("LLMSTATS_OPT_IN", "1")
    res = llm_stats.parse(_snap(), "2026-06-18")
    # 4 models, multiple benchmarks each
    assert len(res.entities) == 4
    assert len(res.observations) >= 13
    assert len(res.prices) == 4

    # join_keys must line up with OpenRouter price keys for the engine to bridge
    keys = {e.metadata["join_key"] for e in res.entities}
    assert "anthropic-claude-opus-4-6" in keys
    assert "openai-gpt-5-2" in keys

    # benchmarks carry task families and their own per-benchmark cohort
    fams = {b.metadata.get("task_family") for b in res.benchmarks}
    assert {"reasoning", "coding_agent"} <= fams
    assert all(b.benchmark_id.startswith("llm_stats/") for b in res.benchmarks)

    # third-party, not self-reported
    assert all(o.relation == "exact" for o in res.observations)


def test_schema_drift_fails_closed(monkeypatch):
    monkeypatch.setenv("LLMSTATS_OPT_IN", "1")
    bad = Snapshot(llm_stats.SOURCE_ID, "x://bad", b'{"unexpected": 1}', 200,
                   "application/json", "2026-06-18T00:00:00Z", "test")
    with pytest.raises(SchemaDriftError):
        llm_stats.parse(bad, "2026-06-18")
