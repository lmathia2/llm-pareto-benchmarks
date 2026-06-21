"""Recommendation + catalog exports with lineage (spec §18, §19)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .store import Store


def write_recommendation(result: dict, output_dir: str | Path) -> dict[str, str]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    name = result.get("profile", {}).get("name", "profile")

    (out / f"{name}.json").write_text(json.dumps(result, indent=2))
    md = _markdown(result)
    (out / f"{name}.md").write_text(md)

    fcols = ["deployment_id", "provider", "access", "evidence", "quality_0_100", "coverage",
             "expected_cost", "p95_cost", "context_tokens", "pricing_basis", "price_as_of"]
    with open(out / f"{name}_pareto.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fcols)
        w.writeheader()
        for r in result["frontier"]:
            w.writerow({k: r.get(k) for k in fcols})
    return {"json": str(out / f"{name}.json"), "md": str(out / f"{name}.md"),
            "pareto_csv": str(out / f"{name}_pareto.csv")}


def _markdown(result: dict) -> str:
    p = result.get("profile", {})
    lines = [f"# Recommendation — {p.get('name','profile')}", ""]
    lines.append(f"_as of {result['as_of']}; {result['n_eligible']}/{result['n_candidates']} candidates eligible; "
                 f"{result['exclusion_count']} excluded._")
    lines.append("")
    d = result.get("recommended_default")
    if d:
        lines += ["## Recommended default", "",
                  f"**{d['deployment_id']}** ({d['provider']}) — quality **{d['quality_0_100']}/100** "
                  f"at coverage {d['coverage']}, expected ${d['expected_cost']}, p95 ${d['p95_cost']}.",
                  f"Component scores: {d['components']}", ""]
    else:
        lines += ["## Recommended default", "", "_No eligible candidate under the profile constraints._", ""]

    lines += ["## Pareto frontier", "",
              "| Deployment | Provider | Access | Evidence | Quality | Coverage | Expected $ | p95 $ | Context |",
              "|---|---|---|---|---:|---:|---:|---:|---:|"]
    for r in result["frontier"]:
        lines.append(f"| {r['deployment_id']} | {r['provider']} | {r.get('access','')} | "
                     f"{r.get('evidence','')} | {r['quality_0_100']} | "
                     f"{r['coverage']} | {r['expected_cost']} | {r['p95_cost']} | {r['context_tokens']} |")
    lines.append("")

    if result["dominated"]:
        lines += ["## Dominated alternatives (top)", ""]
        for dmn in result["dominated"][:10]:
            lines.append(f"- {dmn['name']}: {dmn['reason']}")
        lines.append("")

    lines += ["## Weights & dimension map", "", f"```json\n{json.dumps(result['weights'], indent=2)}\n```",
              f"```json\n{json.dumps(result['dimension_map'], indent=2)}\n```", ""]
    lines += ["## Exclusions (sample)", ""]
    for e in result["exclusions"][:15]:
        lines.append(f"- {e['name']}: {e['reason']}")
    return "\n".join(lines)


def export_catalogs(store: Store, output_dir: str | Path) -> list[str]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    queries = {
        "source_coverage.csv": "SELECT source_id,name,layer,domain,status FROM sources ORDER BY layer,source_id",
        "benchmark_catalog.csv": "SELECT benchmark_id,source_id,name,domain,task_type,metric_name,direction,protocol_version FROM benchmarks ORDER BY benchmark_id",
        "entity_catalog.csv": "SELECT entity_id,display_name,entity_type,organization,family_id FROM entities ORDER BY entity_id",
        "normalized_observations.csv": "SELECT observation_id,benchmark_id,entity_id,normalized_score,rank,cohort_size FROM normalized_observations ORDER BY benchmark_id,rank",
        "pricing_catalog.csv": "SELECT deployment_id,entity_id,family_id,as_of,input_usd_per_million,output_usd_per_million,context_tokens FROM prices ORDER BY deployment_id",
    }
    for fname, sql in queries.items():
        rows = store.query(sql)
        path = out / fname
        with open(path, "w", newline="") as f:
            if rows:
                w = csv.writer(f)
                w.writerow(rows[0].keys())
                for r in rows:
                    w.writerow(list(r))
            else:
                f.write("")
        written.append(str(path))
    return written
