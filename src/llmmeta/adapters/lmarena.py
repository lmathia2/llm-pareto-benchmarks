"""LM Arena preference adapter (spec §10.3).

Arena is a PREFERENCE signal (Bradley-Terry rating), not task accuracy — kept as
a distinct benchmark identity, never mixed with accuracy on a raw scale.

Access reality (2026-06): the public JSON API returns 403 and the HF leaderboard
dataset is gated; ratings load client-side. So this adapter is fail-soft: if it
receives a parseable ratings payload it emits exact observations; otherwise it
records the source as `partial` with ZERO observations and a blocked note,
rather than fabricating ratings. The preference profile dimension then simply
shows reduced coverage, which the missing-evidence machinery handles honestly.
"""
from __future__ import annotations

from ..fetch import Snapshot, fetch
from ..models import AdapterResult, BenchmarkRecord, EntityRecord, Observation, SourceRecord
from . import register

SOURCE_ID = "lmarena"
API_ENDPOINT = "https://lmarena.ai/api/leaderboard/text"
PARSER_VERSION = "1.0.0"


def fetch_live() -> Snapshot:
    return fetch(SOURCE_ID, API_ENDPOINT, terms_note="LM Arena; preference data, verify terms")


def _extract_rows(payload) -> list[dict]:
    """Best-effort: accept several shapes; return [] if none look like ratings."""
    if isinstance(payload, dict):
        for key in ("leaderboard", "data", "rows", "models"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        return []
    rows = []
    for r in payload:
        if not isinstance(r, dict):
            continue
        rating = r.get("rating") or r.get("arena_score") or r.get("elo") or r.get("score")
        name = r.get("model_name") or r.get("modelName") or r.get("model") or r.get("name")
        if rating is not None and name:
            rows.append({"name": name, "rating": rating,
                         "votes": r.get("votes") or r.get("vote_count"),
                         "ci_lower": r.get("rating_lower"), "ci_upper": r.get("rating_upper"),
                         "organization": r.get("organization") or r.get("provider")})
    return rows


@register(SOURCE_ID)
def parse(snapshot: Snapshot, as_of: str) -> AdapterResult:
    result = AdapterResult()
    try:
        payload = snapshot.json()
    except Exception:
        payload = None
    rows = _extract_rows(payload) if payload is not None else []

    blocked = not rows
    result.sources.append(SourceRecord(
        source_id=SOURCE_ID, name="LM Arena / Chatbot Arena", url="https://lmarena.ai/leaderboard/text",
        layer="model", domain="human preference", access_method="HF dataset/API",
        status="partial-blocked" if blocked else "active", as_of=as_of,
        license_or_terms="source-specific; preference measurement, not accuracy",
        metadata={"blocked": blocked,
                  "note": "API 403 / dataset gated; ratings load client-side" if blocked else "ratings parsed"},
    ))
    if blocked:
        return result

    bench_id = f"{SOURCE_ID}/text_style_control/bradley_terry/{as_of}"
    result.benchmarks.append(BenchmarkRecord(
        benchmark_id=bench_id, source_id=SOURCE_ID, name="LM Arena (text)",
        domain="human preference", task_type="pairwise_preference", metric_name="bradley_terry_rating",
        direction="higher_is_better", protocol_version=as_of, publish_date=as_of,
        metadata={"task_family": "preference", "pool": "text_style_control"},
    ))
    for r in rows:
        org = r.get("organization") or "unknown"
        ent_id = f"{_slug(org)}/{_slug(r['name'])}"
        result.entities.append(EntityRecord(
            entity_id=ent_id, display_name=r["name"], entity_type="model",
            organization=org, family_id=ent_id, metadata={"join_key": _slug(r["name"])},
        ))
        result.observations.append(Observation(
            source_id=SOURCE_ID, benchmark_id=bench_id, entity_id=ent_id,
            raw_score=float(r["rating"]), unit="bradley_terry", observed_at=as_of,
            sample_size=r.get("votes"), lower_bound=r.get("ci_lower"), upper_bound=r.get("ci_upper"),
            relation="exact",
        ))
    return result


def _slug(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
