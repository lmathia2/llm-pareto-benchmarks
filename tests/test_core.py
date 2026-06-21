"""Core engine unit tests — baseline asserts from spec §20.1."""
from llmmeta.normalization import tie_aware_ecdf
from llmmeta.scoring import weighted_quality
from llmmeta.cost import Workload, estimate_cost
from llmmeta.pareto import Candidate, pareto_frontier, dominates
from llmmeta.identity import shrink_to_prior


def _score(rows, key):
    return next(r["normalized_score"] for r in rows if r["key"] == key)


def _rank(rows, key):
    return next(r["rank"] for r in rows if r["key"] == key)


def test_tie_aware_normalization():
    rows = tie_aware_ecdf([("a", 10), ("b", 20), ("c", 20), ("d", 40)])
    assert _score(rows, "a") == 0.0
    assert _score(rows, "b") == _score(rows, "c") == 0.5
    assert _score(rows, "d") == 1.0
    # competition rank: best=1, tie at second share rank 2, then rank 4
    assert _rank(rows, "d") == 1
    assert _rank(rows, "b") == _rank(rows, "c") == 2
    assert _rank(rows, "a") == 4


def test_lower_is_better():
    rows = tie_aware_ecdf([("fast", 1), ("slow", 10)], "lower_is_better")
    assert _score(rows, "fast") == 1.0
    assert _score(rows, "slow") == 0.0


def test_single_element_cohort():
    rows = tie_aware_ecdf([("only", 7)])
    assert _score(rows, "only") == 0.5
    assert rows[0]["cohort_size"] == 1


def test_missing_evidence_penalty():
    quality, coverage, values = weighted_quality(
        {"a": 1.0, "b": None}, {"a": 0.5, "b": 0.5},
        missing_prior=0.5, missing_penalty=0.1,
    )
    assert round(quality, 8) == 0.70
    assert coverage == 0.5
    assert values["b"] == 0.5


def test_cost_baseline():
    wl = Workload(input_tokens=225_000, output_tokens=75_000, fixed_tool_cost_usd=0.10)
    expected, p95, basis = estimate_cost(
        wl, blended_price=3.85, p95_token_multiplier=1.35, p95_tool_multiplier=1.15
    )
    assert round(expected, 6) == 1.255
    assert round(p95, 6) == 1.67425
    assert "blended" in basis


def test_cost_separate_prices_and_cache_fallback():
    wl = Workload(input_tokens=1_000_000, output_tokens=1_000_000, cached_input_tokens=1_000_000)
    # cached price falls back to input price when unspecified
    expected, _, basis = estimate_cost(wl, input_price=1.0, output_price=2.0)
    assert round(expected, 6) == 4.0  # 1 (input) + 2 (output) + 1 (cache→input)
    assert "separate" in basis


def test_pareto_baseline():
    rows = [
        Candidate("a", 1.0, 2.0, {}),
        Candidate("b", 0.8, 1.0, {}),
        Candidate("c", 0.7, 1.5, {}),
    ]
    names = {c.name for c in pareto_frontier(rows)}
    assert names == {"a", "b"}
    assert dominates(rows[1], rows[2])  # b dominates c


def test_shrink_to_prior():
    assert shrink_to_prior(1.0, 0.8, prior=0.5) == 0.9
    assert shrink_to_prior(0.0, 0.8, prior=0.5) == pytest_approx(0.1)
    assert shrink_to_prior(None, 0.8) is None


def pytest_approx(x, tol=1e-9):
    class _A:
        def __eq__(self, other):
            return abs(other - x) < tol
    return _A()
