# llmmeta — LLM Meta-Leaderboard

Pick the best LLM for **a specific task**, trading off quality, cost, and context — and re-run it
whenever new models ship.

Instead of one universal ranking, `llmmeta` pulls numbers from published benchmarks and live pricing,
normalizes them honestly, and returns a **cost-quality Pareto frontier** filtered by your constraints.
The same data gives different winners for "deep research under $3" vs. "cheapest coding agent."

## How it works

```
ingest published evidence  →  normalize within each benchmark  →  join to live pricing
   →  score per task profile  →  filter by constraints  →  Pareto frontier  →  (optional) route one call
```

Everything lands in a single local warehouse (`outputs/leaderboard.db`). Every number keeps its
lineage: source, retrieval date, raw + normalized score, and a snapshot checksum.

Core rule: scores are only ever compared **within one benchmark** (a `benchmark_id`). A preference
rating, a pass rate, and a dollar price are never averaged on a raw scale. Missing evidence is imputed
to a neutral prior but tracked as `coverage` and penalized, so a thinly-evidenced model never looks as
certain as a fully-measured one.

## Install

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev,analytics,server]'    # add ,viz for the dashboard
```

Requires Python ≥ 3.11. The CLI installs as `llmmeta` (also runnable as `python -m llmmeta.cli`).

## Quick start

Build the whole warehouse from empty and get a recommendation:

```bash
make all
```

That runs the pipeline end to end: `init → registry → discover → ingest → prices → normalize →
recommend → export`. Then ask it questions:

```bash
llmmeta ask --query "best model for deep research with a good quality/cost tradeoff"
llmmeta recommend --profile profiles/coding_agent_balanced.toml --output-dir outputs/coding
```

## Commands

All commands take `--db` (default `outputs/leaderboard.db`) and print JSON to stdout.

| Command | What it does |
|---|---|
| `llmmeta init` | Create the schema / empty warehouse. |
| `llmmeta registry import <csv>` | Load the curated source census (`research/leaderboard_census.csv`). |
| `llmmeta discover hf-official` | Snapshot the Hugging Face official-benchmark list. |
| `llmmeta ingest --source <name>` | Fetch + parse one source (see list below). |
| `llmmeta prices refresh` | Refresh provider pricing records. |
| `llmmeta normalize` | Compute benchmark-local normalized scores. |
| `llmmeta recommend --profile <toml>` | Run a profile → Pareto frontier + recommended default. |
| `llmmeta ask --query "<text>"` | Plain-English question → compiled profile → answer. Add `--json`. |
| `llmmeta route --profile <toml> --risk <tier>` | Cheapest model clearing a risk-tier quality bar. |
| `llmmeta export catalogs` | Dump catalog CSVs to `outputs/catalogs`. |
| `llmmeta check` | Integrity checks (FK, normalized ∈ [0,1], cohort sizes). |
| `llmmeta dashboard` | Launch the Streamlit UI (needs `.[viz]`). |
| `llmmeta analytics parquet` / `postgres-ddl` | Export Parquet / generate Postgres DDL. |

`--as-of YYYY-MM-DD` pins a date; otherwise queries use the latest snapshot in the warehouse.

### Sources for `ingest --source`

`openevals` (capability backbone), `openrouter` (pricing + context), `aider_polyglot` (coding agents),
`lmarena` (human preference), `vendor_claims` (verified self-reported numbers), `hf_official`,
`artificial_analysis`. Gated sources fail soft — they record a blocked status instead of inventing data.

`artificial_analysis` needs `AA_OPT_IN=1` (and `AA_API_KEY`); `hf_official` uses `HF_TOKEN` for gated
leaderboards.

## Profiles

A profile is a TOML file (`profiles/*.toml`) describing one decision: constraints, your token workload,
dimension weights, and how each weighted dimension maps to task families. This is what makes the
recommendation task-specific — edit one and re-run `recommend`.

```toml
[constraints]
max_cost_usd = 3.0
min_context_tokens = 200000
require_price = true

[weights]
general_intelligence = 0.35
quant_finance_agent  = 0.40
human_preference     = 0.15
context_headroom     = 0.10
```

See `profiles/finance_deep_research_under_3.toml` for a full annotated example.

## Reproducible offline build

Ingest from the frozen fixtures in `tests/fixtures/` — no network, fully deterministic:

```bash
llmmeta init
for s in openevals openrouter lmarena aider_polyglot; do
  llmmeta ingest --source $s --as-of 2026-06-18 \
    --fixture sample.$([ $s = aider_polyglot ] && echo txt || echo json)
done
llmmeta normalize
llmmeta recommend --profile profiles/finance_deep_research_under_3.toml
```

`make refresh-live` does the opposite: a clean rebuild from live sources with real retrieval timestamps.

## API

```bash
uvicorn llmmeta.server:app --reload
# GET  /sources /entities /benchmarks /observations /prices /lineage/{id} /profiles
# POST /recommend {"profile": "finance_deep_research_under_3"}
# POST /route     {"profile": "coding_agent_balanced", "risk_tier": "low"}
```

## Tests

```bash
pytest -q          # math, adapters, router, API
llmmeta check      # warehouse integrity
```

## Project layout

```
src/llmmeta/
  cli.py            command entry points
  pipeline.py       ingest / normalize / integrity orchestration
  adapters/         one module per source (fetch + parse → canonical records)
  models.py         canonical record types
  normalization.py  tie-aware empirical-CDF (within-cohort only)
  scoring.py        weighted quality + coverage / missing-evidence penalty
  cost.py           workload cost model (expected + p95)
  pareto.py         eligibility filter + Pareto frontier
  recommend.py      profile → result
  router.py         pre-call cheapest-passing router
  query_compiler.py natural language → profile
  server.py         FastAPI app
  dashboard.py      Streamlit UI
profiles/           task decision profiles (TOML)
research/           curated source census (115 sources)
docs/               methodology + source terms
```

## Limitations

Public benchmarks **shortlist, they don't certify** — run a private acceptance test before production.
Agent benchmarks confound model + scaffold; preference pools have judge effects; context capacity ≠
effective long-context; identity joins are exact-key only, so cross-source coverage is partial and
reported honestly. See `docs/methodology.md` for the full list.
