"""llm-stats.com Data API adapter — durable third-party benchmark aggregator.

llm-stats publishes a free (key-gated) Data API that aggregates per-benchmark
scores, pricing, and metadata for 300+ models, updated within hours of release
(base `https://api.zeroeval.com/stats/v1/`, `Authorization: Bearer <key>`).
Unlike `vendor_claims` (self-reported, mixed-protocol), these are independently
collected third-party numbers, so each benchmark is its own cohort and they may
share normalization with other harness runs of the same protocol.

Access posture (mirrors `artificial_analysis`): ingests ONLY with an explicit
opt-in + key (`LLMSTATS_OPT_IN=1`, `LLMSTATS_API_KEY`); otherwise records the
source as blocked with zero fabricated rows. Fails CLOSED on schema drift so a
changed upstream shape errors loudly instead of silently mis-mapping columns.

Expected `/models` shape (per the published API docs; validate against a live
key before trusting in production):
    {"data": [
       {"id": "anthropic/claude-opus-4-6", "name": "Claude Opus 4.6",
        "organization": "anthropic", "context_window": 200000,
        "pricing": {"input_per_million": 5.0, "output_per_million": 25.0},
        "benchmarks": [
           {"slug": "gpqa_diamond", "name": "GPQA Diamond", "score": 91.3,
            "higher_is_better": true}, ...]}, ...]}
"""
from __future__ import annotations

import os

from ..fetch import Snapshot, fetch
from ..models import (
    AdapterResult, BenchmarkRecord, EntityRecord, Observation, PriceRecord,
)
from . import register
from .base import SchemaDriftError, blocked_source, slug

SOURCE_ID = "llm_stats"
API = "https://api.zeroeval.com/stats/v1/models?limit=500"
URL = "https://llm-stats.com/leaderboards/llm-leaderboard"
PARSER_VERSION = "1.0.0"

# Map a benchmark slug to (domain, task_family, direction). Substring-matched so
# minor naming variants still land in the right task lens. Unknown benchmarks are
# still ingested (family=None) so coverage stays honest; they just don't feed a
# task dimension until mapped.
_FAMILY_MAP = [
    ("gpqa", ("science", "reasoning", "higher_is_better")),
    ("mmlu", ("knowledge", "reasoning", "higher_is_better")),
    ("hle", ("expert_knowledge", "reasoning", "higher_is_better")),
    ("humanity", ("expert_knowledge", "reasoning", "higher_is_better")),
    ("aime", ("mathematics", "math", "higher_is_better")),
    ("math", ("mathematics", "math", "higher_is_better")),
    ("swe", ("coding/agents", "coding_agent", "higher_is_better")),
    ("terminal", ("agents", "coding_agent", "higher_is_better")),
    ("livecodebench", ("coding", "coding_agent", "higher_is_better")),
    ("arc-agi", ("reasoning", "reasoning", "higher_is_better")),
    ("arc_agi", ("reasoning", "reasoning", "higher_is_better")),
]


def _classify(bslug: str, bname: str) -> tuple[str, str | None, str]:
    key = f"{bslug} {bname}".lower()
    for needle, triple in _FAMILY_MAP:
        if needle in key:
            return triple
    return ("general", None, "higher_is_better")


def fetch_live() -> Snapshot:
    key = os.environ.get("LLMSTATS_API_KEY")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    # fetch() strips auth-like headers by design; live access requires an
    # explicitly authorized client. Absent that this returns the gated response.
    return fetch(SOURCE_ID, API, headers=headers, terms_note="llm-stats Data API; free key required")


def _blocked(as_of: str, reason: str) -> AdapterResult:
    return blocked_source(SOURCE_ID, "llm-stats.com Data API", URL,
                          "benchmark dataset", "cross-domain", as_of, reason)


@register(SOURCE_ID)
def parse(snapshot: Snapshot, as_of: str) -> AdapterResult:
    if not os.environ.get("LLMSTATS_OPT_IN"):
        return _blocked(as_of, "set LLMSTATS_OPT_IN=1 and LLMSTATS_API_KEY to enable")
    try:
        payload = snapshot.json()
    except Exception:
        return _blocked(as_of, "unparseable/gated response")

    if not isinstance(payload, dict) or "data" not in payload:
        # opted in but the shape is wrong: fail closed rather than guess.
        raise SchemaDriftError(f"{SOURCE_ID}: expected top-level 'data' list, got {type(payload).__name__}")
    rows = payload["data"]
    if not isinstance(rows, list):
        raise SchemaDriftError(f"{SOURCE_ID}: 'data' is not a list")

    res = AdapterResult()
    res.sources.append(_source_record(as_of, len(rows)))
    seen_bench: dict[str, BenchmarkRecord] = {}

    for r in rows:
        name = r.get("name") or r.get("id")
        if not name:
            continue
        mid = r.get("id") or name
        org = r.get("organization") or r.get("creator")
        join_key = slug(mid)  # e.g. "anthropic/claude-opus-4-6" -> "anthropic-claude-opus-4-6"
        ent_id = f"model/{SOURCE_ID}/{join_key}"
        res.entities.append(EntityRecord(
            entity_id=ent_id, display_name=name, entity_type="model",
            organization=org, family_id=join_key,
            metadata={"join_key": join_key, "context": r.get("context_window"),
                      "source_model_id": mid},
        ))

        benches = r.get("benchmarks") or []
        if benches and not isinstance(benches, list):
            raise SchemaDriftError(f"{SOURCE_ID}: 'benchmarks' for {mid} is not a list")
        for b in benches:
            bslug = b.get("slug") or slug(b.get("name", ""))
            score = b.get("score")
            if not bslug or score is None:
                continue
            domain, family, direction = _classify(bslug, b.get("name", ""))
            if b.get("higher_is_better") is False:
                direction = "lower_is_better"
            bench_id = f"{SOURCE_ID}/{bslug}/{as_of}"
            if bench_id not in seen_bench:
                rec = BenchmarkRecord(
                    benchmark_id=bench_id, source_id=SOURCE_ID,
                    name=b.get("name") or bslug, domain=domain,
                    task_type="aggregated_third_party", metric_name="score",
                    direction=direction, protocol_version=as_of, publish_date=as_of,
                    metadata={"task_family": family, "aggregator": "llm-stats"},
                )
                seen_bench[bench_id] = rec
                res.benchmarks.append(rec)
            res.observations.append(Observation(
                source_id=SOURCE_ID, benchmark_id=bench_id, entity_id=ent_id,
                raw_score=float(score), unit="score", observed_at=as_of,
                relation="exact", metadata={"aggregator": "llm-stats", "source_model_id": mid}))

        pricing = r.get("pricing") or {}
        pin = pricing.get("input_per_million")
        if pin is not None:
            res.prices.append(PriceRecord(
                source_id=SOURCE_ID, deployment_id=f"{SOURCE_ID}/{join_key}", entity_id=ent_id,
                family_id=join_key, currency="USD", as_of=as_of,
                context_tokens=r.get("context_window"),
                input_usd_per_million=float(pin),
                output_usd_per_million=float(pricing.get("output_per_million") or pin),
                metadata={"basis": "llm-stats"}))
    return res


def _source_record(as_of: str, n: int):
    from ..models import SourceRecord
    return SourceRecord(
        source_id=SOURCE_ID, name="llm-stats.com Data API", url=URL,
        layer="benchmark dataset", domain="cross-domain", access_method="json-api",
        status="active", as_of=as_of,
        license_or_terms="free Data API (key required); third-party aggregated",
        metadata={"models": n, "aggregator": "llm-stats"},
    )
