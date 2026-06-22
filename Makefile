DB ?= outputs/leaderboard.db
PROFILE ?= profiles/finance_deep_research_under_3.toml
PY ?= python3
DATE := $(shell date +%F)

# Load local secrets (API keys / opt-ins) if present, and export them to recipes.
# .env is gitignored — see .env.example for the template. Keeps keys out of the
# shell history and out of version control while making `make warehouse` one step.
ifneq (,$(wildcard ./.env))
include .env
export
endif

.PHONY: help init registry discover ingest prices normalize recommend export test check clean all warehouse

help:
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-12s %s\n", $$1, $$2}'

init: ## Create schema and an empty warehouse
	$(PY) -m llm_pareto.cli init --db $(DB)

registry: ## Import the curated 115-source registry
	$(PY) -m llm_pareto.cli registry import research/leaderboard_census.csv --db $(DB)

discover: ## Snapshot the HF official-benchmark census
	$(PY) -m llm_pareto.cli discover hf-official --db $(DB) --output data/raw/discovery/hf_official_$(DATE).json

ingest: ## Fetch + ingest all live adapters (backbone + Tier-B/C)
	$(PY) -m llm_pareto.cli ingest --source openevals --db $(DB)
	$(PY) -m llm_pareto.cli ingest --source openrouter --db $(DB)
	$(PY) -m llm_pareto.cli ingest --source lmarena --db $(DB)
	$(PY) -m llm_pareto.cli ingest --source aider_polyglot --db $(DB)
	$(PY) -m llm_pareto.cli ingest --source artificial_analysis --db $(DB)
	$(PY) -m llm_pareto.cli ingest --source vendor_claims --db $(DB)
	$(PY) -m llm_pareto.cli ingest --source hf_official --db $(DB)
	$(PY) -m llm_pareto.cli ingest --source llm_stats --db $(DB)

prices: ## Refresh provider pricing records
	$(PY) -m llm_pareto.cli prices refresh --db $(DB) --as-of $(DATE)

normalize: ## Compute benchmark-local normalized scores
	$(PY) -m llm_pareto.cli normalize --db $(DB) --method tie-aware-ecdf-v1

recommend: ## Run a profile end-to-end
	$(PY) -m llm_pareto.cli recommend --profile $(PROFILE) --db $(DB) --output-dir outputs/$(basename $(notdir $(PROFILE)))

recommend-all: ## Run every profile in profiles/
	@for p in profiles/*.toml; do \
	  name=$$(basename $$p .toml); \
	  echo "→ $$name"; \
	  $(PY) -m llm_pareto.cli recommend --profile $$p --db $(DB) --output-dir outputs/$$name >/dev/null; \
	done

export: ## Export catalog CSVs
	$(PY) -m llm_pareto.cli export catalogs --db $(DB) --output-dir outputs/catalogs

test: ## Run the test suite
	$(PY) -m pytest -q

check: ## Database integrity checks
	$(PY) -m llm_pareto.cli check --db $(DB)

all: init registry discover ingest prices normalize recommend export ## Full pipeline from empty

refresh-live: clean init registry discover ingest prices normalize recommend-all export check ## Clean rebuild from LIVE sources (real timestamps + current models)
	@echo "✓ live refresh complete — lineage now carries real retrieval timestamps"

warehouse: clean init registry ingest prices normalize check ## One-shot: build the durable local warehouse (uses .env keys), then query offline
	@echo "✓ warehouse built at $(DB) — now fully offline: query via SQL, 'llm-pareto ask/recommend', the API, or 'llm-pareto dashboard'"

clean:
	rm -f $(DB)
