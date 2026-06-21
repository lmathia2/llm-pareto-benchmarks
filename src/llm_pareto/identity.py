"""Entity / benchmark identity + proxy-transfer shrinkage (spec §8, §12).

Identity mappings are versioned evidence, not string cleanup. We never merge by
fuzzy similarity alone; normalized names only *propose* aliases for review.
"""
from __future__ import annotations

import re
import unicodedata

# Policy transfer strengths (spec §12). These are policy choices, not constants.
TRANSFER_STRENGTH = {
    "exact": 1.0,
    "exact_system": 1.0,
    "lmarena_exact": 0.95,
    "lmarena_family": 0.75,
    "family_proxy": 0.75,
    "system_to_model_family": 0.80,
    "qfbench_scaffold": 0.80,
    "provider_route_proxy": 0.70,
    "unknown": 0.0,
}


def shrink_to_prior(score: float | None, transfer_strength: float, prior: float = 0.5) -> float | None:
    """transferred = prior + t * (observed - prior)."""
    if score is None:
        return None
    t = min(1.0, max(0.0, transfer_strength))
    return prior + t * (score - prior)


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def entity_id(organization: str | None, model_name: str) -> str:
    org = slugify(organization) if organization else "unknown"
    return f"{org}/{slugify(model_name)}"


# --- Access axis: API-only vs open-weight (spec §8 entity facets) ------------
# A model's *access* is how you can run it, independent of its quality. API-only
# models (Claude, GPT, Gemini, Grok) are served exclusively behind a vendor API;
# open-weight models publish downloadable weights. This is the axis users filter
# on ("I can only call an API" vs "I can self-host"), and it explains coverage:
# the open-weight quality backbone (OpenEvals) carries almost no API-only models.

# Org slugs whose models are API-only. Note the gpt-oss / gemma exceptions below.
_API_ONLY_ORGS = {"anthropic", "openai", "google", "x-ai", "xai"}
# Substrings that mark an otherwise API-looking org's model as actually open-weight.
_OPEN_WEIGHT_MARKERS = ("gpt-oss", "gemma", "-oss-")
# Org slugs that always publish weights (covers Google's open Gemma, etc.).
_OPEN_WEIGHT_ORGS = {
    "deepseek", "deepseek-ai", "qwen", "meta", "meta-llama", "mistralai", "mistral",
    "moonshotai", "z-ai", "zai-org", "zhipu", "allenai", "microsoft", "nvidia",
    "nousresearch", "cohere", "ai21", "databricks", "01-ai", "baidu",
}


def access_type(organization: str | None, display_name: str = "") -> str:
    """Return 'api' or 'open_weight' for a model/deployment.

    Heuristic, deliberately conservative: an explicit open-weight marker
    (gpt-oss, gemma) wins over the org; then known open-weight orgs; then known
    API-only orgs; default open_weight (most of the long tail is open)."""
    org = slugify(organization or "")
    name = (display_name or "").lower()
    blob = f"{org} {name}"
    if any(m in blob for m in _OPEN_WEIGHT_MARKERS):
        return "open_weight"
    if org in _OPEN_WEIGHT_ORGS:
        return "open_weight"
    if org in _API_ONLY_ORGS:
        return "api"
    # name-based fallback when org is missing/ambiguous (e.g. "Anthropic: Claude …")
    if any(b in name for b in ("claude", "gpt-", "gemini", "grok")):
        return "api"
    return "open_weight"


# Tokens that are version/date noise for join purposes but NOT version identity.
# We strip publication date stamps and provider prefixes, NEVER the version number
# (4.5 vs 4.8 are different models and must not be merged).
_DATE_STAMP = re.compile(r"-(20\d{6}|20\d{2}-\d{2}-\d{2}|preview[-a-z0-9]*|latest)$")
_PROVIDER_PREFIX = re.compile(
    r"^(anthropic|openai|google|x-ai|z-ai|zai-org|moonshotai|qwen|meta-llama|"
    r"mistralai|deepseek-ai|deepseek)-"
)


def canonical_key(join_key: str | None) -> str | None:
    """A looser key for bridging quality evidence to pricing across sources that
    name the SAME model differently (dated API ids vs display slugs). Strips
    publication-date stamps and provider prefixes but preserves the version
    number, so it never merges distinct versions. Used only as a fallback after
    exact join_key fails; the match relation is recorded for auditability."""
    if not join_key:
        return join_key
    k = join_key
    prev = None
    while k != prev:  # peel repeated date/preview suffixes
        prev = k
        k = _DATE_STAMP.sub("", k)
    k = _PROVIDER_PREFIX.sub("", k)
    return k or join_key


def benchmark_id(source_id: str, task_key: str, metric: str, generation: str) -> str:
    """Protocol is part of identity. `generation` is usually a retrieval date or
    protocol_version; a change always yields a new benchmark_id."""
    return f"{source_id}/{slugify(task_key)}/{slugify(metric)}/{generation}"
