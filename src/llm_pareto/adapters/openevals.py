"""OpenEvals/leaderboard-data adapter (spec §10.2).

Materializes the 11 score columns as 11 SEPARATE benchmark dimensions. The
row-level aggregate_score is NOT normalized — rows cover different benchmark
counts, so it is not a common evidence set; retained only as entity metadata.
Each score column also carries a task-family tag (Doc-1 taxonomy) used by the
task-typed scoring lens.
"""
from __future__ import annotations

import json

from ..fetch import Snapshot, fetch
from ..models import AdapterResult, BenchmarkRecord, EntityRecord, Observation, SourceRecord
from . import register

SOURCE_ID = "hf_openevals"
DATASET = "OpenEvals/leaderboard-data"
ROWS_ENDPOINT = "https://datasets-server.huggingface.co/rows"
PARSER_VERSION = "1.0.0"

# column -> (display name, domain, task_type, task_family)
SCORE_COLUMNS = {
    "aime2026_score":      ("AIME 2026", "mathematics", "competition_math", "math"),
    "evasionBench_score":  ("EvasionBench", "finance/language", "evasive_language_detection", "finance"),
    "gpqa_score":          ("GPQA Diamond", "science", "graduate_science_qa", "reasoning"),
    "gsm8k_score":         ("GSM8K", "mathematics", "grade_school_math", "math"),
    "hle_score":           ("Humanity's Last Exam", "expert_knowledge", "frontier_expert_qa", "reasoning"),
    "hmmt2026_score":      ("HMMT February 2026", "mathematics", "competition_math", "math"),
    "mmluPro_score":       ("MMLU-Pro", "knowledge", "multidomain_mcq", "reasoning"),
    "olmOcr_score":        ("olmOCR-bench", "multimodal/document", "pdf_ocr_parsing", "multimodal"),
    "swePro_score":        ("SWE-bench Pro", "coding/agents", "enterprise_issue_resolution", "coding_agent"),
    "sweVerified_score":   ("SWE-bench Verified", "coding/agents", "validated_issue_resolution", "coding_agent"),
    "terminalBench_score": ("Terminal-Bench 2.0", "agents", "containerized_terminal", "coding_agent"),
}


def fetch_live(page_size: int = 100) -> Snapshot:
    """Paginate the datasets-server until a short page; combine into one snapshot."""
    import httpx
    rows: list = []
    offset = 0
    features = None
    while True:
        r = httpx.get(ROWS_ENDPOINT, params={
            "dataset": DATASET, "config": "default", "split": "train",
            "offset": offset, "length": page_size,
        }, timeout=60).json()
        if features is None:
            features = r.get("features")
        page = r.get("rows", [])
        rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    combined = json.dumps({"features": features, "rows": rows}).encode("utf-8")
    return Snapshot(SOURCE_ID, f"{ROWS_ENDPOINT}?dataset={DATASET}", combined, 200,
                    "application/json", _now(), "HF dataset; verify terms before redistribution")


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@register(SOURCE_ID)
def parse(snapshot: Snapshot, as_of: str) -> AdapterResult:
    data = snapshot.json()
    rows = [r["row"] if "row" in r else r for r in data["rows"]]

    result = AdapterResult()
    result.sources.append(SourceRecord(
        source_id=SOURCE_ID, name="Hugging Face OpenEvals", url=f"https://huggingface.co/datasets/{DATASET}",
        layer="model", domain="cross-domain", access_method="HF datasets-server", status="active",
        as_of=as_of, license_or_terms="source-specific; verify before redistribution",
        metadata={"dataset": DATASET, "num_rows": len(rows)},
    ))

    # benchmark dimensions, dated generation
    for col, (name, domain, task_type, family) in SCORE_COLUMNS.items():
        result.benchmarks.append(BenchmarkRecord(
            benchmark_id=f"{SOURCE_ID}/{col.replace('_score','')}/{as_of}",
            source_id=SOURCE_ID, name=name, domain=domain, task_type=task_type,
            metric_name="score", direction="higher_is_better", protocol_version=as_of,
            publish_date=as_of, metadata={"task_family": family, "column": col, "scale": "0-100"},
        ))

    for row in rows:
        org = row.get("provider") or "unknown"
        model_name = row.get("model_name") or row.get("model_id")
        ent_id = f"{_slug(org)}/{_slug(model_name)}"
        result.entities.append(EntityRecord(
            entity_id=ent_id, display_name=model_name, entity_type="model",
            organization=org, family_id=f"{_slug(org)}/{_slug(model_name)}",
            metadata={
                # join_key bridges to OpenRouter pricing: slug(model_name) == slug(openrouter base id)
                "join_key": _slug(model_name),
                "model_type": row.get("model_type"),
                "parameters_billions": row.get("parameters_billions"),
                "license": row.get("license"),
                "context_window": row.get("context_window"),
                "modality": row.get("modality"),
                "architecture": row.get("architecture"),
                # aggregate kept as metadata only — NOT a normalization cohort
                "openevals_aggregate_score": row.get("aggregate_score"),
                "openevals_coverage_count": row.get("coverage_count"),
                "openevals_coverage_percent": row.get("coverage_percent"),
            },
        ))
        result.aliases.append({
            "source_id": SOURCE_ID, "source_model_name": row.get("model_id"),
            "entity_id": ent_id, "family_id": f"{_slug(org)}/{_slug(model_name)}",
            "mapping_note": "exact openevals model_id",
        })
        for col in SCORE_COLUMNS:
            val = row.get(col)
            if val is None:
                continue
            result.observations.append(Observation(
                source_id=SOURCE_ID, benchmark_id=f"{SOURCE_ID}/{col.replace('_score','')}/{as_of}",
                entity_id=ent_id, raw_score=float(val), unit="score_0_100",
                observed_at=as_of, relation="exact",
                metadata={"column": col},
            ))
    return result


def _slug(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
