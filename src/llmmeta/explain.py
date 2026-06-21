"""Turn a recommendation result + interpretation into a written rationale.

Shared by the `ask` CLI command and the dashboard so the text answer is identical
across surfaces. Rationale is grounded strictly in the result (components,
coverage, cost, dominators) — no claims beyond the evidence.
"""
from __future__ import annotations


def answer_text(result: dict, interpretation: dict | None = None, query: str | None = None) -> str:
    d = result.get("recommended_default")
    lines: list[str] = []
    if query:
        lines.append(f"**Question:** {query}")
    if interpretation:
        b = interpretation.get("budget_usd")
        lines.append(
            f"**Interpreted as:** {interpretation['detected_task']} workload, "
            f"objective = *{interpretation['objective']}*"
            + (f", budget ≤ ${b}/job (p95)" if b else "")
            + (f", min context {interpretation['min_context_tokens']:,}" if interpretation.get('min_context_tokens') else "")
            + "."
        )
    lines.append(
        f"_Scored {result['n_candidates']} priced deployments; {result['n_eligible']} met the constraints "
        f"({result['exclusion_count']} excluded). Default chosen by: {result.get('selection_rule','—')}._"
    )
    lines.append("")

    if not d:
        lines.append("**No deployment satisfies these constraints.** Relax the budget, lower the minimum "
                     "context, or reduce the evidence-coverage floor. See exclusions below.")
        return "\n".join(lines)

    comp = ", ".join(
        f"{k} {round(v*100)}" if v is not None else f"{k} —(no evidence)"
        for k, v in d["components"].items()
    )
    lines.append(
        f"## Recommendation: **{d['deployment_id']}**  ({d['provider']})\n\n"
        f"- **Quality {d['quality_0_100']}/100** at **evidence coverage {round(d['coverage']*100)}%**\n"
        f"- **Expected ${d['expected_cost']}/job**, **p95 ${d['p95_cost']}/job**, context {d['context_tokens']:,} tokens\n"
        f"- Component scores (0–100): {comp}\n"
        f"- Price basis: {d['pricing_basis']} (${d['input_usd_per_million']}/M in, ${d['output_usd_per_million']}/M out), "
        f"price as of {d['price_as_of']}"
    )
    lines.append("")

    # rationale: why this one beats the alternatives
    fr = result["frontier"]
    if len(fr) > 1:
        cheaper = [c for c in fr if c["p95_cost"] < d["p95_cost"]]
        better = [c for c in fr if c["quality_0_100"] > d["quality_0_100"]]
        bits = []
        if better:
            top = max(better, key=lambda c: c["quality_0_100"])
            bits.append(f"higher quality is available ({top['deployment_id']} at {top['quality_0_100']}/100) "
                        f"but costs ${top['p95_cost']} vs ${d['p95_cost']}")
        if cheaper:
            cmin = min(cheaper, key=lambda c: c["p95_cost"])
            bits.append(f"cheaper options exist ({cmin['deployment_id']} at ${cmin['p95_cost']}) "
                        f"but drop to {cmin['quality_0_100']}/100")
        if bits:
            lines.append("**Why this point on the frontier:** " + "; ".join(bits) +
                         f". The chosen rule — {result.get('selection_rule','—')} — lands here.")
            lines.append("")

    # honesty about coverage
    if d["coverage"] < 0.6:
        missing = [k for k, v in d["components"].items() if v is None]
        lines.append(f"⚠️ **Coverage caveat:** only {round(d['coverage']*100)}% of the weighted score is backed by "
                     f"observed evidence" + (f" (no data for: {', '.join(missing)})" if missing else "") +
                     "; the rest is a neutral prior with a missing-evidence penalty. Treat as a shortlist, not a verdict.")
        lines.append("")

    return "\n".join(lines)
