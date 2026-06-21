"""Read-side analysis helpers (warehouse -> matrices/tables for visualization).
Kept separate from viz.py so figure builders stay dependency-light and testable."""
from __future__ import annotations

import json

from .store import Store


def coverage_matrix(store: Store, limit: int = 40) -> tuple[list[str], list[str], list[list]]:
    """Return (models, benchmarks, z) where z[i][j] is the normalized score of
    model i on benchmark j (None if no evidence). Models are ranked by how many
    benchmarks they cover (descending), so the honest gaps are visible at a glance.
    """
    rows = store.query(
        """SELECT n.entity_id, e.display_name AS dn, n.benchmark_id, b.name AS bname,
                  b.source_id AS src, n.normalized_score AS nz, b.metadata_json AS bmeta
           FROM normalized_observations n
           JOIN entities e ON e.entity_id = n.entity_id
           JOIN benchmarks b ON b.benchmark_id = n.benchmark_id
           WHERE e.entity_type = 'model'"""
    )
    if not rows:
        return [], [], []

    # short, stable, source-tagged labels so distinct cohorts never collapse
    # (e.g. third-party vs self-reported SWE-bench stay separate columns).
    src_abbr = {"hf_openevals": "oe", "vendor_claims": "vendor", "lmarena": "arena",
                "aider_polyglot": "aider", "hf_official_leaderboard": "hfo"}
    bench_label: dict[str, str] = {}
    for r in rows:
        if r["benchmark_id"] not in bench_label:
            short = r["bname"].split("(")[0].strip()[:18]
            src = src_abbr.get(r["src"], r["src"][:6])
            bench_label[r["benchmark_id"]] = f"{short} [{src}]"

    benches = sorted(bench_label.values())
    by_model: dict[str, dict[str, float]] = {}
    name_of: dict[str, str] = {}
    for r in rows:
        m = r["entity_id"]
        name_of[m] = r["dn"]
        by_model.setdefault(m, {})[bench_label[r["benchmark_id"]]] = r["nz"]

    ranked = sorted(by_model.items(), key=lambda kv: -len(kv[1]))[:limit]
    models = [name_of[m] for m, _ in ranked]
    z = [[scores.get(b) for b in benches] for _, scores in ranked]
    return models, benches, z


def list_join_keys(store: Store) -> list[tuple[str, str]]:
    """(join_key, a display name) for every model family that has evidence."""
    rows = store.query(
        """SELECT DISTINCT json_extract(e.metadata_json,'$.join_key') AS jk, e.display_name AS dn
           FROM normalized_observations n JOIN entities e ON e.entity_id = n.entity_id
           WHERE e.entity_type='model' AND jk IS NOT NULL ORDER BY dn"""
    )
    seen, out = set(), []
    for r in rows:
        if r["jk"] and r["jk"] not in seen:
            seen.add(r["jk"])
            out.append((r["jk"], r["dn"]))
    return out


def list_openrouter_slugs(store: Store, limit: int = 200) -> list[str]:
    """OpenRouter base slugs (no ':route' variant) present in the warehouse, for
    the provider-route comparison picker."""
    rows = store.query(
        """SELECT DISTINCT json_extract(metadata_json,'$.openrouter_id') AS oid
           FROM entities WHERE entity_type='deployment' AND oid IS NOT NULL"""
    )
    slugs = sorted({r["oid"].split(":", 1)[0] for r in rows if r["oid"]})
    return slugs[:limit]


def lineage_for(store: Store, join_key: str) -> dict:
    """Full evidence trail for a model family: every observation with its raw +
    normalized score, source, retrieval date, source URL / verifying snippet, and
    the raw-snapshot checksum/URI when lineage was recorded."""
    obs = store.query(
        """SELECT b.name AS bench, b.source_id AS src, b.metadata_json AS bmeta,
                  o.raw_score AS raw, o.observed_at AS obs_at, o.relation AS rel,
                  o.metadata_json AS ometa, o.observation_id AS oid,
                  n.normalized_score AS nz, n.rank AS rk, n.cohort_size AS cs,
                  e.display_name AS dn
           FROM observations o
           JOIN entities e ON e.entity_id = o.entity_id
           JOIN benchmarks b ON b.benchmark_id = o.benchmark_id
           LEFT JOIN normalized_observations n ON n.observation_id = o.observation_id
           WHERE json_extract(e.metadata_json,'$.join_key') = ?
           ORDER BY b.source_id, b.name""",
        (join_key,),
    )
    evidence = []
    for r in obs:
        om = json.loads(r["ometa"] or "{}")
        snap = store.query(
            """SELECT s.uri, s.retrieved_at, s.sha256, l.parser_version, l.source_row_locator
               FROM observation_lineage l JOIN raw_snapshots s ON s.snapshot_id = l.snapshot_id
               WHERE l.observation_id = ?""",
            (r["oid"],),
        )
        sp = dict(snap[0]) if snap else {}
        evidence.append({
            "benchmark": r["bench"], "source": r["src"], "model_label": r["dn"],
            "raw_score": r["raw"], "normalized": r["nz"], "rank": r["rk"], "cohort_size": r["cs"],
            "relation": r["rel"], "observed_at": r["obs_at"],
            "source_url": om.get("source_url"), "confidence": om.get("confidence"),
            "verifying_snippet": om.get("verifying_snippet"),
            "snapshot_uri": sp.get("uri"), "retrieved_at": sp.get("retrieved_at"),
            "snapshot_sha256": (sp.get("sha256") or "")[:12], "parser_version": sp.get("parser_version"),
        })

    prices = store.query(
        """SELECT p.deployment_id, p.source_id, p.as_of, p.input_usd_per_million AS inp,
                  p.output_usd_per_million AS outp, p.context_tokens AS ctx, p.metadata_json AS pmeta
           FROM prices p JOIN entities e ON e.entity_id = p.entity_id
           WHERE p.family_id = ? OR json_extract(e.metadata_json,'$.join_key') = ?
           ORDER BY p.input_usd_per_million""",
        (join_key, join_key),
    )
    price_rows = []
    for r in prices:
        pm = json.loads(r["pmeta"] or "{}")
        price_rows.append({
            "deployment_id": r["deployment_id"], "source": r["source_id"], "as_of": r["as_of"],
            "input_usd_per_million": r["inp"], "output_usd_per_million": r["outp"],
            "context_tokens": r["ctx"], "source_url": pm.get("source_url"), "basis": pm.get("basis"),
        })
    return {"join_key": join_key, "evidence": evidence, "prices": price_rows,
            "n_observations": len(evidence), "n_price_records": len(price_rows)}
