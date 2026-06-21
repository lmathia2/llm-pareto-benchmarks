"""Coverage matrix + new figures + router-accepts-dict (dashboard backends)."""
from pathlib import Path

import pytest

from llmmeta.adapters import openevals
from llmmeta.fetch import load_fixture
from llmmeta.pipeline import recompute_normalized
from llmmeta.store import Store
from llmmeta.analysis import coverage_matrix

FIX = Path("tests/fixtures")
AS_OF = "2026-06-18"
pytestmark = pytest.mark.skipif(not (FIX / "hf_openevals" / "sample.json").exists(), reason="fixtures missing")


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "c.db")
    s.init_schema()
    s.write_result(openevals.parse(load_fixture("hf_openevals", "sample.json"), AS_OF))
    recompute_normalized(s)
    return s


def test_coverage_matrix_shape(store):
    models, benches, z = coverage_matrix(store, limit=10)
    assert 0 < len(models) <= 10
    assert len(benches) == 11               # OpenEvals 11 dims
    assert len(z) == len(models)
    assert all(len(row) == len(benches) for row in z)
    # ranked by coverage: first model has >= as many non-null cells as the last
    nn = lambda row: sum(v is not None for v in row)
    assert nn(z[0]) >= nn(z[-1])
    # values in [0,1] or None
    assert all(v is None or 0.0 <= v <= 1.0 for row in z for v in row)


def test_coverage_heatmap_builds():
    plotly = pytest.importorskip("plotly")  # noqa
    from llmmeta.viz import coverage_heatmap
    fig = coverage_heatmap(["m1", "m2"], ["b1", "b2"], [[0.1, None], [0.9, 0.5]])
    assert fig.data[0].type == "heatmap"


def test_router_accepts_profile_dict(store):
    # build a minimal coding profile dict and route on it (no file)
    from llmmeta.router import route
    prof = {
        "profile": {"name": "t"},
        "constraints": {"require_price": True, "min_evidence_coverage": 0.0},
        "workload": {"input_tokens": 1000, "output_tokens": 500, "calls": 1},
        "weights": {"reasoning": 1.0},
        "dimension_map": {"reasoning": ["reasoning"]},
        "policy": {"missing_prior": 0.5, "missing_penalty": 0.1},
    }
    # no prices in this store -> 0 eligible, but it must run and return shape
    rr = route(store, prof, AS_OF, risk_tier="low")
    assert "eligible_points" in rr
    assert rr["request"]["risk_tier"] == "low"


def test_router_figure_builds():
    pytest.importorskip("plotly")
    from llmmeta.viz import router_figure
    rr = {
        "request": {"effective_threshold": 0.5},
        "eligible_points": [
            {"deployment_id": "a", "cost": 0.1, "quality_0_100": 60, "predicted_pass": 0.6, "coverage": 0.8},
            {"deployment_id": "b", "cost": 0.2, "quality_0_100": 40, "predicted_pass": 0.4, "coverage": 0.8},
        ],
        "decision": {"deployment_id": "a", "cost": 0.1, "quality_0_100": 60},
    }
    fig = router_figure(rr)
    names = {t.name for t in fig.data}
    assert "passing" in names and "chosen (cheapest passing)" in names
