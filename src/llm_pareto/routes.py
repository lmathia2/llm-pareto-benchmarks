"""Provider-route comparison (OpenRouter /endpoints).

The same model family is served by several providers, each a distinct DEPLOYMENT
with its own price, quantization, uptime, and (when published) latency/throughput.
This is the spec's provider-routing layer (artificial_analysis_providers) made
live: do not conflate base-model quality with serving economics.

Quality lives in the warehouse (per family); routes are fetched live per family
on demand, so we don't bloat the warehouse with hundreds of serving rows.
throughput/latency are intermittently null upstream — reported honestly as None.
"""
from __future__ import annotations

from .fetch import fetch

ENDPOINTS = "https://openrouter.ai/api/v1/models/{slug}/endpoints"


def _per_million(s) -> float | None:
    try:
        v = float(s) * 1_000_000
        return round(v, 6) if v >= 0 else None
    except (TypeError, ValueError):
        return None


def parse_routes(payload: dict) -> list[dict]:
    """Normalize the /endpoints payload into comparable route rows."""
    data = payload.get("data", payload)
    rows = []
    for e in data.get("endpoints", []):
        pr = e.get("pricing") or {}
        rows.append({
            "provider": e.get("provider_name"),
            "quantization": e.get("quantization"),
            "context_tokens": e.get("context_length"),
            "max_output_tokens": e.get("max_completion_tokens"),
            "input_usd_per_million": _per_million(pr.get("prompt")),
            "output_usd_per_million": _per_million(pr.get("completion")),
            "cached_input_usd_per_million": _per_million(pr.get("input_cache_read")),
            "throughput_tps_30m": e.get("throughput_last_30m"),
            "latency_s_30m": e.get("latency_last_30m"),
            "uptime_pct_30m": e.get("uptime_last_30m"),
            "status": e.get("status"),
        })
    # cheapest input first; unknown prices last
    rows.sort(key=lambda r: (r["input_usd_per_million"] is None, r["input_usd_per_million"] or 0))
    return rows


def fetch_provider_routes(slug: str) -> list[dict]:
    """Live fetch + parse routes for one OpenRouter model slug (e.g. 'qwen/qwen3.5-397b-a17b')."""
    snap = fetch("openrouter_endpoints", ENDPOINTS.format(slug=slug),
                 terms_note="OpenRouter provider routes")
    return parse_routes(snap.json())
