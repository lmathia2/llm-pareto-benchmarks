"""Orchestration helpers used by the CLI: registry import, source ingest,
normalization recompute, and integrity checks."""
from __future__ import annotations

import csv
import importlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .models import SourceRecord
from .normalization import METHOD_VERSION, tie_aware_ecdf
from .store import Store

# adapter_id -> (module path, fetch fn name)
LIVE_ADAPTERS = {
    "openevals": ("llm_pareto.adapters.openevals", "fetch_live"),
    "openrouter": ("llm_pareto.adapters.openrouter", "fetch_live"),
    "lmarena": ("llm_pareto.adapters.lmarena", "fetch_live"),
    # Tier-B/C (expanded scope): aider is cleanly accessible; artificial_analysis is
    # terms-gated and records a blocked condition unless explicitly opted in.
    "aider_polyglot": ("llm_pareto.adapters.aider_polyglot", "fetch_live"),
    "artificial_analysis": ("llm_pareto.adapters.artificial_analysis", "fetch_live"),
    "vendor_claims": ("llm_pareto.adapters.vendor_claims", "fetch_live"),
    "hf_official": ("llm_pareto.adapters.hf_official", "fetch_live"),
    # third-party benchmark aggregator (free Data API, key-gated; fail-soft like AA)
    "llm_stats": ("llm_pareto.adapters.llm_stats", "fetch_live"),
    "provider_pricing": ("llm_pareto.adapters.provider_pricing", None),  # seed-file driven
}


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def import_registry(store: Store, csv_path: str | Path) -> int:
    """Load the curated census CSV into sources. Backbone adapters overwrite
    their own rows on ingest; the rest remain as registered stubs."""
    n = 0
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            store.upsert_source(SourceRecord(
                source_id=row["source_id"], name=row["name"], url=row["primary_url"],
                layer=row["layer"], domain=row["domain"], access_method=row["data_access"],
                status=row["status"], as_of=None, license_or_terms=row["license_or_terms"],
                metadata={
                    "owner": row["owner"], "ingestion_tier": row["ingestion_tier"],
                    "machine_readable": row["machine_readable"], "freshness": row["freshness"],
                    "primary_metrics": row["primary_metrics"], "notes": row["notes"],
                    "adapter": "stub",
                },
            ))
            n += 1
    store.conn.commit()
    return n


def ingest_source(store: Store, source: str, as_of: str | None = None,
                  use_fixture: str | None = None, save_fixture: bool = True) -> dict:
    as_of = as_of or today()
    mod_path, fetch_name = LIVE_ADAPTERS[source]
    mod = importlib.import_module(mod_path)

    if source == "provider_pricing":
        result = mod.parse(None, as_of)
        ids = store.write_result(result, parser_version=getattr(mod, "PARSER_VERSION", "1.0.0"))
        store.conn.commit()
        return {"source": source, "observations": len(result.observations),
                "prices": len(result.prices), "snapshot_id": None}

    if use_fixture:
        from .fetch import load_fixture
        snap = load_fixture(getattr(mod, "SOURCE_ID"), use_fixture)
        raw_path = snap.persist()
        store.record_snapshot(snap.snapshot_id, snap.source_id, snap.retrieved_at, snap.sha256,
                              snap.url, raw_path, snap.http_status, snap.terms_note, {"fixture": use_fixture})
    else:
        snap = getattr(mod, fetch_name)()
        raw_path = snap.persist()
        store.record_snapshot(snap.snapshot_id, snap.source_id, snap.retrieved_at, snap.sha256,
                              snap.url, raw_path, snap.http_status, snap.terms_note, {})
        if save_fixture:
            _save_fixture(snap)

    result = mod.parse(snap, as_of)
    store.write_result(result, snapshot_id=getattr(snap, "snapshot_id", None),
                       parser_version=getattr(mod, "PARSER_VERSION", "1.0.0"))
    store.conn.commit()
    return {
        "source": source, "as_of": as_of,
        "entities": len(result.entities), "benchmarks": len(result.benchmarks),
        "observations": len(result.observations), "prices": len(result.prices),
        "snapshot_id": getattr(snap, "snapshot_id", None),
    }


def _save_fixture(snap) -> None:
    d = Path("tests/fixtures") / snap.source_id
    d.mkdir(parents=True, exist_ok=True)
    ext = "json" if "json" in (snap.content_type or "") else "txt"
    (d / f"sample.{ext}").write_bytes(snap.content)


def recompute_normalized(store: Store, method: str = METHOD_VERSION) -> dict:
    """Normalize within each benchmark cohort (and ONLY within it)."""
    store.conn.execute("DELETE FROM normalized_observations")
    benches = store.query("SELECT benchmark_id, direction FROM benchmarks")
    total = 0
    for b in benches:
        obs = store.query(
            "SELECT observation_id, entity_id, raw_score FROM observations WHERE benchmark_id=?",
            (b["benchmark_id"],),
        )
        if not obs:
            continue
        points = [(o["observation_id"], o["raw_score"]) for o in obs]
        normed = tie_aware_ecdf(points, direction=b["direction"])
        ent_by_oid = {o["observation_id"]: o["entity_id"] for o in obs}
        for row in normed:
            oid = row["key"]
            store.conn.execute(
                """INSERT OR REPLACE INTO normalized_observations(observation_id,benchmark_id,entity_id,normalized_score,rank,cohort_size,method)
                   VALUES(?,?,?,?,?,?,?)""",
                (oid, b["benchmark_id"], ent_by_oid[oid], row["normalized_score"],
                 row["rank"], row["cohort_size"], method),
            )
            total += 1
    store.conn.commit()
    return {"benchmarks": len(benches), "normalized": total, "method": method}


def integrity_check(store: Store) -> dict:
    out: dict = {}
    out["integrity_check"] = store.conn.execute("PRAGMA integrity_check").fetchone()[0]
    out["foreign_key_violations"] = len(store.query("PRAGMA foreign_key_check"))
    out["normalized_out_of_range"] = store.query(
        "SELECT COUNT(*) c FROM normalized_observations WHERE normalized_score < 0 OR normalized_score > 1"
    )[0]["c"]
    out["orphan_observations"] = store.query(
        "SELECT COUNT(*) c FROM observations o LEFT JOIN benchmarks b ON b.benchmark_id=o.benchmark_id WHERE b.benchmark_id IS NULL"
    )[0]["c"]
    # cohort_size must equal the observation count per benchmark
    mism = store.query(
        """SELECT n.benchmark_id FROM normalized_observations n
           GROUP BY n.benchmark_id
           HAVING MAX(n.cohort_size) != COUNT(*)"""
    )
    out["cohort_size_mismatches"] = len(mism)
    return out
