"""Aider Polyglot leaderboard adapter (spec §5 aider_polyglot; agent-system layer).

Real agent-system evidence: each row is a model + the aider scaffold/edit-format,
carrying pass_rate AND cost. We materialize pass_rate_2 (the headline retry-2 pass
rate) as a coding_agent benchmark, and keep cost/latency as metadata. Entities are
agent_systems; the join_key is derived from the `--model` spec in the command so
the evidence can (best-effort) attach to a priced deployment.
"""
from __future__ import annotations

from ..fetch import Snapshot, fetch
from ..models import AdapterResult, BenchmarkRecord, EntityRecord, Observation, SourceRecord
from . import register
from .base import SchemaDriftError, slug

SOURCE_ID = "aider_polyglot"
URL = "https://raw.githubusercontent.com/Aider-AI/aider/main/aider/website/_data/polyglot_leaderboard.yml"
PARSER_VERSION = "1.0.0"
REQUIRED = {"model", "pass_rate_2"}


def fetch_live() -> Snapshot:
    return fetch(SOURCE_ID, URL, terms_note="Aider public result files (Apache-2.0 repo)")


def _model_from_command(cmd: str | None, model: str) -> str:
    if cmd and "--model" in cmd:
        after = cmd.split("--model", 1)[1].strip()
        spec = after.split()[0] if after else model
        return spec
    return model


@register(SOURCE_ID)
def parse(snapshot: Snapshot, as_of: str) -> AdapterResult:
    import yaml
    rows = yaml.safe_load(snapshot.text())
    if not isinstance(rows, list) or not rows:
        raise SchemaDriftError("aider polyglot: expected a non-empty list")
    if not REQUIRED.issubset(set(rows[0].keys())):
        raise SchemaDriftError(f"aider polyglot: missing {REQUIRED - set(rows[0].keys())}")

    res = AdapterResult()
    res.sources.append(SourceRecord(
        source_id=SOURCE_ID, name="Aider Polyglot Leaderboard", url="https://aider.chat/docs/leaderboards/",
        layer="agent system", domain="code editing", access_method="public result files",
        status="active", as_of=as_of, license_or_terms="Apache-2.0 repo; verify before redistribution",
        metadata={"rows": len(rows)},
    ))
    bench_id = f"{SOURCE_ID}/pass_rate_2/{as_of}"
    res.benchmarks.append(BenchmarkRecord(
        benchmark_id=bench_id, source_id=SOURCE_ID, name="Aider Polyglot (pass@2)",
        domain="code editing", task_type="agentic_code_edit", metric_name="pass_rate_2",
        direction="higher_is_better", protocol_version=as_of, publish_date=as_of,
        metadata={"task_family": "coding_agent", "scaffold": "aider", "scale": "0-100"},
    ))
    for r in rows:
        model = r.get("model")
        if model is None or r.get("pass_rate_2") is None:
            continue
        model_spec = _model_from_command(r.get("command"), model)
        ent_id = f"agent/{SOURCE_ID}/{slug(model)}"
        res.entities.append(EntityRecord(
            entity_id=ent_id, display_name=f"{model} (aider)", entity_type="agent_system",
            organization=None, family_id=slug(model_spec),
            metadata={"join_key": slug(model_spec), "scaffold": "aider",
                      "edit_format": r.get("edit_format"),
                      "total_cost_usd": r.get("total_cost"),
                      "seconds_per_case": r.get("seconds_per_case"),
                      "test_cases": r.get("test_cases"), "date": str(r.get("date"))},
        ))
        res.observations.append(Observation(
            source_id=SOURCE_ID, benchmark_id=bench_id, entity_id=ent_id,
            raw_score=float(r["pass_rate_2"]), unit="pass_rate_pct", observed_at=as_of,
            sample_size=r.get("test_cases"), relation="exact_system",
            metadata={"edit_format": r.get("edit_format"), "total_cost_usd": r.get("total_cost")},
        ))
    return res
