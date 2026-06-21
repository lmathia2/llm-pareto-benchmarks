"""Live interactive dashboard for the LLM meta-leaderboard.

Ask a question in plain English -> it compiles to an auditable decision profile,
re-runs the engine, and updates BOTH the cost-quality Pareto chart and a written
rationale. Sliders let you override the compiled budget/weights/risk and watch
the frontier + recommendation recompute live.

    pip install '.[viz]'
    llmmeta dashboard            # or: streamlit run src/llmmeta/dashboard.py
"""
from __future__ import annotations

import os

import streamlit as st

from llmmeta.store import Store
from llmmeta.query_compiler import compile_query
from llmmeta.recommend import run_profile
from llmmeta.explain import answer_text
from llmmeta.viz import pareto_figure, coverage_heatmap, router_figure, routes_figure
from llmmeta.analysis import coverage_matrix, lineage_for, list_join_keys, list_openrouter_slugs
from llmmeta.router import route as route_call
from llmmeta.routes import fetch_provider_routes

DB = os.environ.get("LLMMETA_DB", "outputs/leaderboard.db")

st.set_page_config(page_title="LLM Meta-Leaderboard", layout="wide")


@st.cache_resource
def get_store():
    return Store(DB)


# default to the latest snapshot present so the UI works against any rebuild date
AS_OF = os.environ.get("LLMMETA_AS_OF") or get_store().latest_data_date() or "2026-06-18"

st.title("🧭 LLM Meta-Leaderboard")
st.caption(f"Ask in plain English. Data snapshot: {AS_OF} · warehouse: `{DB}`")

q = st.text_input(
    "Your question",
    value="for deep research what's the best model we can use that provides a good quality/cost tradeoff",
)

prof, interp = compile_query(q, AS_OF)

# ---- live overrides (shared by the Ask and Router tabs) ----
with st.sidebar:
    st.header("Override the compiled profile")
    st.caption("The query sets these; tweak to explore.")
    objective = st.selectbox("Selection rule", ["tradeoff", "quality", "cost"],
                             index=["tradeoff", "quality", "cost"].index(prof["_selection"]))
    budget = st.slider("Max p95 cost / job ($)", 0.0, 10.0,
                       float(prof["constraints"].get("max_cost_usd", 5.0)), 0.05)
    min_cov = st.slider("Min evidence coverage", 0.0, 1.0,
                        float(prof["constraints"].get("min_evidence_coverage", 0.30)), 0.05)
    st.subheader("Dimension weights")
    new_weights = {}
    for dim, w in prof["weights"].items():
        new_weights[dim] = st.slider(dim, 0.0, 1.0, float(w), 0.05)

prof["constraints"]["max_cost_usd"] = budget
prof["constraints"]["min_evidence_coverage"] = min_cov
total = sum(new_weights.values()) or 1.0
prof["weights"] = {k: round(v / total, 3) for k, v in new_weights.items() if v > 0}
prof["dimension_map"] = {k: prof["dimension_map"][k] for k in prof["weights"]}

tab_ask, tab_router, tab_cov, tab_lin, tab_routes = st.tabs(
    ["🔎 Ask & Pareto", "🚦 Router (cheapest-passing)", "🗺️ Coverage", "🔬 Lineage", "🛣️ Routes"])

with tab_ask:
    result = run_profile(get_store(), prof, AS_OF, selection=objective)
    left, right = st.columns([3, 2])
    with left:
        st.subheader("Cost–quality frontier")
        st.plotly_chart(pareto_figure(result), width="stretch")
    with right:
        st.subheader("Answer")
        st.markdown(answer_text(result, {**interp, "objective": objective}, q))
    st.subheader("Pareto frontier")
    if result["frontier"]:
        st.dataframe([
            {"deployment": c["deployment_id"], "provider": c["provider"], "quality": c["quality_0_100"],
             "coverage": c["coverage"], "expected $": c["expected_cost"], "p95 $": c["p95_cost"],
             "context": c["context_tokens"]}
            for c in result["frontier"]
        ], width="stretch", hide_index=True)
    else:
        st.info("No eligible candidates — relax budget / coverage in the sidebar.")
    with st.expander("Interpreted profile (auditable) + exclusions"):
        st.json({"interpretation": interp,
                 "compiled_profile": {k: v for k, v in prof.items() if not k.startswith("_")}})
        st.caption(f"{result['exclusion_count']} excluded; sample:")
        st.dataframe(result["exclusions"][:20], width="stretch", hide_index=True)

with tab_router:
    st.subheader("Pre-call router — cheapest model that clears the bar (Doc-1)")
    st.caption("Picks the cheapest deployment whose predicted pass-probability clears the risk-tier "
               "threshold q(x). Raise the risk tier to demand more quality.")
    risk = st.radio("Risk tier", ["low", "medium", "high", "critical"], horizontal=True)
    # the router accepts the live-edited profile dict directly (same weights/budget)
    rr = route_call(get_store(), prof, AS_OF, risk_tier=risk, budget_max=budget, min_coverage=min_cov)
    c1, c2, c3 = st.columns(3)
    dec = rr.get("decision")
    c1.metric("Chosen", dec["deployment_id"].split("/")[-1] if dec else "— none —",
              f"q={dec['quality_0_100']}" if dec else None)
    c2.metric("Passing / eligible", f"{rr['n_passing']} / {rr['n_eligible']}",
              f"threshold {rr['request']['effective_threshold']}")
    sv = rr.get("savings_vs_always_top")
    c3.metric("Cost vs always-top", f"${dec['cost']}" if dec else "—",
              f"-{sv['pct']}%" if sv else None)
    st.plotly_chart(router_figure(rr), width="stretch")
    if rr.get("escalation_flag"):
        st.warning("⚠️ " + rr["escalation_flag"])
    st.dataframe(sorted(
        [{"deployment": e["deployment_id"], "quality": e["quality_0_100"], "pred_pass": e["predicted_pass"],
          "p95 $": e["cost"], "coverage": e["coverage"],
          "passes": "✅" if e["predicted_pass"] >= rr["request"]["effective_threshold"] else "—"}
         for e in rr["eligible_points"]], key=lambda r: r["p95 $"]),
        width="stretch", hide_index=True)

with tab_cov:
    st.subheader("Benchmark coverage — models × benchmarks")
    st.caption("Normalized score per model per benchmark (within-benchmark). Gaps = no published "
               "evidence. Ranked by how many benchmarks each model covers.")
    topn = st.slider("Show top N models by coverage", 10, 60, 35, 5)
    models, benches, z = coverage_matrix(get_store(), limit=topn)
    if models:
        st.plotly_chart(coverage_heatmap(models, benches, z), width="stretch")
        st.caption(f"{len(models)} models × {len(benches)} benchmark cohorts shown.")
    else:
        st.info("No normalized observations yet — run `llmmeta normalize`.")

with tab_lin:
    st.subheader("Evidence lineage — where every number comes from")
    st.caption("Pick a model family to see each observation with its source, retrieval date, raw + "
               "normalized score, and (for self-reported numbers) the verifying snippet from the page.")
    keys = list_join_keys(get_store())
    if keys:
        labels = [f"{dn}  ·  {jk}" for jk, dn in keys]
        # default to the recommended model's family if present
        default_jk = (result.get("recommended_default") or {}).get("join_key")
        idx = next((i for i, (jk, _) in enumerate(keys) if jk == default_jk), 0)
        pick = st.selectbox("Model family", range(len(keys)), index=idx, format_func=lambda i: labels[i])
        jk = keys[pick][0]
        ln = lineage_for(get_store(), jk)
        st.caption(f"{ln['n_observations']} observations · {ln['n_price_records']} price records")
        st.markdown("**Quality evidence**")
        st.dataframe([
            {"benchmark": e["benchmark"], "source": e["source"], "raw": e["raw_score"],
             "norm": e["normalized"], "relation": e["relation"], "conf": e["confidence"],
             "retrieved": e["retrieved_at"], "sha": e["snapshot_sha256"], "url": e["source_url"]}
            for e in ln["evidence"]
        ], width="stretch", hide_index=True)
        snips = [e for e in ln["evidence"] if e.get("verifying_snippet")]
        if snips:
            with st.expander("Verifying snippets (self-reported numbers found on the cited page)"):
                for e in snips:
                    st.markdown(f"- **{e['benchmark']}** = {e['raw_score']} ({e['confidence']}) — "
                                f"[source]({e['source_url']})\n\n  > …{e['verifying_snippet']}…")
        if ln["prices"]:
            st.markdown("**Price records**")
            st.dataframe(ln["prices"], width="stretch", hide_index=True)
    else:
        st.info("No evidence yet — ingest + normalize first.")

with tab_routes:
    st.subheader("Provider-route comparison (serving layer)")
    st.caption("The same model is served by several providers — each its own price, quantization, "
               "uptime, and (when published) throughput/latency. Serving economics ≠ base-model quality.")
    slugs = list_openrouter_slugs(get_store())
    colA, colB = st.columns([3, 1])
    slug = colA.selectbox("OpenRouter model", slugs,
                          index=(slugs.index("qwen/qwen3.5-397b-a17b") if "qwen/qwen3.5-397b-a17b" in slugs else 0)) \
        if slugs else colA.text_input("OpenRouter slug", "qwen/qwen3.5-397b-a17b")
    if colB.button("Fetch routes", type="primary") or slug:
        try:
            routes = fetch_provider_routes(slug)
        except Exception as e:
            routes = []
            st.error(f"Could not fetch routes: {e}")
        if routes:
            st.caption(f"{len(routes)} provider routes for `{slug}` (live).")
            st.plotly_chart(routes_figure(routes), width="stretch")
            st.dataframe([
                {"provider": r["provider"], "quant": r["quantization"], "in $/M": r["input_usd_per_million"],
                 "out $/M": r["output_usd_per_million"], "context": r["context_tokens"],
                 "tps 30m": r["throughput_tps_30m"], "latency s 30m": r["latency_s_30m"],
                 "uptime% 30m": r["uptime_pct_30m"]}
                for r in routes
            ], width="stretch", hide_index=True)
            st.caption("throughput/latency are null when OpenRouter hasn't published recent measurements.")
        else:
            st.info("No routes returned for this slug.")
