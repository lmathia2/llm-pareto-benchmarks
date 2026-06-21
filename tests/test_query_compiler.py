"""NL → profile compiler tests (Doc-2 §17): deterministic + auditable."""
from llmmeta.query_compiler import compile_query


def test_deep_research_tradeoff():
    prof, interp = compile_query(
        "for deep research what's the best model we can use that provides a good quality/cost tradeoff")
    assert interp["detected_task"] in ("deep research", "research")
    assert interp["objective"] == "tradeoff"
    assert "reasoning" in prof["weights"]
    assert prof["_selection"] == "tradeoff"
    # weights normalize to the dimension_map keys
    assert set(prof["weights"]) == set(prof["dimension_map"])


def test_cost_objective_and_budget():
    prof, interp = compile_query("cheapest coding agent under $2")
    assert interp["objective"] == "cost"
    assert interp["budget_usd"] == 2.0
    assert prof["constraints"]["max_cost_usd"] == 2.0
    assert prof["weights"]["coding_agent"] >= prof["weights"]["reasoning"]


def test_quality_objective():
    prof, interp = compile_query("best possible model for math, money no object")
    assert interp["objective"] == "quality"
    assert "math" in prof["weights"]


def test_context_detection():
    prof, interp = compile_query("long context summarization with 200k token window")
    assert interp["min_context_tokens"] == 200_000
    assert prof["constraints"]["min_context_tokens"] == 200_000


def test_deterministic():
    a, _ = compile_query("finance research, good value")
    b, _ = compile_query("finance research, good value")
    assert a == b  # same query -> same compiled profile, always
