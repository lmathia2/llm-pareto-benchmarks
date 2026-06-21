"""HF official per-dataset leaderboard adapter (spec §4, §10.1) — token-gated.

The per-dataset leaderboard route (huggingface.co/api/datasets/{id}/leaderboard)
returns 401 without auth. This adapter uses HF_TOKEN when present to pull the
official leaderboard for a configured dataset (which DOES include proprietary
models), and records a blocked condition otherwise — the same honest pattern as
the Artificial Analysis adapter. Configure target datasets in HF_OFFICIAL_DATASETS.
"""
from __future__ import annotations

import json
import os
import urllib.parse

from ..fetch import Snapshot, fetch
from ..models import AdapterResult, BenchmarkRecord, EntityRecord, Observation
from . import register
from .base import blocked_source, slug

SOURCE_ID = "hf_official_leaderboard"
API = "https://huggingface.co/api/datasets/{enc}/leaderboard"

# dataset -> (benchmark key, task_family, metric field, model field, score scale)
TARGETS = {
    "Idavidrein/gpqa": ("gpqa_diamond", "reasoning"),
    "TIGER-Lab/MMLU-Pro": ("mmlu_pro", "reasoning"),
    "SWE-bench/SWE-bench_Verified": ("swe_bench_verified", "coding_agent"),
}


def fetch_live() -> Snapshot:
    token = os.environ.get("HF_TOKEN")
    bundle = {}
    for ds in TARGETS:
        enc = urllib.parse.quote(ds, safe="")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        # fetch() strips auth headers by design; with a token an authorized client
        # is required. Without one this captures the gated 401 for honest recording.
        r = fetch(SOURCE_ID, API.format(enc=enc), headers=headers, terms_note="HF gated leaderboard")
        try:
            bundle[ds] = r.json()
        except Exception:
            bundle[ds] = {"_status": r.http_status}
    content = json.dumps({"datasets": bundle, "authed": bool(token)}).encode()
    return Snapshot(SOURCE_ID, "hf_official://bundle", content, 200, "application/json", _now(), "HF gated")


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rows(payload):
    if isinstance(payload, dict):
        for k in ("leaderboard", "results", "data", "rows"):
            if isinstance(payload.get(k), list):
                return payload[k]
        return []
    return payload if isinstance(payload, list) else []


@register(SOURCE_ID)
def parse(snapshot: Snapshot, as_of: str) -> AdapterResult:
    data = snapshot.json()
    if not data.get("authed"):
        return blocked_source(SOURCE_ID, "HF official per-dataset leaderboards",
                              "https://huggingface.co/datasets", "benchmark dataset", "cross-domain",
                              as_of, "leaderboard route gated (401); set HF_TOKEN to enable")
    res = AdapterResult()
    any_rows = False
    for ds, (bkey, family) in TARGETS.items():
        rows = _rows(data["datasets"].get(ds, {}))
        if not rows:
            continue
        any_rows = True
        bench_id = f"{SOURCE_ID}/{bkey}/{as_of}"
        res.benchmarks.append(BenchmarkRecord(
            benchmark_id=bench_id, source_id=SOURCE_ID, name=f"{bkey} (HF official)",
            domain="official", task_type="official_leaderboard", metric_name="score",
            direction="higher_is_better", protocol_version=as_of, publish_date=as_of,
            metadata={"task_family": family, "dataset": ds},
        ))
        for r in rows:
            name = r.get("model") or r.get("model_name") or r.get("name")
            score = r.get("score") or r.get("accuracy") or r.get("resolved")
            if not name or score is None:
                continue
            jk = slug(name)
            ent_id = f"hfofficial/{jk}"
            res.entities.append(EntityRecord(
                entity_id=ent_id, display_name=name, entity_type="model",
                organization=r.get("organization"), family_id=jk, metadata={"join_key": jk}))
            res.observations.append(Observation(
                source_id=SOURCE_ID, benchmark_id=bench_id, entity_id=ent_id,
                raw_score=float(score), unit="score", observed_at=as_of, relation="exact",
                metadata={"dataset": ds}))
    if not any_rows:
        return blocked_source(SOURCE_ID, "HF official per-dataset leaderboards",
                              "https://huggingface.co/datasets", "benchmark dataset", "cross-domain",
                              as_of, "authed but no parseable leaderboard rows")
    return res
