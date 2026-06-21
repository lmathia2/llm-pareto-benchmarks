# Source access & terms posture

We respect licenses, robots directives, and terms. Preference order for every source (spec §6.1):
official API → official download (CSV/JSON/Parquet/HF dataset) → repo artifacts → stable generated
assets → permitted browser parsing → manual extraction (Tier C). We **never** bypass authentication,
anti-bot controls, paywalls, or rate limits, and we never store credentials/cookies/authorization
headers (`fetch.fetch` strips them). When a source is inaccessible or its terms prohibit automated
collection, we **record that condition** (status `partial-blocked`) rather than inventing data.

## Ingestion tiers

- **Tier A** — public API / downloadable dataset / stable artifact. Automated.
- **Tier B** — public data needing source-specific parsing or protocol reconstruction.
- **Tier C** — web/paper tables or terms-sensitive extraction; manual review + explicit approval.

## Status of implemented adapters (as of 2026-06-18)

| Source | Tier | Access | Status in build |
|---|---|---|---|
| HF `benchmark:official` discovery | A | `api/datasets?filter=benchmark:official` | **live** — 34 datasets, dated + diffed |
| OpenEvals (`OpenEvals/leaderboard-data`) | A | HF datasets-server `/rows` | **live** — 105 models, 11 dims |
| OpenRouter catalog | A | `api/v1/models` | **live** — 300+ priced deployments |
| Aider Polyglot | A/B | GitHub raw YAML | **live** — agent-system coding + cost |
| LM Arena | B | api 403 / dataset gated / client-side | **fail-soft blocked** — 0 fabricated rows |
| Artificial Analysis | B | commercial API 401 | **terms-gated** — blocked unless `AA_OPT_IN=1` + `AA_API_KEY` |
| Provider pricing (OpenAI/Anthropic/Google) | A | official pages | **seed-file**; only `confirmed=true` rows ingested |
| Vendor claims (model cards + announcements) | C | vendor/aggregator pages | **live + verified** — number must appear on the fetched page or it's skipped |
| HF official per-dataset leaderboards | A/B | `…/datasets/{id}/leaderboard` | **token-gated** — needs `HF_TOKEN`; blocked otherwise |

### Proprietary-model coverage

OpenEvals (the open-weight quality source) carries almost no proprietary frontier models. To bring
Claude / GPT-5.x / Gemini / Mistral into the rankings we use **`vendor_claims`**: a curated,
provenance-stamped table of self-reported numbers (`config/vendor_claims.toml`) where the adapter
**fetches the cited source page and verifies the score literally appears near the benchmark keyword**
before ingesting. Naive prose scraping is deliberately avoided — it pulled *"SWE-bench Verified … 76%
fewer output tokens"* as a score in testing. Self-reported numbers are tagged `self_reported`,
grouped into their own cohort per benchmark (vendor protocols differ), and **never** merged with
third-party harness runs. The `hf_official` adapter is the alternative once an `HF_TOKEN` is supplied.

The remaining ~108 registry sources are loaded as **registered stubs** (`adapter=stub`) so coverage and
exclusions stay honest; add a source-specific adapter after inspecting its protocol. Adding one means:
emit canonical records (`models.py`), tag a `task_family`, fail closed on schema drift
(`adapters/base.SchemaDriftError`), and register it in `pipeline.LIVE_ADAPTERS`.

## Redistribution

Raw snapshots are stored locally (content-addressed) for reproducibility, **not** republished. For
terms-sensitive sources prefer storing derived measurements + source links over mirroring upstream
tables. Each source row carries its `license_or_terms`; verify before any redistribution.
