"""Lineage drill-down + provider-route comparison."""
import json
from pathlib import Path

import pytest

from llm_pareto.adapters import openevals, vendor_claims
from llm_pareto.fetch import Snapshot, load_fixture
from llm_pareto.pipeline import recompute_normalized
from llm_pareto.store import Store
from llm_pareto.analysis import lineage_for, list_join_keys
from llm_pareto.routes import parse_routes

FIX = Path("tests/fixtures")
AS_OF = "2026-06-18"
pytestmark = pytest.mark.skipif(not (FIX / "hf_openevals" / "sample.json").exists(), reason="fixtures missing")


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = Store(tmp_path / "l.db")
    s.init_schema()
    s.write_result(openevals.parse(load_fixture("hf_openevals", "sample.json"), AS_OF))
    # add a verified self-reported claim so lineage has a snippet to show
    seed = tmp_path / "vc.toml"
    seed.write_text(
        '[[claim]]\nmodel="MoonshotAI/Kimi-K2.5"\njoin_key="moonshotai-kimi-k2-5"\nvendor="Moonshot"\n'
        'benchmark="gpqa_diamond"\nscore=87.6\nsource_url="https://ex.test/k"\nsource_type="model_card"\n')
    monkeypatch.setattr(vendor_claims, "SEED", seed)
    snap = Snapshot("vendor_claims", "x", json.dumps(
        {"pages": {"https://ex.test/k": "GPQA Diamond: 87.6% reported."}}).encode(),
        200, "application/json", AS_OF, None)
    s.write_result(vendor_claims.parse(snap, AS_OF))
    recompute_normalized(s)
    return s


def test_list_join_keys(store):
    keys = dict(list_join_keys(store))
    assert "moonshotai-kimi-k2-5" in keys


def test_lineage_has_sources_and_snippet(store):
    ln = lineage_for(store, "moonshotai-kimi-k2-5")
    assert ln["n_observations"] >= 1
    # the self-reported obs carries a source_url + verifying snippet
    sr = [e for e in ln["evidence"] if e["relation"] == "self_reported"]
    assert sr and sr[0]["source_url"] == "https://ex.test/k"
    assert sr[0]["verifying_snippet"]
    # third-party openevals obs are also present, with normalized scores
    tp = [e for e in ln["evidence"] if e["source"] == "hf_openevals"]
    assert tp and all(e["normalized"] is not None for e in tp)


def test_parse_routes_fixture():
    payload = json.load(open(FIX / "openrouter_endpoints" / "sample.json"))
    routes = parse_routes(payload)
    assert len(routes) > 5
    # sorted cheapest input first; each has provider + price fields
    prices = [r["input_usd_per_million"] for r in routes if r["input_usd_per_million"] is not None]
    assert prices == sorted(prices)
    assert all("provider" in r and "uptime_pct_30m" in r for r in routes)


def test_routes_figure_builds():
    pytest.importorskip("plotly")
    from llm_pareto.viz import routes_figure
    routes = parse_routes(json.load(open(FIX / "openrouter_endpoints" / "sample.json")))
    fig = routes_figure(routes)
    assert fig.data and fig.data[0].type == "bar"
