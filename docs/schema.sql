PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
  source_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  url TEXT NOT NULL,
  layer TEXT NOT NULL,
  domain TEXT NOT NULL,
  access_method TEXT NOT NULL,
  status TEXT NOT NULL,
  as_of TEXT,
  license_or_terms TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS entities (
  entity_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  organization TEXT,
  family_id TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_entities_family ON entities(family_id);

CREATE TABLE IF NOT EXISTS benchmarks (
  benchmark_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  name TEXT NOT NULL,
  domain TEXT NOT NULL,
  task_type TEXT NOT NULL,
  metric_name TEXT NOT NULL,
  direction TEXT NOT NULL CHECK(direction IN ('higher_is_better','lower_is_better')),
  protocol_version TEXT NOT NULL,
  publish_date TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS observations (
  observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  benchmark_id TEXT NOT NULL REFERENCES benchmarks(benchmark_id),
  entity_id TEXT NOT NULL REFERENCES entities(entity_id),
  raw_score REAL NOT NULL,
  unit TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  sample_size INTEGER,
  standard_error REAL,
  lower_bound REAL,
  upper_bound REAL,
  relation TEXT NOT NULL DEFAULT 'exact',
  metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_obs_benchmark ON observations(benchmark_id);
CREATE INDEX IF NOT EXISTS idx_obs_entity ON observations(entity_id);
-- Natural key for idempotent upsert of a (benchmark, entity, retrieval-date) observation.
CREATE UNIQUE INDEX IF NOT EXISTS uq_obs_natural
  ON observations(source_id, benchmark_id, entity_id, observed_at, relation);

CREATE TABLE IF NOT EXISTS normalized_observations (
  observation_id INTEGER PRIMARY KEY REFERENCES observations(observation_id) ON DELETE CASCADE,
  benchmark_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  normalized_score REAL NOT NULL,
  rank INTEGER NOT NULL,
  cohort_size INTEGER NOT NULL,
  method TEXT NOT NULL DEFAULT 'tie-aware-ecdf-v1'
);
CREATE INDEX IF NOT EXISTS idx_norm_entity ON normalized_observations(entity_id);

CREATE TABLE IF NOT EXISTS prices (
  price_id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT NOT NULL REFERENCES sources(source_id),
  deployment_id TEXT NOT NULL,
  entity_id TEXT NOT NULL REFERENCES entities(entity_id),
  family_id TEXT NOT NULL,
  currency TEXT NOT NULL,
  context_tokens INTEGER,
  as_of TEXT NOT NULL,
  blended_usd_per_million REAL,
  input_usd_per_million REAL,
  cached_input_usd_per_million REAL,
  cache_write_usd_per_million REAL,
  output_usd_per_million REAL,
  median_tokens_per_second REAL,
  latency_first_chunk_seconds REAL,
  total_response_seconds REAL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(source_id, deployment_id, as_of)
);
CREATE INDEX IF NOT EXISTS idx_prices_entity ON prices(entity_id);

CREATE TABLE IF NOT EXISTS aliases (
  source_id TEXT NOT NULL,
  source_model_name TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  family_id TEXT,
  mapping_note TEXT,
  PRIMARY KEY(source_id, source_model_name)
);

-- Production-leaning lineage extensions (kept lightweight for the reference build).
CREATE TABLE IF NOT EXISTS raw_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  retrieved_at TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  uri TEXT NOT NULL,
  raw_object_path TEXT NOT NULL,
  http_status INTEGER,
  terms_note TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_snap_source ON raw_snapshots(source_id);

CREATE TABLE IF NOT EXISTS observation_lineage (
  observation_id INTEGER NOT NULL REFERENCES observations(observation_id) ON DELETE CASCADE,
  snapshot_id TEXT NOT NULL REFERENCES raw_snapshots(snapshot_id),
  source_row_locator TEXT,
  parser_version TEXT,
  PRIMARY KEY(observation_id, snapshot_id)
);

CREATE TABLE IF NOT EXISTS discovery_snapshots (
  as_of TEXT NOT NULL,
  discovery_key TEXT NOT NULL,
  member TEXT NOT NULL,
  change TEXT NOT NULL DEFAULT 'present',
  PRIMARY KEY(as_of, discovery_key, member)
);
