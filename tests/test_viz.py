"""Pareto figure builder test (no Streamlit needed)."""
import pytest

pytest.importorskip("plotly")
from llm_pareto.viz import pareto_figure


def test_pareto_figure_builds_traces():
    result = {
        "frontier": [
            {"deployment_id": "a", "p95_cost": 0.1, "quality_0_100": 80, "coverage": 0.9, "context_tokens": 200000},
            {"deployment_id": "b", "p95_cost": 0.5, "quality_0_100": 90, "coverage": 1.0, "context_tokens": 100000},
        ],
        "dominated": [{"name": "c", "cost": 0.4, "quality": 70}],
        "recommended_default": {"deployment_id": "a", "p95_cost": 0.1, "quality_0_100": 80},
    }
    fig = pareto_figure(result)
    names = {t.name for t in fig.data}
    assert {"Pareto frontier", "dominated", "recommended"} <= names
    # log x-axis for cost
    assert fig.layout.xaxis.type == "log"


def test_pareto_figure_empty_frontier():
    fig = pareto_figure({"frontier": [], "dominated": [], "recommended_default": None})
    assert len(fig.data) == 0  # nothing to plot, no crash
