"""Artificial Analysis adapter (spec §10.4) — terms-gated Tier-B example.

Artificial Analysis is commercial: its API requires a key and its table has
redistribution terms. robots.txt permits crawling, but the data is governed by a
separate Terms of Use, so we access the OFFICIAL API (not HTML scraping) and store
DERIVED measurements + a source link, never a mirror of their table. This adapter
therefore ingests ONLY when an explicit opt-in + key is provided (AA_OPT_IN=1 +
AA_API_KEY); otherwise it records the source as blocked with zero rows — the
canonical "record, don't fabricate" pattern for terms-sensitive sources.

When enabled, each row yields: the AA **Intelligence Index** (a composite quality),
price, throughput, latency, and — when the API exposes them — the **individual
evaluations** behind the index (GPQA Diamond, Humanity's Last Exam, Terminal-Bench,
SciCode, …), each as its own per-benchmark cohort tagged with a task family.
join_key is org-prefixed (`openai-gpt-5-2`) to line up with OpenRouter pricing.
"""
from __future__ import annotations

import os

from ..fetch import Snapshot, fetch
from ..models import (
    AdapterResult, BenchmarkRecord, EntityRecord, Observation, PriceRecord, SourceRecord,
)
from . import register
from .base import SchemaDriftError, blocked_source, slug

SOURCE_ID = "artificial_analysis"
API = "https://artificialanalysis.ai/api/v2/data/llms/models"
PARSER_VERSION = "1.1.0"

# AA evaluation key (substring) -> (display, domain, task_family). The individual
# evals that make up the Intelligence Index; unmapped evals are still ingested
# (family=None) so coverage stays honest.
_EVAL_MAP = [
    ("gpqa", ("GPQA Diamond", "science", "reasoning")),
    ("humanity", ("Humanity's Last Exam", "expert_knowledge", "reasoning")),
    ("hle", ("Humanity's Last Exam", "expert_knowledge", "reasoning")),
    ("terminal", ("Terminal-Bench", "agents", "coding_agent")),
    ("scicode", ("SciCode", "coding", "coding_agent")),
    ("livecodebench", ("LiveCodeBench", "coding", "coding_agent")),
    ("lcr", ("AA Long-Context Reasoning", "long_context", "long_context")),
    ("mmlu", ("MMLU-Pro", "knowledge", "reasoning")),
    ("mmmu", ("MMMU-Pro", "multimodal", "reasoning")),
    ("aime", ("AIME", "mathematics", "math")),
    ("math", ("AA Math", "mathematics", "math")),
    ("banking", ("τ³-Banking", "finance", "finance")),
    ("ifbench", ("IFBench", "instruction_following", "preference")),
]


def _classify_eval(eval_key: str):
    k = eval_key.lower()
    for needle, triple in _EVAL_MAP:
        if needle in k:
            return triple
    return (eval_key, "general", None)


def fetch_live() -> Snapshot:
    key = os.environ.get("AA_API_KEY")
    headers = {"x-api-key": key} if key else {}
    # NOTE: fetch() strips auth-like headers by design; AA access requires an
    # explicitly authorized client. Absent that, this returns the gated response.
    return fetch(SOURCE_ID, API, headers=headers, terms_note="Artificial Analysis commercial terms")


# AA composite indices are headline roll-ups; we ingest them for display but do
# NOT let them feed a task dimension (their components already do — avoids double
# counting). Mapped to task_family=None.
_COMPOSITE = {"artificial_analysis_intelligence_index", "artificial_analysis_coding_index",
              "artificial_analysis_math_index"}


def authed_fetch_live() -> Snapshot:
    """Authorized fetch for opted-in users. Sends the API key in the request but
    NEVER persists it (the Snapshot/sidecar store only the response body), so the
    'no stored credentials' guardrail holds. Falls back to the gated path if no
    key is set."""
    key = os.environ.get("AA_API_KEY")
    if not (key and os.environ.get("AA_OPT_IN")):
        return fetch_live()
    import httpx
    from ..fetch import USER_AGENT, _utc_now
    resp = httpx.get(API, headers={"User-Agent": USER_AGENT, "x-api-key": key},
                     timeout=60.0, follow_redirects=True)
    return Snapshot(SOURCE_ID, API, resp.content, resp.status_code,
                    resp.headers.get("content-type", "application/json"), _utc_now(),
                    "Artificial Analysis commercial terms; API key authorized, not stored")


def _eval_benchmark(res: AdapterResult, seen: dict, ek: str, as_of: str) -> str:
    bench_id = f"{SOURCE_ID}/{ek}/{as_of}"
    if bench_id not in seen:
        display, domain, family = _classify_eval(ek)
        composite = ek in _COMPOSITE
        rec = BenchmarkRecord(
            benchmark_id=bench_id, source_id=SOURCE_ID, name=display,
            domain=domain, task_type="composite_index" if composite else "aggregated_third_party",
            metric_name=ek, direction="higher_is_better", protocol_version=as_of, publish_date=as_of,
            metadata={"task_family": None if composite else family, "aggregator": "artificial_analysis",
                      "composite": composite},
        )
        seen[bench_id] = rec
        res.benchmarks.append(rec)
    return bench_id


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

    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise SchemaDriftError(f"{SOURCE_ID}: expected a 'data' list, got {type(rows).__name__}")

    res = AdapterResult()
    res.sources.append(SourceRecord(
        source_id=SOURCE_ID, name="Artificial Analysis LLM Performance",
        url="https://artificialanalysis.ai/leaderboards/models", layer="deployment",
        domain="quality, speed, price", access_method="json-api", status="active", as_of=as_of,
        license_or_terms="commercial terms; derived measurements + source link, not mirrored",
        metadata={"models": len(rows), "aggregator": "artificial_analysis"}))
    seen: dict[str, BenchmarkRecord] = {}

    for r in rows:
        name = r.get("name")
        mslug = r.get("slug")
        if not (name and mslug):
            continue
        creator = r.get("model_creator") or {}
        org = creator.get("name")
        org_slug = creator.get("slug") or slug(org or "unknown")
        join_key = f"{slug(org_slug)}-{slug(mslug)}"
        ent_id = f"model/{SOURCE_ID}/{join_key}"
        res.entities.append(EntityRecord(
            entity_id=ent_id, display_name=name, entity_type="model",
            organization=org, family_id=join_key,
            metadata={"join_key": join_key, "source_model_id": r.get("id"),
                      "release_date": r.get("release_date")}))

        evals = r.get("evaluations") or {}
        if not isinstance(evals, dict):
            raise SchemaDriftError(f"{SOURCE_ID}: 'evaluations' for {mslug} is not an object")
        for ek, val in evals.items():
            if val is None:
                continue
            bench_id = _eval_benchmark(res, seen, ek, as_of)
            res.observations.append(Observation(
                source_id=SOURCE_ID, benchmark_id=bench_id, entity_id=ent_id,
                raw_score=float(val), unit="score", observed_at=as_of, relation="exact",
                metadata={"aggregator": "artificial_analysis"}))

        pricing = r.get("pricing") or {}
        pin = pricing.get("price_1m_input_tokens")
        blended = pricing.get("price_1m_blended_3_to_1")
        if pin is not None or blended is not None:
            res.prices.append(PriceRecord(
                source_id=SOURCE_ID, deployment_id=f"aa/{join_key}", entity_id=ent_id,
                family_id=join_key, currency="USD", as_of=as_of,
                input_usd_per_million=float(pin) if pin is not None else None,
                output_usd_per_million=float(pricing["price_1m_output_tokens"])
                    if pricing.get("price_1m_output_tokens") is not None else None,
                blended_usd_per_million=float(blended) if blended is not None else None,
                median_tokens_per_second=r.get("median_output_tokens_per_second"),
                latency_first_chunk_seconds=r.get("median_time_to_first_token_seconds"),
                metadata={"basis": "artificial_analysis"}))
    return res
