"""Access axis (api vs open_weight), canonical-key join bridging, and the
price-only evidence flag / low-coverage caveat."""
import sqlite3

from llm_pareto.identity import access_type, canonical_key
from llm_pareto.adapters import openevals, openrouter
from llm_pareto.fetch import load_fixture
from llm_pareto.pipeline import recompute_normalized
from llm_pareto.recommend import build_candidates, run_profile
from llm_pareto.store import Store


def test_access_type_classification():
    assert access_type("Anthropic", "Claude Opus 4.8") == "api"
    assert access_type("OpenAI", "GPT-5.2") == "api"
    assert access_type("Google", "Gemini 3 Pro") == "api"
    # open-weight markers win even under an API-only org
    assert access_type("OpenAI", "gpt-oss-120b") == "open_weight"
    assert access_type("Google", "Gemma 3 27B") == "open_weight"
    # known open-weight orgs
    assert access_type("DeepSeek", "DeepSeek V3") == "open_weight"
    assert access_type("Qwen", "Qwen3.5 397B") == "open_weight"
    # name fallback when org missing
    assert access_type(None, "Claude Sonnet 4.5") == "api"


def test_canonical_key_strips_dates_and_prefix_not_version():
    # date stamp + provider prefix removed
    assert canonical_key("anthropic-claude-3-5-sonnet-20241022") == "claude-3-5-sonnet"
    assert canonical_key("google-gemini-2-5-pro-preview-05-06") == "gemini-2-5-pro"
    # version number must be preserved (4-5 and 4-8 stay distinct)
    assert canonical_key("anthropic-claude-opus-4-5") != canonical_key("anthropic-claude-opus-4-8")
    assert canonical_key(None) is None


def _warehouse(tmp_path):
    db = str(tmp_path / "t.db")
    s = Store(db)
    s.init_schema()
    for mod, fx in [(openevals, "sample.json"), (openrouter, "sample.json")]:
        snap = load_fixture(mod.SOURCE_ID, fx)
        s.record_snapshot(snap.snapshot_id, snap.source_id, snap.retrieved_at, snap.sha256,
                          snap.url, snap.persist(), snap.http_status, snap.terms_note, {})
        s.write_result(mod.parse(snap, "2026-06-18"), snapshot_id=snap.snapshot_id)
    s.conn.commit()
    recompute_normalized(s)
    return s


def test_candidates_carry_access_and_evidence(tmp_path):
    s = _warehouse(tmp_path)
    prof = {
        "weights": {"general_intelligence": 0.6, "context_headroom": 0.4},
        "dimension_map": {"general_intelligence": ["reasoning"], "context_headroom": ["__context__"]},
        "constraints": {"require_price": True},
        "workload": {"input_tokens": 1000, "output_tokens": 1000, "calls": 1},
    }
    cands = build_candidates(s, prof, "2026-06-18")
    assert cands, "expected priced deployments"
    for c in cands:
        assert c.payload["access"] in ("api", "open_weight")
        assert c.payload["evidence"] in ("measured", "transferred", "price_only")
    # at least one API-access deployment should be present from the openrouter catalog
    assert any(c.payload["access"] == "api" for c in cands)
    # price-only models exist (API models with no benchmark join)
    assert any(c.payload["evidence"] == "price_only" for c in cands)


def test_coverage_floor_surfaces_price_only(tmp_path):
    s = _warehouse(tmp_path)
    prof = {
        "weights": {"general_intelligence": 0.7, "context_headroom": 0.3},
        "dimension_map": {"general_intelligence": ["reasoning"], "context_headroom": ["__context__"]},
        "constraints": {"require_price": True, "min_evidence_coverage": 0.30},
        "workload": {"input_tokens": 1000, "output_tokens": 1000, "calls": 1},
    }
    strict = run_profile(s, prof, "2026-06-18")
    relaxed = run_profile(s, prof, "2026-06-18", coverage_floor=0.0)
    assert relaxed["n_eligible"] >= strict["n_eligible"]
    assert "api" in relaxed["access_summary"] or "open_weight" in relaxed["access_summary"]


def test_access_filter(tmp_path):
    s = _warehouse(tmp_path)
    prof = {
        "weights": {"general_intelligence": 1.0},
        "dimension_map": {"general_intelligence": ["reasoning"]},
        "constraints": {"require_price": True},
        "workload": {"input_tokens": 1000, "output_tokens": 1000, "calls": 1},
    }
    api = run_profile(s, prof, "2026-06-18", coverage_floor=0.0, access_filter="api")
    ow = run_profile(s, prof, "2026-06-18", coverage_floor=0.0, access_filter="open_weight")
    assert all(c["access"] == "api" for c in api["frontier"])
    assert all(c["access"] == "open_weight" for c in ow["frontier"])
