"""Adapter tests against frozen fixtures — deterministic, offline (spec §20.2)."""
import json
from pathlib import Path

import pytest

from llm_pareto.fetch import load_fixture
from llm_pareto.adapters import openevals, openrouter, lmarena
from llm_pareto.store import Store
from llm_pareto.pipeline import recompute_normalized, integrity_check

FIX = Path("tests/fixtures")
AS_OF = "2026-06-18"
pytestmark = pytest.mark.skipif(not (FIX / "hf_openevals" / "sample.json").exists(),
                                reason="fixtures not captured yet (run `make ingest` once)")


def _store(tmp_path):
    s = Store(tmp_path / "t.db")
    s.init_schema()
    return s


def test_openevals_parse_shape():
    snap = load_fixture("hf_openevals", "sample.json")
    res = openevals.parse(snap, AS_OF)
    assert len(res.benchmarks) == 11
    assert all(b.direction == "higher_is_better" for b in res.benchmarks)
    assert all("task_family" in b.metadata for b in res.benchmarks)
    assert len(res.entities) == 105
    assert len(res.observations) > 0
    # aggregate must NOT become an observation/benchmark
    assert not any("aggregate" in b.benchmark_id for b in res.benchmarks)


def test_openevals_idempotent(tmp_path):
    snap = load_fixture("hf_openevals", "sample.json")
    s = _store(tmp_path)
    s.write_result(openevals.parse(snap, AS_OF))
    n1 = s.query("SELECT COUNT(*) c FROM observations")[0]["c"]
    s.write_result(openevals.parse(snap, AS_OF))  # same date → upsert, no growth
    n2 = s.query("SELECT COUNT(*) c FROM observations")[0]["c"]
    assert n1 == n2 and n1 > 0


def test_openevals_later_date_new_generation(tmp_path):
    snap = load_fixture("hf_openevals", "sample.json")
    s = _store(tmp_path)
    s.write_result(openevals.parse(snap, "2026-06-18"))
    s.write_result(openevals.parse(snap, "2026-07-01"))  # later date → new benchmark ids
    gens = s.query("SELECT COUNT(DISTINCT benchmark_id) c FROM benchmarks")[0]["c"]
    assert gens == 22  # 11 dims x 2 generations


def test_openrouter_prices_and_conversion():
    snap = load_fixture("openrouter_models", "sample.json")
    res = openrouter.parse(snap, AS_OF)
    assert len(res.prices) > 50
    # per-million conversion: a known-shape price is positive and reasonable
    assert all(p.input_usd_per_million is None or p.input_usd_per_million >= 0 for p in res.prices)
    assert any(p.output_usd_per_million and p.output_usd_per_million > 0 for p in res.prices)


def test_lmarena_blocked_is_honest():
    snap = load_fixture("lmarena", "sample.json")
    res = lmarena.parse(snap, AS_OF)
    # 403 body → partial-blocked source, zero fabricated observations
    assert len(res.observations) == 0
    assert res.sources[0].status == "partial-blocked"


def test_normalize_cohort_and_integrity(tmp_path):
    s = _store(tmp_path)
    s.write_result(openevals.parse(load_fixture("hf_openevals", "sample.json"), AS_OF))
    recompute_normalized(s)
    checks = integrity_check(s)
    assert checks["normalized_out_of_range"] == 0
    assert checks["cohort_size_mismatches"] == 0
    assert checks["foreign_key_violations"] == 0
    # every normalized score within [0,1]
    bad = s.query("SELECT COUNT(*) c FROM normalized_observations WHERE normalized_score<0 OR normalized_score>1")[0]["c"]
    assert bad == 0
