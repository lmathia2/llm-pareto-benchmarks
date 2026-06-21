"""OpenRouter model catalog adapter (spec §10.8, deployment economics).

Each row is a DEPLOYMENT (a model served by a provider/route), not a base model.
Prices arrive as per-token USD strings; we convert to USD-per-million. We emit
deployment entities + effective-dated PriceRecords + alias proposals so the
recommend engine can join price to quality evidence by normalized family.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..fetch import Snapshot, fetch
from ..models import AdapterResult, EntityRecord, PriceRecord, SourceRecord
from . import register

SOURCE_ID = "openrouter_models"
ENDPOINT = "https://openrouter.ai/api/v1/models"
PARSER_VERSION = "1.0.0"


def fetch_live() -> Snapshot:
    return fetch(SOURCE_ID, ENDPOINT, terms_note="OpenRouter public catalog; aliases change over time")


def _per_million(s) -> float | None:
    try:
        return round(float(s) * 1_000_000, 6)
    except (TypeError, ValueError):
        return None


@register(SOURCE_ID)
def parse(snapshot: Snapshot, as_of: str) -> AdapterResult:
    data = snapshot.json()
    models = data["data"] if isinstance(data, dict) else data

    result = AdapterResult()
    result.sources.append(SourceRecord(
        source_id=SOURCE_ID, name="OpenRouter Model Catalog", url="https://openrouter.ai/models",
        layer="deployment", domain="pricing and routing", access_method="public API", status="active",
        as_of=as_of, license_or_terms="source-specific; verify before redistribution",
        metadata={"num_deployments": len(models)},
    ))

    for m in models:
        mid = m.get("id")
        if not mid:
            continue
        pricing = m.get("pricing") or {}
        input_pm = _per_million(pricing.get("prompt"))
        output_pm = _per_million(pricing.get("completion"))
        # text models only carry meaningful token pricing; skip image-only/free-of-token
        # rows and OpenRouter's negative "-1" variable/unavailable sentinels.
        if input_pm is None or output_pm is None or input_pm < 0 or output_pm < 0:
            continue
        provider = mid.split("/", 1)[0]
        family_id = _family(mid)
        ent_id = f"deployment/{_slug(mid)}"
        arch = m.get("architecture") or {}
        result.entities.append(EntityRecord(
            entity_id=ent_id, display_name=m.get("name") or mid, entity_type="deployment",
            organization=provider, family_id=family_id,
            metadata={
                "openrouter_id": mid,
                "canonical_slug": m.get("canonical_slug"),
                "modality": arch.get("modality"),
                "context_length": m.get("context_length"),
                "knowledge_cutoff": m.get("knowledge_cutoff"),
                "join_key": family_id,
            },
        ))
        result.prices.append(PriceRecord(
            source_id=SOURCE_ID, deployment_id=f"openrouter/{mid}", entity_id=ent_id,
            family_id=family_id, currency="USD", context_tokens=m.get("context_length"),
            as_of=as_of,
            input_usd_per_million=input_pm, output_usd_per_million=output_pm,
            cached_input_usd_per_million=_per_million(pricing.get("input_cache_read")),
            cache_write_usd_per_million=_per_million(pricing.get("input_cache_write")),
            metadata={
                "web_search_usd_per_call": pricing.get("web_search"),
                "modality": arch.get("modality"),
                "openrouter_id": mid,
            },
        ))
        result.aliases.append({
            "source_id": SOURCE_ID, "source_model_name": mid, "entity_id": ent_id,
            "family_id": family_id, "mapping_note": "openrouter deployment id",
        })
    return result


def _slug(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def _family(openrouter_id: str) -> str:
    """provider/model family, dropping route variants like ':free' or ':nitro'."""
    base = openrouter_id.split(":", 1)[0]
    return _slug(base)
