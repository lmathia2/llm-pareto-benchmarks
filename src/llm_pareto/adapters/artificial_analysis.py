"""Artificial Analysis adapter (spec §10.4) — terms-gated Tier-B example.

Artificial Analysis is commercial: its API requires a key and its table has
redistribution terms. This adapter therefore ingests ONLY when an explicit opt-in
+ key is provided (env AA_API_KEY). Otherwise it records the source as blocked
with zero rows — the canonical "record, don't fabricate" pattern for terms-
sensitive Tier-B/C sources. When enabled, each row is a deployment with an
Intelligence Index (quality), price, throughput, and latency.
"""
from __future__ import annotations

import os

from ..fetch import Snapshot, fetch
from ..models import AdapterResult, BenchmarkRecord, EntityRecord, Observation, PriceRecord
from . import register
from .base import blocked_source, slug

SOURCE_ID = "artificial_analysis"
API = "https://artificialanalysis.ai/api/v2/data/llms/models"
PARSER_VERSION = "1.0.0"


def fetch_live() -> Snapshot:
    key = os.environ.get("AA_API_KEY")
    headers = {"x-api-key": key} if key else {}
    # NOTE: fetch() strips auth-like headers by design; AA access requires an
    # explicitly authorized client. Absent that, this returns the gated response.
    return fetch(SOURCE_ID, API, headers=headers, terms_note="Artificial Analysis commercial terms")


@register(SOURCE_ID)
def parse(snapshot: Snapshot, as_of: str) -> AdapterResult:
    if not os.environ.get("AA_OPT_IN"):
        return blocked_source(SOURCE_ID, "Artificial Analysis LLM Performance",
                              "https://artificialanalysis.ai/leaderboards/models",
                              "deployment", "quality, speed, price", as_of,
                              "commercial terms; set AA_OPT_IN=1 and AA_API_KEY to enable")
    try:
        payload = snapshot.json()
    except Exception:
        return blocked_source(SOURCE_ID, "Artificial Analysis LLM Performance",
                              "https://artificialanalysis.ai/leaderboards/models",
                              "deployment", "quality, speed, price", as_of, "unparseable/gated response")

    rows = payload.get("data", payload) if isinstance(payload, dict) else payload
    res = AdapterResult()
    bench_id = f"{SOURCE_ID}/intelligence_index/{as_of}"
    res.benchmarks.append(BenchmarkRecord(
        benchmark_id=bench_id, source_id=SOURCE_ID, name="AA Intelligence Index",
        domain="composite", task_type="composite_intelligence", metric_name="intelligence_index",
        direction="higher_is_better", protocol_version=as_of, publish_date=as_of,
        metadata={"task_family": "reasoning", "note": "composite; not a single benchmark"},
    ))
    for r in rows if isinstance(rows, list) else []:
        name = r.get("name") or r.get("model")
        if not name:
            continue
        ent_id = f"deployment/{slug(name)}"
        res.entities.append(EntityRecord(
            entity_id=ent_id, display_name=name, entity_type="deployment",
            organization=r.get("creator") or r.get("provider"), family_id=slug(name),
            metadata={"join_key": slug(name), "context": r.get("context_window")},
        ))
        idx = r.get("intelligence_index") or r.get("quality_index")
        if idx is not None:
            res.observations.append(Observation(
                source_id=SOURCE_ID, benchmark_id=bench_id, entity_id=ent_id,
                raw_score=float(idx), unit="index", observed_at=as_of, relation="exact"))
        price_in = r.get("price_input") or r.get("input_price")
        if price_in is not None:
            res.prices.append(PriceRecord(
                source_id=SOURCE_ID, deployment_id=f"aa/{slug(name)}", entity_id=ent_id,
                family_id=slug(name), currency="USD", as_of=as_of,
                input_usd_per_million=float(price_in),
                output_usd_per_million=float(r.get("price_output") or price_in),
                median_tokens_per_second=r.get("median_tokens_per_second"),
                latency_first_chunk_seconds=r.get("ttft"),
                metadata={"basis": "artificial_analysis"}))
    return res
