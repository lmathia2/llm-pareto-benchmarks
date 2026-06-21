"""Natural-language → decision-profile compiler (Doc-2 §17).

We do NOT let an LLM invent SQL or weights. User language is compiled into a
*versioned, auditable decision profile* via deterministic rules, and the
interpreted profile is always shown back to the user. This keeps recommendations
reproducible and explainable: the same question always compiles to the same
profile, and every weight/constraint is traceable to a phrase in the query.

compile_query("for deep research, best model with a good quality/cost tradeoff")
  -> (profile_dict, interpretation_notes)
"""
from __future__ import annotations

import re

# Task family -> the benchmark families that constitute it (matches adapter task_family tags)
FAMILY_DIMS = {
    "reasoning": ["reasoning"],
    "math": ["math"],
    "coding_agent": ["coding_agent"],
    "finance": ["finance"],
    "preference": ["preference"],
    "multimodal": ["multimodal"],
    "long_context": ["__context__"],
}

# Intent keywords -> task families to weight (with relative emphasis)
TASK_PATTERNS = [
    ("deep research", {"reasoning": 0.45, "long_context": 0.25, "preference": 0.15, "coding_agent": 0.15}),
    ("research",      {"reasoning": 0.45, "long_context": 0.25, "preference": 0.15, "coding_agent": 0.15}),
    ("finance",       {"finance": 0.45, "reasoning": 0.35, "preference": 0.10, "long_context": 0.10}),
    ("coding agent",  {"coding_agent": 0.60, "reasoning": 0.25, "long_context": 0.15}),
    ("agent",         {"coding_agent": 0.50, "reasoning": 0.35, "long_context": 0.15}),
    ("coding",        {"coding_agent": 0.60, "reasoning": 0.25, "long_context": 0.15}),
    ("code",          {"coding_agent": 0.60, "reasoning": 0.25, "long_context": 0.15}),
    ("math",          {"math": 0.60, "reasoning": 0.40}),
    ("chat",          {"reasoning": 0.55, "preference": 0.25, "long_context": 0.20}),
    ("multimodal",    {"multimodal": 0.55, "reasoning": 0.30, "long_context": 0.15}),
    ("document",      {"multimodal": 0.50, "reasoning": 0.35, "long_context": 0.15}),
    ("long context",  {"long_context": 0.40, "reasoning": 0.45, "preference": 0.15}),
]

DEFAULT_TASK = {"reasoning": 0.55, "preference": 0.25, "long_context": 0.20}

# Workload presets per broad task (token totals for one job)
WORKLOAD_PRESETS = {
    "deep research": dict(input_tokens=225_000, output_tokens=75_000, calls=20, fixed_tool_cost_usd=0.10),
    "research":      dict(input_tokens=225_000, output_tokens=75_000, calls=20, fixed_tool_cost_usd=0.10),
    "coding":        dict(input_tokens=400_000, output_tokens=120_000, reasoning_tokens=40_000, calls=30, retry_multiplier=1.1),
    "agent":         dict(input_tokens=400_000, output_tokens=120_000, reasoning_tokens=40_000, calls=30, retry_multiplier=1.1),
    "chat":          dict(input_tokens=4_000, output_tokens=1_000, calls=1),
    "_default":      dict(input_tokens=50_000, output_tokens=15_000, calls=5),
}


def _detect_task(q: str) -> tuple[dict, str]:
    for kw, weights in TASK_PATTERNS:
        if kw in q:
            return weights, kw
    return DEFAULT_TASK, "general"


def _detect_objective(q: str) -> str:
    has_quality = any(w in q for w in ["best", "highest quality", "most capable", "smartest", "top"])
    has_cost = any(w in q for w in ["cheap", "cheapest", "lowest cost", "low cost", "budget", "inexpensive", "affordable"])
    has_tradeoff = any(w in q for w in ["tradeoff", "trade-off", "balance", "good quality/cost", "quality/cost",
                                        "value", "bang for", "cost-effective", "cost effective"])
    if has_tradeoff or (has_quality and has_cost):
        return "tradeoff"
    if has_cost:
        return "cost"
    if has_quality:
        return "quality"
    return "tradeoff"


def _detect_budget(q: str) -> float | None:
    # "$3", "under 2.50", "below $5", "per research/run/job"
    m = re.search(r"(?:under|below|less than|max|within|budget of)?\s*\$?\s*(\d+(?:\.\d+)?)\s*(?:usd|dollars?)?", q)
    # only treat as budget if a budget cue is present near a number
    if re.search(r"(under|below|less than|budget|max|within|cheap|\$)\s*\$?\s*\d", q) and m:
        return float(m.group(1))
    return None


def _detect_context(q: str) -> int | None:
    m = re.search(r"(\d+)\s*[kK]\s*(?:token|context|ctx|window)", q)
    if m:
        return int(m.group(1)) * 1000
    if "long context" in q or "long-context" in q:
        return 200_000
    return None


def compile_query(query: str, as_of: str = "today") -> tuple[dict, dict]:
    q = query.lower().strip()
    task_weights, task_kw = _detect_task(q)
    objective = _detect_objective(q)
    budget = _detect_budget(q)
    min_ctx = _detect_context(q)

    # weights -> dimension_map (only families with weight)
    weights = {k: round(v, 3) for k, v in task_weights.items() if v > 0}
    dim_map = {k: FAMILY_DIMS[k] for k in weights}

    # workload preset
    wl_key = next((k for k in WORKLOAD_PRESETS if k in q), "_default")
    workload = dict(WORKLOAD_PRESETS[wl_key])

    constraints = {"require_price": True, "budget_basis": "p95", "min_evidence_coverage": 0.30}
    if budget is not None:
        constraints["max_cost_usd"] = budget
    if min_ctx is not None:
        constraints["min_context_tokens"] = min_ctx

    name = f"adhoc_{task_kw.replace(' ', '_')}_{objective}"
    profile = {
        "profile": {"name": name, "as_of": as_of, "description": f"Compiled from query: {query!r}"},
        "constraints": constraints,
        "workload": workload,
        "uncertainty": {"p95_token_multiplier": 1.35, "p95_tool_multiplier": 1.15},
        "weights": weights,
        "dimension_map": dim_map,
        "policy": {"missing_prior": 0.5, "missing_penalty": 0.1, "context_reference_tokens": 1_000_000},
        "_selection": objective,
    }
    interpretation = {
        "detected_task": task_kw,
        "objective": objective,
        "budget_usd": budget,
        "min_context_tokens": min_ctx,
        "weights": weights,
        "workload_preset": wl_key,
        "selection_rule": objective,
    }
    return profile, interpretation
