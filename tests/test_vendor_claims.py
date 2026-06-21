"""Vendor self-reported claims + HF official adapters (proprietary coverage)."""
import json
import textwrap
from pathlib import Path

from llm_pareto.adapters import vendor_claims, hf_official
from llm_pareto.adapters.vendor_claims import _verify
from llm_pareto.fetch import Snapshot

AS_OF = "2026-06-18"


def _snap(source_id, obj):
    return Snapshot(source_id, "x", json.dumps(obj).encode(), 200, "application/json", AS_OF, None)


def test_verify_strong_weak_absent():
    page = "Model scores 91.9% on GPQA Diamond and is great."
    ok, conf, _ = _verify(page, 91.9, "gpqa_diamond")
    assert ok and conf == "strong"
    # number present but far from keyword
    page2 = "GPQA Diamond is hard. " + ("x " * 200) + "unrelated 91.9% elsewhere"
    ok2, conf2, _ = _verify(page2, 91.9, "gpqa_diamond")
    assert ok2 and conf2 == "weak"
    # absent
    ok3, conf3, _ = _verify("no numbers here", 91.9, "gpqa_diamond")
    assert not ok3 and conf3 == "absent"


def test_vendor_claims_verifies_before_ingest(tmp_path, monkeypatch):
    seed = tmp_path / "vc.toml"
    seed.write_text(textwrap.dedent("""
        [[claim]]
        model = "TestModel-A"
        join_key = "test-a"
        vendor = "ACME"
        benchmark = "gpqa_diamond"
        score = 91.9
        source_url = "https://example.test/a"
        source_type = "announcement"

        [[claim]]
        model = "TestModel-B"
        join_key = "test-b"
        vendor = "ACME"
        benchmark = "gpqa_diamond"
        score = 55.5
        source_url = "https://example.test/b"
        source_type = "announcement"
    """))
    monkeypatch.setattr(vendor_claims, "SEED", seed)
    # page A contains the number near keyword; page B does NOT contain 55.5
    snap = _snap("vendor_claims", {"pages": {
        "https://example.test/a": "GPQA Diamond: 91.9% accuracy.",
        "https://example.test/b": "GPQA Diamond results pending.",
    }})
    res = vendor_claims.parse(snap, AS_OF)
    names = {o.entity_id.split("/")[-1] for o in res.observations}
    assert "testmodel-a" in names          # verified → ingested
    assert "testmodel-b" not in names      # unverified → skipped (no fabrication)
    assert all(o.relation == "self_reported" for o in res.observations)
    assert res.benchmarks[0].metadata["self_reported"] is True


def test_hf_official_blocked_without_token():
    res = hf_official.parse(_snap("hf_official_leaderboard", {"authed": False, "datasets": {}}), AS_OF)
    assert res.sources[0].status == "partial-blocked"
    assert len(res.observations) == 0
