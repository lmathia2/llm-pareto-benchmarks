"""Plotly figure builders (no Streamlit side effects, so they're unit-testable).
Requires the `viz` extra (plotly)."""
from __future__ import annotations


def pareto_figure(result: dict):
    import plotly.graph_objects as go

    fr = result["frontier"]
    dom = result["dominated"]
    default = result.get("recommended_default")
    fig = go.Figure()

    if dom:
        fig.add_trace(go.Scatter(
            x=[d["cost"] for d in dom], y=[d["quality"] for d in dom],
            mode="markers", name="dominated",
            marker=dict(color="lightgray", size=8),
            text=[d["name"] for d in dom],
            hovertemplate="%{text}<br>q=%{y}<br>$%{x}<extra></extra>",
        ))
    if fr:
        fr_sorted = sorted(fr, key=lambda c: c["p95_cost"])
        fig.add_trace(go.Scatter(
            x=[c["p95_cost"] for c in fr_sorted], y=[c["quality_0_100"] for c in fr_sorted],
            mode="lines+markers", name="Pareto frontier",
            line=dict(color="#2563eb", width=2), marker=dict(color="#2563eb", size=11),
            text=[c["deployment_id"] for c in fr_sorted],
            customdata=[[c["coverage"], c["context_tokens"]] for c in fr_sorted],
            hovertemplate="%{text}<br>quality %{y}<br>p95 $%{x}<br>coverage %{customdata[0]}<extra></extra>",
        ))
    if default:
        fig.add_trace(go.Scatter(
            x=[default["p95_cost"]], y=[default["quality_0_100"]],
            mode="markers", name="recommended",
            marker=dict(color="#f59e0b", size=22, symbol="star", line=dict(color="black", width=1)),
            text=[default["deployment_id"]],
            hovertemplate="⭐ %{text}<br>quality %{y}<br>p95 $%{x}<extra></extra>",
        ))
    fig.update_layout(
        xaxis_title="p95 cost per job (USD, log)", yaxis_title="quality (0–100)",
        xaxis_type="log", height=520, legend=dict(orientation="h", y=1.02, x=0),
        margin=dict(l=10, r=10, t=30, b=10),
    )
    return fig


def coverage_heatmap(models: list[str], benchmarks: list[str], z: list[list]):
    """Models × benchmarks normalized-score heatmap. Empty cells (no evidence)
    render as gaps, making the honest coverage holes visible."""
    import plotly.graph_objects as go

    fig = go.Figure(go.Heatmap(
        z=z, x=benchmarks, y=models, colorscale="Viridis", zmin=0, zmax=1,
        colorbar=dict(title="norm"), hoverongaps=False,
        hovertemplate="%{y}<br>%{x}<br>norm=%{z:.2f}<extra></extra>",
    ))
    fig.update_layout(
        height=max(360, 18 * len(models)), margin=dict(l=10, r=10, t=30, b=10),
        xaxis=dict(side="top", tickangle=-40), yaxis=dict(autorange="reversed"),
    )
    return fig


def router_figure(route_result: dict):
    """Eligible candidates as quality-vs-cost points, colored by pass/fail of the
    risk threshold, with the chosen (cheapest-passing) point starred."""
    import plotly.graph_objects as go

    elig = route_result.get("eligible_points", [])
    chosen = route_result.get("decision")
    thr = route_result["request"]["effective_threshold"]
    passing = [e for e in elig if e["predicted_pass"] >= thr]
    failing = [e for e in elig if e["predicted_pass"] < thr]
    fig = go.Figure()
    if failing:
        fig.add_trace(go.Scatter(
            x=[e["cost"] for e in failing], y=[e["quality_0_100"] for e in failing],
            mode="markers", name="below threshold", marker=dict(color="lightgray", size=9),
            text=[e["deployment_id"] for e in failing],
            hovertemplate="%{text}<br>q=%{y}<br>$%{x}<extra></extra>"))
    if passing:
        fig.add_trace(go.Scatter(
            x=[e["cost"] for e in passing], y=[e["quality_0_100"] for e in passing],
            mode="markers", name="passing", marker=dict(color="#16a34a", size=11),
            text=[e["deployment_id"] for e in passing],
            hovertemplate="%{text}<br>q=%{y}<br>$%{x}<extra></extra>"))
    if chosen:
        fig.add_trace(go.Scatter(
            x=[chosen["cost"]], y=[chosen["quality_0_100"]], mode="markers", name="chosen (cheapest passing)",
            marker=dict(color="#f59e0b", size=22, symbol="star", line=dict(color="black", width=1)),
            text=[chosen["deployment_id"]], hovertemplate="⭐ %{text}<br>q=%{y}<br>$%{x}<extra></extra>"))
    fig.update_layout(
        xaxis_title="p95 cost per job (USD, log)", yaxis_title="quality / predicted pass (0–100)",
        xaxis_type="log", height=460, legend=dict(orientation="h", y=1.02, x=0),
        margin=dict(l=10, r=10, t=30, b=10))
    return fig


def routes_figure(routes: list[dict]):
    """Provider routes for one model family: input $/M per provider, colored by
    uptime. Robust to null throughput/latency (which OpenRouter populates
    intermittently)."""
    import plotly.graph_objects as go

    rows = [r for r in routes if r.get("input_usd_per_million") is not None]
    if not rows:
        return go.Figure()
    labels = [f"{r['provider']}" + (f" ({r['quantization']})" if r.get("quantization") not in (None, "unknown") else "")
              for r in rows]
    up = [r.get("uptime_pct_30m") for r in rows]
    fig = go.Figure(go.Bar(
        x=[r["input_usd_per_million"] for r in rows], y=labels, orientation="h",
        marker=dict(color=[u if u is not None else 0 for u in up], colorscale="RdYlGn",
                    cmin=90, cmax=100, colorbar=dict(title="uptime% 30m")),
        customdata=[[r.get("output_usd_per_million"), r.get("throughput_tps_30m"), r.get("uptime_pct_30m")]
                    for r in rows],
        hovertemplate="%{y}<br>$%{x}/M in · $%{customdata[0]}/M out<br>tps=%{customdata[1]}<br>uptime=%{customdata[2]}%<extra></extra>",
    ))
    fig.update_layout(
        xaxis_title="input price (USD / M tokens)", height=max(300, 30 * len(rows)),
        yaxis=dict(autorange="reversed"), margin=dict(l=10, r=10, t=30, b=10))
    return fig
