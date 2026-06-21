"""Doc-1 pre-call router: cheapest-passing model selection (Doc-1 §1, §8).

Where the meta-leaderboard returns a Pareto frontier, the router makes the
single online decision Doc-1 describes:

    observe request state  ->  predict P(pass | x, c) for each candidate
    ->  keep candidates clearing the risk/quality threshold  ->  pick the cheapest

It reuses the task-typed quality from recommend.build_candidates as the pre-call
success estimator. Quality (0..1) is the predicted pass-probability proxy; a
risk tier raises the required threshold q(x). The chosen candidate is the
cheapest-passing one — i.e. the cheapest config likely to clear the bar for this
call, not the strongest model.

Honest limitation: with leaderboard *aggregates* only, the estimator IS the
proxy, so reported oracle-regret is structural, not measured. True calibration
(Doc-1 §4.5) needs per-item pass/fail labels; the module exposes the hook
(`calibrate`) and reports coverage so low-evidence routes can escalate.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .recommend import build_candidates, eligibility_predicates, load_profile
from .pareto import filter_eligible
from .store import Store

# Default risk -> minimum predicted pass-probability (on quality/100 scale).
RISK_THRESHOLDS = {"low": 0.50, "medium": 0.65, "high": 0.80, "critical": 0.90}


def predict_pass(quality_0_100: float, calibration=None) -> float:
    """Map task-typed quality to a pass probability. Default: monotone identity
    proxy. `calibration` (a fitted function) can replace it once per-item labels
    exist."""
    p = max(0.0, min(1.0, quality_0_100 / 100.0))
    return calibration(p) if calibration else p


def route(
    store: Store,
    profile: "str | Path | dict",
    as_of: str,
    quality_threshold: Optional[float] = None,
    risk_tier: str = "low",
    budget_max: Optional[float] = None,
    min_coverage: float = 0.30,
    calibration=None,
) -> dict:
    prof = profile if isinstance(profile, dict) else load_profile(profile)
    cons = dict(prof.get("constraints", {}))
    router_cfg = prof.get("router", {})
    thresholds = {**RISK_THRESHOLDS, **router_cfg.get("risk_thresholds", {})}

    # effective threshold: explicit value wins, else the risk-tier floor
    q = quality_threshold if quality_threshold is not None else thresholds.get(risk_tier, 0.5)
    if q > 1.0:  # accept 0..100 input
        q = q / 100.0

    # apply a budget override if provided
    if budget_max is not None:
        cons["max_cost_usd"] = budget_max
    cons.setdefault("min_evidence_coverage", min_coverage)

    candidates = build_candidates(store, prof, as_of)
    eligible, exclusions = filter_eligible(candidates, eligibility_predicates(cons))

    # attach predicted pass-prob; passing = clears threshold
    scored = []
    for c in eligible:
        pp = predict_pass(c.quality, calibration)
        scored.append((c, pp))
    passing = [(c, pp) for c, pp in scored if pp >= q]

    chosen = min(passing, key=lambda t: t[0].cost) if passing else None
    # the always-frontier baseline: the highest-quality eligible candidate
    top = max(eligible, key=lambda c: c.quality) if eligible else None

    def _row(c, pp=None):
        d = dict(c.payload)
        d["predicted_pass"] = round(pp if pp is not None else predict_pass(c.quality, calibration), 4)
        d["cost"] = c.cost
        return d

    result = {
        "profile": prof.get("profile", {}).get("name"),
        "as_of": as_of,
        "request": {"risk_tier": risk_tier, "effective_threshold": round(q, 4),
                    "budget_max": cons.get("max_cost_usd"), "min_coverage": cons.get("min_evidence_coverage")},
        "n_candidates": len(candidates),
        "n_eligible": len(eligible),
        "n_passing": len(passing),
        "decision": _row(*chosen) if chosen else None,
        "always_frontier_baseline": _row(top) if top else None,
        "eligible_points": [_row(c, pp) for c, pp in scored],
    }
    if chosen and top:
        saved = round(top.cost - chosen[0].cost, 4)
        result["savings_vs_always_top"] = {
            "abs_usd": saved,
            "pct": round(100 * saved / top.cost, 1) if top.cost else 0.0,
            "chosen_is_top": chosen[0].name == top.name,
        }
    # under-routing / escalation guard: chose something with thin evidence
    if chosen and chosen[0].payload["coverage"] < min_coverage + 0.15:
        result["escalation_flag"] = "low evidence coverage on the chosen route — consider escalation/abstention"
    if not passing:
        result["escalation_flag"] = "no candidate clears the threshold under budget — escalate or relax constraints"
    result["exclusions_sample"] = exclusions[:10]
    return result


def calibrate(labels):  # pragma: no cover - hook for future per-item calibration
    """Placeholder for Doc-1 §4.5 calibration. `labels` = [(predicted, passed)];
    returns a monotone mapping fit (e.g. isotonic). Not fit on aggregates."""
    raise NotImplementedError("Per-item pass/fail labels required for calibration.")
