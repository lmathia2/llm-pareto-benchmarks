"""Dynamic source discovery (spec §4, §10.1).

The curated registry is supplemented by querying Hugging Face for datasets
tagged `benchmark:official`. Each run is stored as a dated snapshot and diffed
against the prior membership so additions/removals are auditable. We do NOT
auto-promote discovered datasets to comparable leaderboards — they are
registered, then require protocol inspection + a benchmark-specific adapter.
"""
from __future__ import annotations

from .fetch import Snapshot, fetch
from .store import Store

HF_OFFICIAL_ENDPOINT = "https://huggingface.co/api/datasets"
DISCOVERY_KEY = "hf_official_benchmarks"


def fetch_hf_official(limit: int = 1000) -> Snapshot:
    return fetch(
        "hf_benchmark_api",
        HF_OFFICIAL_ENDPOINT,
        params={"filter": "benchmark:official", "limit": limit, "full": "true"},
        terms_note="HF dataset cards; verify per-dataset license before redistribution",
    )


def parse_members(snapshot: Snapshot) -> list[str]:
    data = snapshot.json()
    return sorted({d["id"] for d in data if isinstance(d, dict) and "id" in d})


def diff_membership(store: Store, members: list[str]) -> dict[str, str]:
    """Returns {member: 'added'|'present'} plus removed entries vs the prior snapshot."""
    _, prior = store.latest_discovery(DISCOVERY_KEY)
    current = set(members)
    changes: dict[str, str] = {}
    for m in members:
        changes[m] = "added" if (prior and m not in prior) else "present"
    for gone in (prior - current):
        changes[gone] = "removed"
    return changes


def record(store: Store, snapshot: Snapshot, as_of: str) -> dict:
    members = parse_members(snapshot)
    changes = diff_membership(store, members)
    all_members = sorted(set(members) | {m for m, c in changes.items() if c == "removed"})
    store.record_discovery(as_of, DISCOVERY_KEY, all_members, changes)
    store.conn.commit()
    added = [m for m, c in changes.items() if c == "added"]
    removed = [m for m, c in changes.items() if c == "removed"]
    return {"as_of": as_of, "count": len(members), "added": added, "removed": removed}
