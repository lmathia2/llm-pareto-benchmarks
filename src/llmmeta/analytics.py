"""Production analytics backend (spec §21): DuckDB/Parquet export for the
analytics plane. SQLite remains the serving warehouse; DuckDB + Parquet is the
columnar analytics mirror. Postgres DDL is generated for a production serving DB.
"""
from __future__ import annotations

from pathlib import Path

from .store import Store

TABLES = ["sources", "entities", "benchmarks", "observations", "normalized_observations",
          "prices", "aliases", "raw_snapshots", "observation_lineage", "discovery_snapshots"]


def export_parquet(store: Store, out_dir: str | Path) -> dict:
    """Mirror every warehouse table to Parquet via DuckDB (optional dependency)."""
    try:
        import duckdb
    except ImportError:
        return {"ok": False, "reason": "duckdb not installed (pip install '.[analytics]')"}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute(f"ATTACH '{store.db_path}' AS src (TYPE sqlite);")
    written = []
    for t in TABLES:
        path = out / f"{t}.parquet"
        con.execute(f"COPY (SELECT * FROM src.{t}) TO '{path}' (FORMAT parquet);")
        written.append(str(path))
    con.close()
    return {"ok": True, "written": written}


def postgres_ddl(sqlite_schema: str | Path) -> str:
    """Translate the SQLite reference schema to Postgres-flavored DDL (spec §7
    production extensions: SERIAL ids, effective-date ranges)."""
    sql = Path(sqlite_schema).read_text()
    sql = sql.replace("PRAGMA foreign_keys = ON;", "-- Postgres enforces FKs by default")
    sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    sql = sql.replace("TEXT NOT NULL DEFAULT '{}'", "JSONB NOT NULL DEFAULT '{}'::jsonb")
    sql = sql.replace("metadata_json TEXT", "metadata_json JSONB")
    header = (
        "-- Generated Postgres DDL (production serving DB). For production, also add:\n"
        "--   * price_effectivity(valid_from, valid_to, region, provider_route)\n"
        "--   * identity_edges(left,right,relation,confidence,valid_from,valid_to,reviewer)\n"
        "--   * benchmark_protocols(dataset_version,prompt,judge,scaffold,attempts,seed_policy)\n\n"
    )
    return header + sql
