"""Canonical record types emitted by adapters (spec §6.3).

These are deliberately thin, immutable-ish dataclasses. Adapters parse raw
source payloads into these; the store persists them. Keeping the canonical
shape narrow is what lets unlike sources coexist without averaging raw scores.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

EntityType = Literal[
    "model", "deployment", "agent_system", "embedding_model", "speech_model", "other"
]
Direction = Literal["higher_is_better", "lower_is_better"]


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    name: str
    url: str
    layer: str
    domain: str
    access_method: str
    status: str
    as_of: Optional[str] = None
    license_or_terms: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EntityRecord:
    entity_id: str
    display_name: str
    entity_type: EntityType
    organization: Optional[str] = None
    family_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BenchmarkRecord:
    benchmark_id: str
    source_id: str
    name: str
    domain: str
    task_type: str
    metric_name: str
    direction: Direction
    protocol_version: str
    publish_date: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Observation:
    source_id: str
    benchmark_id: str
    entity_id: str
    raw_score: float
    unit: str
    observed_at: str
    sample_size: Optional[int] = None
    standard_error: Optional[float] = None
    lower_bound: Optional[float] = None
    upper_bound: Optional[float] = None
    relation: str = "exact"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PriceRecord:
    source_id: str
    deployment_id: str
    entity_id: str
    family_id: str
    currency: str
    as_of: str
    context_tokens: Optional[int] = None
    blended_usd_per_million: Optional[float] = None
    input_usd_per_million: Optional[float] = None
    cached_input_usd_per_million: Optional[float] = None
    cache_write_usd_per_million: Optional[float] = None
    output_usd_per_million: Optional[float] = None
    median_tokens_per_second: Optional[float] = None
    latency_first_chunk_seconds: Optional[float] = None
    total_response_seconds: Optional[float] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterResult:
    """Everything an adapter emits from one snapshot."""
    sources: list[SourceRecord] = field(default_factory=list)
    entities: list[EntityRecord] = field(default_factory=list)
    benchmarks: list[BenchmarkRecord] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    prices: list[PriceRecord] = field(default_factory=list)
    aliases: list[dict[str, Any]] = field(default_factory=list)
