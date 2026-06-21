# Methodology

This document explains the assumptions behind every derived number. The guiding rule: **preserve what
each source measured, normalize only where comparison is valid, expose missingness and proxy
assumptions, estimate the user's actual workload cost, and return transparent trade-offs.**

## 1. Four evidence layers, never blended raw

We separate (1) model capability benchmarks, (2) preference/judge evaluations, (3) agent-system
results (model + scaffold + tools), and (4) deployment economics (price/latency/throughput). These have
different units and semantics. A Bradley-Terry rating, a pass rate, a composite index, and a dollar
price are **never** averaged on a raw scale.

## 2. Benchmark identity = protocol identity

A `benchmark_id` is `source/task/metric/generation`. It changes whenever any comparability-critical
property changes: dataset version, prompt/shots, judge or reference model, scaffold, attempts/pass@k,
tools, style control, or publication window. A later retrieval date creates a **new generation**; old
snapshots are preserved. Old and new generations may be displayed together but never share a
normalization cohort.

## 3. Normalization — tie-aware empirical CDF (`tie-aware-ecdf-v1`)

Within one `benchmark_id` cohort only:
1. direction-adjust (`x = s` if higher-is-better else `-s`);
2. sort, assign zero-based positions; tied values share the averaged position;
3. `z = mean_position / (n-1)` for `n>1`, else `0.5`.

A unique worst → 0, unique best → 1. Monotone and unit-free; it deliberately discards cardinal
distance, which is the right trade-off for heterogeneous aggregation but not a substitute for reading
raw scores. Competition rank (1,2,2,4) is stored alongside. Implementation: `normalization.py`;
the rule is enforced structurally — `pipeline.recompute_normalized` groups strictly by `benchmark_id`.

## 4. Identity & proxy transfer

Model, deployment, and agent-system are distinct entity types. We **never** merge by fuzzy string
similarity; normalized names only *propose* aliases for review (`aliases` table). Quality (model
evidence) is joined to price (deployment evidence) by a conservative `join_key` (slug of the model
name / model spec). This under-joins rather than mis-joins — cross-source coverage is therefore partial
and reported honestly via the `coverage` field, not hidden.

Proxy evidence is shrunk toward a neutral prior (`identity.shrink_to_prior`):
`transferred = prior + strength·(observed − prior)`, with policy strengths (exact 0.95, family 0.75,
system→family 0.80). Transfer strengths are **policy choices, not measured constants**, and are exposed
in every result's `relations`.

## 5. Missing evidence (`scoring.weighted_quality`)

Missing evidence is neither failure nor certainty. For each missing dimension we impute a neutral prior
for the arithmetic, but track coverage and apply a penalty:

```
coverage = Σ(weights of observed dims) / Σ(weights)
quality  = Σ(wᵢ·imputedᵢ)/Σwᵢ − missing_penalty·(1 − coverage)
```

Every recommendation reports **both** quality and coverage; profiles can set a `min_evidence_coverage`
constraint so candidates whose score is mostly imputed prior are excluded.

## 6. Cost (`cost.estimate_cost`)

Cost is workload-specific. Token fields are totals across one job. With separate prices:
`(I·in + O·out + C·cache_read + W·cache_write)/1e6`, `O` including reasoning tokens, all scaled by a
retry multiplier; fixed tool cost added. `p95 = token_cost·p95_token_mult + fixed·p95_tool_mult`.
Prices are effective-dated; for a query `as_of` we pick the latest price at/under that date.

## 7. Task-typed scoring lens (Doc-1 → profiles)

A profile maps each weighted dimension to a set of Doc-1 task families via `[dimension_map]`. Per
candidate, each dimension value is the mean of the normalized scores of all benchmarks tagged with
those families (joined by `join_key`); `__context__` is the capacity feature `min(1, ctx/reference)`.
This is why the same warehouse yields different winners per task.

## 7a. Self-reported vendor numbers (`adapters/vendor_claims.py`)

Proprietary frontier models rarely appear in open third-party leaderboards, so we ingest vendor
self-reported numbers from model cards/announcements — but only after the adapter **fetches the cited
page and verifies the score literally appears near the benchmark keyword** (confidence `strong` =
adjacent, `weak` = present-but-not-adjacent, `absent` = skipped). This caught a real mis-claim during
the build (a GPT-5.1 HLE number not present on the cited page was rejected). Self-reported scores are a
`self_reported`, mixed-protocol benchmark generation, grouped per benchmark across vendors so
proprietary models can be ranked against each other — **with the loud caveat that vendor protocols
differ** — and never share a cohort with third-party harness runs. Small cohorts (e.g. 3 models)
compress normalized scores toward 0/0.5/1; this is a real artifact, surfaced via coverage and the
`self_reported` relation, not hidden.

## 8. Eligibility & Pareto (`pareto.py`)

Candidates are filtered by named predicates (price required, min context, max p95 cost, min coverage)
— each exclusion records the first failed predicate. Among eligible candidates, `a` dominates `b` if
`quality(a) ≥ quality(b)` and `cost(a) ≤ cost(b)` with one strict. The frontier is the non-dominated
set; each dominated candidate gets a concrete dominator and a plain-language reason.

## 9. Pre-call router (`router.py`, Doc-1)

The router makes the single online decision: predict `P(pass|x,c)` per candidate (the task-typed
quality is the proxy), keep those clearing the risk-tier threshold `q(x)`, pick the **cheapest-passing**.
It reports savings vs always picking the top-quality model and flags escalation when nothing passes or
the chosen route has thin evidence. **Limitation:** with leaderboard *aggregates* only, the estimator
is the proxy; true calibration (Doc-1 §4.5) needs per-item pass/fail labels — `router.calibrate` is the
hook, intentionally not fit on aggregates.

## Limitations & threats to validity

1. Benchmark coverage is incomplete and uneven.
2. Agent benchmarks confound model and scaffold (tooling/retries can dominate).
3. Preference/judge evaluations have pool and judge effects; they are not universal utility.
4. Contamination/gaming remain possible — prefer time-stamped/refreshed evals.
5. Context capacity ≠ effective long-context performance.
6. Prices and routes change rapidly — effective-dating is required.
7. Family transfer introduces assumptions — proxy strength is reported; run sensitivity analysis.
8. ECDF loses cardinal distance.
9. Identity joins are conservative (exact-key) — coverage is partial by design, not hidden.
10. **Public benchmarks should shortlist, not certify.** Run a private, identical-scaffold acceptance
    test (Doc-2 §25) before promoting a candidate to production.
