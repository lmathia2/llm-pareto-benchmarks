"""Profile-driven recommendation engine (spec §13, §15, §16).

Pipeline: resolve priced deployment candidates -> gather task-typed quality
evidence (joined model->deployment by normalized family key) -> weighted quality
+ coverage -> workload cost (expected & p95) -> eligibility filter -> cost-quality
Pareto frontier -> recommended default + alternatives + exclusions + lineage.

The "task-typed scoring lens": a profile maps each weighted dimension to a set of
Doc-1 task families; the same warehouse therefore yields different winners per task.
"""
from __future__ import annotations

import json
import tomllib
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

from .cost import Workload, estimate_cost
from .pareto import Candidate, best_dominator, filter_eligible, pareto_frontier
from .scoring import weighted_quality
from .store import Store

CONTEXT_SENTINEL = "__context__"


def load_profile(path: str | Path) -> dict:
    return tomllib.loads(Path(path).read_text())


def _family_scores(store: Store) -> dict[str, dict[str, list[float]]]:
    """join_key -> task_family -> [normalized scores] across all model observations."""
    rows = store.query(
        """SELECT n.normalized_score AS ns, b.metadata_json AS bmeta, e.metadata_json AS emeta,
                  e.entity_id AS eid
           FROM normalized_observations n
           JOIN benchmarks b ON b.benchmark_id = n.benchmark_id
           JOIN entities e ON e.entity_id = n.entity_id"""
    )
    out: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        bmeta = json.loads(r["bmeta"] or "{}")
        emeta = json.loads(r["emeta"] or "{}")
        family = bmeta.get("task_family")
        if not family:
            continue
        join_key = emeta.get("join_key") or r["eid"]
        out[join_key][family].append(r["ns"])
    return out


def _latest_prices(store: Store, as_of: str) -> list[dict]:
    """Latest price per deployment at/under as_of, with entity context."""
    rows = store.query(
        """SELECT p.*, e.metadata_json AS emeta, e.display_name AS dname, e.organization AS org
           FROM prices p JOIN entities e ON e.entity_id = p.entity_id
           WHERE p.as_of <= ?""",
        (as_of,),
    )
    best: dict[str, dict] = {}
    for r in rows:
        d = dict(r)
        key = r["deployment_id"]
        if key not in best or r["as_of"] > best[key]["as_of"]:
            best[key] = d
    return list(best.values())


def _dimension_value(dim_families: list[str], fam_scores: dict[str, list[float]],
                     context_tokens: Optional[int], ref_tokens: int) -> tuple[Optional[float], str]:
    if dim_families == [CONTEXT_SENTINEL]:
        if not context_tokens:
            return None, "no_context"
        return min(1.0, context_tokens / ref_tokens), "capacity_feature"
    vals: list[float] = []
    for fam in dim_families:
        vals.extend(fam_scores.get(fam, []))
    if not vals:
        return None, "no_evidence"
    return sum(vals) / len(vals), "model_to_deployment_family"


def build_candidates(store: Store, prof: dict, as_of: str) -> list[Candidate]:
    """Score every priced deployment under a profile (task-typed quality + cost).
    Shared by the Pareto recommender and the pre-call router."""
    weights: dict[str, float] = prof["weights"]
    dim_map: dict[str, list[str]] = prof.get("dimension_map", {})
    cons = prof.get("constraints", {})
    wl_cfg = prof.get("workload", {})
    unc = prof.get("uncertainty", {})
    policy = prof.get("policy", {})

    ref_tokens = int(policy.get("context_reference_tokens", 1_000_000))
    missing_prior = float(policy.get("missing_prior", 0.5))
    missing_penalty = float(policy.get("missing_penalty", 0.1))
    budget_basis = cons.get("budget_basis", "p95")

    workload = Workload(
        input_tokens=int(wl_cfg.get("input_tokens", 0)),
        output_tokens=int(wl_cfg.get("output_tokens", 0)),
        cached_input_tokens=int(wl_cfg.get("cached_input_tokens", 0)),
        cache_write_tokens=int(wl_cfg.get("cache_write_tokens", 0)),
        reasoning_tokens=int(wl_cfg.get("reasoning_tokens", 0)),
        calls=int(wl_cfg.get("calls", 1)),
        retry_multiplier=float(wl_cfg.get("retry_multiplier", 1.0)),
        fixed_tool_cost_usd=float(wl_cfg.get("fixed_tool_cost_usd", 0.0)),
    )

    fam_scores_by_key = _family_scores(store)
    priced = _latest_prices(store, as_of)

    candidates: list[Candidate] = []
    for p in priced:
        emeta = json.loads(p["emeta"] or "{}")
        join_key = emeta.get("join_key") or p["family_id"]
        fam_scores = fam_scores_by_key.get(join_key, {})
        context_tokens = p["context_tokens"] or emeta.get("context_length")

        components: dict[str, Optional[float]] = {}
        relations: dict[str, str] = {}
        for dim, w in weights.items():
            fams = dim_map.get(dim, [dim])
            val, rel = _dimension_value(fams, fam_scores, context_tokens, ref_tokens)
            components[dim] = val
            relations[dim] = rel

        quality, coverage, imputed = weighted_quality(
            components, weights, missing_prior=missing_prior, missing_penalty=missing_penalty
        )

        # cost
        if p["input_usd_per_million"] is not None and p["output_usd_per_million"] is not None:
            expected, p95, basis = estimate_cost(
                workload, input_price=p["input_usd_per_million"], output_price=p["output_usd_per_million"],
                cached_input_price=p["cached_input_usd_per_million"],
                cache_write_price=p["cache_write_usd_per_million"],
                p95_token_multiplier=float(unc.get("p95_token_multiplier", 1.35)),
                p95_tool_multiplier=float(unc.get("p95_tool_multiplier", 1.15)),
            )
        elif p["blended_usd_per_million"] is not None:
            expected, p95, basis = estimate_cost(
                workload, blended_price=p["blended_usd_per_million"],
                p95_token_multiplier=float(unc.get("p95_token_multiplier", 1.35)),
                p95_tool_multiplier=float(unc.get("p95_tool_multiplier", 1.15)),
            )
        else:
            continue

        cost_for_ranking = p95 if budget_basis == "p95" else expected
        candidates.append(Candidate(
            name=p["deployment_id"], quality=round(quality * 100, 2), cost=round(cost_for_ranking, 4),
            payload={
                "deployment_id": p["deployment_id"], "display_name": p["dname"],
                "provider": p["org"], "family_id": p["family_id"], "join_key": join_key,
                "quality_0_100": round(quality * 100, 2), "coverage": round(coverage, 3),
                "expected_cost": round(expected, 4), "p95_cost": round(p95, 4),
                "context_tokens": context_tokens, "components": {k: (round(v, 3) if v is not None else None) for k, v in components.items()},
                "imputed_components": {k: round(v, 3) for k, v in imputed.items()},
                "relations": relations, "pricing_basis": basis,
                "input_usd_per_million": p["input_usd_per_million"],
                "output_usd_per_million": p["output_usd_per_million"],
                "source_id": p["source_id"], "price_as_of": p["as_of"],
            },
        ))
    return candidates


def eligibility_predicates(cons: dict):
    """Build named eligibility predicates from profile constraints (spec §15)."""
    max_cost = cons.get("max_cost_usd")
    min_ctx = cons.get("min_context_tokens")
    require_price = cons.get("require_price", True)
    min_cov = cons.get("min_evidence_coverage")
    preds = []
    if require_price:
        preds.append(("missing_price", lambda c: c.payload["input_usd_per_million"] is not None or c.payload.get("blended")))
    if min_ctx:
        preds.append((f"context_below_{min_ctx}", lambda c, m=min_ctx: (c.payload["context_tokens"] or 0) >= m))
    if max_cost is not None:
        preds.append((f"over_budget_{max_cost}", lambda c, mc=max_cost: c.cost <= mc))
    if min_cov is not None:
        preds.append((f"coverage_below_{min_cov}", lambda c, mv=min_cov: c.payload["coverage"] >= mv))
    return preds


def _knee_point(frontier: list[Candidate]) -> Candidate | None:
    """Pick the frontier point with the best quality-per-cost balance: normalize
    quality and cost to [0,1] across the frontier, return the point closest to the
    ideal (max quality, min cost) corner. Good default for 'tradeoff' objectives."""
    if not frontier:
        return None
    if len(frontier) == 1:
        return frontier[0]
    qs = [c.quality for c in frontier]
    cs = [c.cost for c in frontier]
    qlo, qhi = min(qs), max(qs)
    clo, chi = min(cs), max(cs)
    qr = (qhi - qlo) or 1.0
    cr = (chi - clo) or 1.0
    best, best_d = None, 1e9
    for c in frontier:
        nq = (c.quality - qlo) / qr           # 1 = best quality
        nc = (c.cost - clo) / cr              # 0 = cheapest
        d = (1 - nq) ** 2 + nc ** 2           # distance to ideal corner
        if d < best_d:
            best, best_d = c, d
    return best


def run_profile(store: Store, prof: dict, as_of: str, selection: str = "quality") -> dict:
    """Core engine on a compiled profile dict. `selection` picks the headline
    default: 'quality' (top of frontier), 'cost' (cheapest frontier), or
    'tradeoff'/'balanced' (knee point)."""
    weights = prof["weights"]
    dim_map = prof.get("dimension_map", {})
    cons = prof.get("constraints", {})
    wl_cfg = prof.get("workload", {})

    candidates = build_candidates(store, prof, as_of)
    preds = eligibility_predicates(cons)
    eligible, exclusions = filter_eligible(candidates, preds)
    frontier = pareto_frontier(eligible)
    frontier.sort(key=lambda c: (-c.quality, c.cost))

    dominated = []
    for c in eligible:
        if c in frontier:
            continue
        dom = best_dominator(c, frontier)
        dominated.append({
            "name": c.name, "quality": c.quality, "cost": c.cost,
            "dominated_by": dom.name if dom else None,
            "reason": (f"{dom.name} has quality {dom.quality} vs {c.quality} at cost ${dom.cost} vs ${c.cost}"
                       if dom else "dominated"),
        })

    if selection == "cost":
        default = min(frontier, key=lambda c: c.cost) if frontier else None
        rule = "lowest-cost frontier member"
    elif selection in ("tradeoff", "balanced", "knee"):
        default = _knee_point(frontier)
        rule = "knee point (best quality/cost balance)"
    else:
        default = frontier[0] if frontier else None
        rule = "highest-quality frontier member"

    return {
        "profile": prof.get("profile", {}),
        "as_of": as_of,
        "weights": weights,
        "dimension_map": dim_map,
        "workload": wl_cfg,
        "selection_rule": rule,
        "n_candidates": len(candidates),
        "n_eligible": len(eligible),
        "recommended_default": default.payload if default else None,
        "frontier": [c.payload for c in frontier],
        "dominated": sorted(dominated, key=lambda d: -d["quality"])[:25],
        "exclusions": exclusions[:50],
        "exclusion_count": len(exclusions),
    }


def recommend(store: Store, profile_path: str | Path, as_of: str, selection: str = "quality") -> dict:
    return run_profile(store, load_profile(profile_path), as_of, selection=selection)
