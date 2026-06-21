"""Authoritative provider pricing adapter (spec §10.4).

Loads effective-dated prices from config/provider_prices.toml. Only entries
explicitly `confirmed = true` (verified against the official source_url) are
ingested — unverified rows are skipped and reported, never fabricated.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from ..models import AdapterResult, EntityRecord, PriceRecord, SourceRecord
from . import register

SOURCE_ID = "provider_pricing"
SEED_PATH = Path("config/provider_prices.toml")

_PROVIDER_SOURCE = {
    "openai_pricing": ("OpenAI API Pricing", "https://openai.com/api/pricing/", "OpenAI"),
    "anthropic_pricing": ("Anthropic API Pricing", "https://docs.anthropic.com/en/docs/about-claude/pricing", "Anthropic"),
    "google_pricing": ("Google Gemini API Pricing", "https://ai.google.dev/gemini-api/docs/pricing", "Google"),
}


def parse_seed(seed_path: Path, as_of: str) -> tuple[AdapterResult, list[dict]]:
    result = AdapterResult()
    skipped: list[dict] = []
    entries = []
    if seed_path.exists():
        entries = tomllib.loads(seed_path.read_text()).get("price", [])

    seen_sources = set()
    for e in entries:
        sid = e.get("source_id", SOURCE_ID)
        if not e.get("confirmed", False):
            skipped.append({"deployment_id": e.get("deployment_id"), "reason": "unconfirmed"})
            continue
        if sid not in seen_sources:
            name, url, org = _PROVIDER_SOURCE.get(sid, (sid, "", None))
            result.sources.append(SourceRecord(
                source_id=sid, name=name, url=url, layer="deployment", domain="pricing",
                access_method="official documentation", status="active", as_of=as_of,
                license_or_terms="authoritative provider price; snapshot effective date",
            ))
            seen_sources.add(sid)
        ent_id = f"deployment/{e['family_id']}"
        result.entities.append(EntityRecord(
            entity_id=ent_id, display_name=e["deployment_id"], entity_type="deployment",
            organization=_PROVIDER_SOURCE.get(sid, (None, None, None))[2], family_id=e["family_id"],
            metadata={"join_key": e.get("join_key", e["family_id"]), "source_url": e.get("source_url")},
        ))
        result.prices.append(PriceRecord(
            source_id=sid, deployment_id=e["deployment_id"], entity_id=ent_id,
            family_id=e["family_id"], currency=e.get("currency", "USD"),
            context_tokens=e.get("context_tokens"), as_of=e.get("as_of", as_of),
            input_usd_per_million=e.get("input_usd_per_million"),
            output_usd_per_million=e.get("output_usd_per_million"),
            cached_input_usd_per_million=e.get("cached_input_usd_per_million"),
            cache_write_usd_per_million=e.get("cache_write_usd_per_million"),
            metadata={"source_url": e.get("source_url"), "basis": "official"},
        ))
    return result, skipped


@register(SOURCE_ID)
def parse(snapshot, as_of: str) -> AdapterResult:
    result, _ = parse_seed(SEED_PATH, as_of)
    return result
