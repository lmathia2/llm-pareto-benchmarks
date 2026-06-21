"""SQLite warehouse: schema bootstrap + idempotent upserts (spec §7, §6.4).

The store is the single write path. Adapters never touch SQL directly; they
return AdapterResult and the ingest pipeline calls store.write_result(). This
keeps idempotency and provenance in one place.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Optional

from .models import (
    AdapterResult,
    BenchmarkRecord,
    EntityRecord,
    Observation,
    PriceRecord,
    SourceRecord,
)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "docs" / "schema.sql"


class Store:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    # ---- lifecycle -------------------------------------------------------
    def init_schema(self, schema_path: str | Path = SCHEMA_PATH) -> None:
        sql = Path(schema_path).read_text()
        self.conn.executescript(sql)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.conn.commit()
        self.close()

    # ---- upserts ---------------------------------------------------------
    def upsert_source(self, s: SourceRecord) -> None:
        self.conn.execute(
            """INSERT INTO sources(source_id,name,url,layer,domain,access_method,status,as_of,license_or_terms,metadata_json)
               VALUES(?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source_id) DO UPDATE SET
                 name=excluded.name, url=excluded.url, layer=excluded.layer, domain=excluded.domain,
                 access_method=excluded.access_method, status=excluded.status, as_of=excluded.as_of,
                 license_or_terms=excluded.license_or_terms, metadata_json=excluded.metadata_json""",
            (s.source_id, s.name, s.url, s.layer, s.domain, s.access_method, s.status,
             s.as_of, s.license_or_terms, json.dumps(s.metadata)),
        )

    def upsert_entity(self, e: EntityRecord) -> None:
        self.conn.execute(
            """INSERT INTO entities(entity_id,display_name,entity_type,organization,family_id,metadata_json)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(entity_id) DO UPDATE SET
                 display_name=excluded.display_name, entity_type=excluded.entity_type,
                 organization=excluded.organization, family_id=excluded.family_id,
                 metadata_json=excluded.metadata_json""",
            (e.entity_id, e.display_name, e.entity_type, e.organization, e.family_id,
             json.dumps(e.metadata)),
        )

    def upsert_benchmark(self, b: BenchmarkRecord) -> None:
        self.conn.execute(
            """INSERT INTO benchmarks(benchmark_id,source_id,name,domain,task_type,metric_name,direction,protocol_version,publish_date,metadata_json)
               VALUES(?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(benchmark_id) DO UPDATE SET
                 source_id=excluded.source_id, name=excluded.name, domain=excluded.domain,
                 task_type=excluded.task_type, metric_name=excluded.metric_name,
                 direction=excluded.direction, protocol_version=excluded.protocol_version,
                 publish_date=excluded.publish_date, metadata_json=excluded.metadata_json""",
            (b.benchmark_id, b.source_id, b.name, b.domain, b.task_type, b.metric_name,
             b.direction, b.protocol_version, b.publish_date, json.dumps(b.metadata)),
        )

    def upsert_observation(self, o: Observation) -> int:
        """Idempotent on the natural key (source,benchmark,entity,observed_at,relation)."""
        cur = self.conn.execute(
            """INSERT INTO observations(source_id,benchmark_id,entity_id,raw_score,unit,observed_at,sample_size,standard_error,lower_bound,upper_bound,relation,metadata_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source_id,benchmark_id,entity_id,observed_at,relation) DO UPDATE SET
                 raw_score=excluded.raw_score, unit=excluded.unit, sample_size=excluded.sample_size,
                 standard_error=excluded.standard_error, lower_bound=excluded.lower_bound,
                 upper_bound=excluded.upper_bound, metadata_json=excluded.metadata_json""",
            (o.source_id, o.benchmark_id, o.entity_id, o.raw_score, o.unit, o.observed_at,
             o.sample_size, o.standard_error, o.lower_bound, o.upper_bound, o.relation,
             json.dumps(o.metadata)),
        )
        if cur.lastrowid:
            row = self.conn.execute(
                "SELECT observation_id FROM observations WHERE source_id=? AND benchmark_id=? AND entity_id=? AND observed_at=? AND relation=?",
                (o.source_id, o.benchmark_id, o.entity_id, o.observed_at, o.relation),
            ).fetchone()
            return row["observation_id"]
        return -1

    def upsert_price(self, p: PriceRecord) -> None:
        self.conn.execute(
            """INSERT INTO prices(source_id,deployment_id,entity_id,family_id,currency,context_tokens,as_of,
                 blended_usd_per_million,input_usd_per_million,cached_input_usd_per_million,cache_write_usd_per_million,
                 output_usd_per_million,median_tokens_per_second,latency_first_chunk_seconds,total_response_seconds,metadata_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source_id,deployment_id,as_of) DO UPDATE SET
                 entity_id=excluded.entity_id, family_id=excluded.family_id, currency=excluded.currency,
                 context_tokens=excluded.context_tokens, blended_usd_per_million=excluded.blended_usd_per_million,
                 input_usd_per_million=excluded.input_usd_per_million,
                 cached_input_usd_per_million=excluded.cached_input_usd_per_million,
                 cache_write_usd_per_million=excluded.cache_write_usd_per_million,
                 output_usd_per_million=excluded.output_usd_per_million,
                 median_tokens_per_second=excluded.median_tokens_per_second,
                 latency_first_chunk_seconds=excluded.latency_first_chunk_seconds,
                 total_response_seconds=excluded.total_response_seconds, metadata_json=excluded.metadata_json""",
            (p.source_id, p.deployment_id, p.entity_id, p.family_id, p.currency, p.context_tokens,
             p.as_of, p.blended_usd_per_million, p.input_usd_per_million, p.cached_input_usd_per_million,
             p.cache_write_usd_per_million, p.output_usd_per_million, p.median_tokens_per_second,
             p.latency_first_chunk_seconds, p.total_response_seconds, json.dumps(p.metadata)),
        )

    def upsert_alias(self, source_id: str, source_model_name: str, entity_id: str,
                     family_id: Optional[str] = None, mapping_note: Optional[str] = None) -> None:
        self.conn.execute(
            """INSERT INTO aliases(source_id,source_model_name,entity_id,family_id,mapping_note)
               VALUES(?,?,?,?,?)
               ON CONFLICT(source_id,source_model_name) DO UPDATE SET
                 entity_id=excluded.entity_id, family_id=excluded.family_id, mapping_note=excluded.mapping_note""",
            (source_id, source_model_name, entity_id, family_id, mapping_note),
        )

    def record_snapshot(self, snapshot_id: str, source_id: str, retrieved_at: str, sha256: str,
                        uri: str, raw_object_path: str, http_status: Optional[int],
                        terms_note: Optional[str], metadata: dict[str, Any]) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO raw_snapshots(snapshot_id,source_id,retrieved_at,sha256,uri,raw_object_path,http_status,terms_note,metadata_json)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (snapshot_id, source_id, retrieved_at, sha256, uri, raw_object_path, http_status,
             terms_note, json.dumps(metadata)),
        )

    def link_lineage(self, observation_id: int, snapshot_id: str, locator: str, parser_version: str) -> None:
        if observation_id < 0:
            return
        self.conn.execute(
            "INSERT OR REPLACE INTO observation_lineage(observation_id,snapshot_id,source_row_locator,parser_version) VALUES(?,?,?,?)",
            (observation_id, snapshot_id, locator, parser_version),
        )

    def record_discovery(self, as_of: str, key: str, members: Iterable[str],
                         changes: Optional[dict[str, str]] = None) -> None:
        changes = changes or {}
        for m in members:
            self.conn.execute(
                "INSERT OR REPLACE INTO discovery_snapshots(as_of,discovery_key,member,change) VALUES(?,?,?,?)",
                (as_of, key, m, changes.get(m, "present")),
            )

    def write_result(self, result: AdapterResult, snapshot_id: Optional[str] = None,
                     parser_version: str = "1.0.0") -> list[int]:
        """Persist a full AdapterResult; returns observation ids for lineage/normalization."""
        for s in result.sources:
            self.upsert_source(s)
        for e in result.entities:
            self.upsert_entity(e)
        for b in result.benchmarks:
            self.upsert_benchmark(b)
        obs_ids: list[int] = []
        for o in result.observations:
            oid = self.upsert_observation(o)
            obs_ids.append(oid)
            if snapshot_id:
                self.link_lineage(oid, snapshot_id, f"{o.benchmark_id}::{o.entity_id}", parser_version)
        for p in result.prices:
            self.upsert_price(p)
        for a in result.aliases:
            self.upsert_alias(**a)
        self.conn.commit()
        return obs_ids

    # ---- reads -----------------------------------------------------------
    def latest_discovery(self, key: str) -> tuple[Optional[str], set[str]]:
        row = self.conn.execute(
            "SELECT MAX(as_of) AS d FROM discovery_snapshots WHERE discovery_key=?", (key,)
        ).fetchone()
        if not row or not row["d"]:
            return None, set()
        as_of = row["d"]
        members = {
            r["member"]
            for r in self.conn.execute(
                "SELECT member FROM discovery_snapshots WHERE discovery_key=? AND as_of=? AND change != 'removed'",
                (key, as_of),
            )
        }
        return as_of, members

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return list(self.conn.execute(sql, params))

    def latest_data_date(self) -> Optional[str]:
        """Most recent snapshot date present (max over price + observation dates).
        Used as the default `as_of` so queries hit whatever was last ingested."""
        row = self.conn.execute(
            "SELECT MAX(d) AS d FROM (SELECT MAX(as_of) d FROM prices UNION ALL SELECT MAX(observed_at) FROM observations)"
        ).fetchone()
        return row["d"] if row and row["d"] else None
