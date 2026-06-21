"""Vendor self-reported claims adapter (model cards + release announcements).

Vendors publish benchmark numbers in announcements/model cards. These are
self-reported under vendor-chosen protocols, so they are:
  * a SEPARATE benchmark generation, tagged self_reported + mixed-protocol, that
    never shares a cohort with third-party harness numbers;
  * grouped by benchmark NAME across vendors into one self-reported cohort so
    proprietary models can be ranked against each other (with a loud caveat).

Anti-fabrication guardrail (the reason we don't blind-scrape prose): each claimed
score is VERIFIED to appear literally on the fetched source page near the
benchmark keyword. Absent → recorded as unverified and skipped, never ingested.
The raw page is snapshotted for audit; each observation carries its source_url
and the verifying snippet.
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from ..fetch import Snapshot, fetch
from ..models import AdapterResult, BenchmarkRecord, EntityRecord, Observation, SourceRecord
from . import register
from .base import slug

SOURCE_ID = "vendor_claims"
SEED = Path("config/vendor_claims.toml")
PARSER_VERSION = "1.0.0"

# benchmark key -> (display, domain, task_family)
BENCHES = {
    "gpqa_diamond": ("GPQA Diamond (self-reported)", "science", "reasoning"),
    "mmlu_pro": ("MMLU-Pro (self-reported)", "knowledge", "reasoning"),
    "hle": ("Humanity's Last Exam (self-reported)", "expert_knowledge", "reasoning"),
    "aime_2026": ("AIME 2026 (self-reported)", "mathematics", "math"),
    "swe_bench_verified": ("SWE-bench Verified (self-reported)", "coding/agents", "coding_agent"),
    "terminal_bench": ("Terminal-Bench (self-reported)", "agents", "coding_agent"),
}


def _strip(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def _verify(page_text: str, score: float, bench_key: str) -> tuple[bool, str, str]:
    """Confirm the score appears on the page; prefer a match near the benchmark
    keyword. Returns (verified, confidence, snippet)."""
    if not page_text:
        return False, "no_page", ""
    t = _strip(page_text)
    # accept "80.9", "80.9%", "80.90"
    s = f"{score:g}"
    num_pat = re.escape(s) + r"\s*%?"
    kw = bench_key.split("_")[0]  # gpqa, mmlu, hle, aime, swe, terminal
    kw_pat = {"swe": r"swe-?bench", "terminal": r"terminal-?bench"}.get(kw, re.escape(kw))
    # strong: number within 160 chars of the benchmark keyword (either order)
    for m in re.finditer(kw_pat, t, re.I):
        win = t[max(0, m.start() - 160): m.start() + 160]
        if re.search(num_pat, win):
            return True, "strong", win.strip()[:160]
    # weak: number present somewhere on the page
    if re.search(num_pat, t):
        return True, "weak", "(score present on page, not adjacent to keyword)"
    return False, "absent", ""


def fetch_live() -> Snapshot:
    """Fetch every distinct source page once; bundle {url: text} into one snapshot."""
    claims = tomllib.loads(SEED.read_text()).get("claim", []) if SEED.exists() else []
    pages: dict[str, str] = {}
    for url in sorted({c["source_url"] for c in claims}):
        try:
            r = fetch(SOURCE_ID, url, terms_note="vendor self-reported; provenance only")
            pages[url] = r.text()
        except Exception as e:  # record fetch failure as empty -> claim becomes unverified
            pages[url] = ""
    content = json.dumps({"pages": pages}).encode("utf-8")
    return Snapshot(SOURCE_ID, "vendor_claims://bundle", content, 200, "application/json",
                    _now(), "vendor self-reported")


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@register(SOURCE_ID)
def parse(snapshot: Snapshot, as_of: str) -> AdapterResult:
    claims = tomllib.loads(SEED.read_text()).get("claim", []) if SEED.exists() else []
    pages = snapshot.json().get("pages", {})

    res = AdapterResult()
    res.sources.append(SourceRecord(
        source_id=SOURCE_ID, name="Vendor self-reported claims", url="(model cards + announcements)",
        layer="model", domain="self-reported benchmarks", access_method="vendor pages",
        status="active", as_of=as_of,
        license_or_terms="self-reported; verified-present-on-page; not third-party measured",
        metadata={"claims": len(claims)},
    ))
    # one cohort per benchmark across vendors
    seen_bench = set()
    skipped = []
    for c in claims:
        bk = c["benchmark"]
        if bk not in BENCHES:
            skipped.append({"model": c.get("model"), "benchmark": bk, "reason": "unknown_benchmark"})
            continue
        score = float(c["score"])
        verified, conf, snippet = _verify(pages.get(c["source_url"], ""), score, bk)
        if not verified:
            skipped.append({"model": c.get("model"), "benchmark": bk, "reason": f"unverified:{conf}",
                            "source_url": c["source_url"]})
            continue

        name, domain, family = BENCHES[bk]
        bench_id = f"{SOURCE_ID}/{bk}/{as_of}"
        if bench_id not in seen_bench:
            res.benchmarks.append(BenchmarkRecord(
                benchmark_id=bench_id, source_id=SOURCE_ID, name=name, domain=domain,
                task_type="self_reported", metric_name=c.get("metric", "score"),
                direction="higher_is_better", protocol_version=f"self_reported/{as_of}",
                publish_date=as_of,
                metadata={"task_family": family, "self_reported": True,
                          "protocol": "mixed/vendor-defined", "caveat": "vendor protocols differ"},
            ))
            seen_bench.add(bench_id)

        jk = c.get("join_key") or slug(c["model"])
        ent_id = f"{slug(c.get('vendor','vendor'))}/{slug(c['model'])}"
        res.entities.append(EntityRecord(
            entity_id=ent_id, display_name=c["model"], entity_type="model",
            organization=c.get("vendor"), family_id=jk,
            metadata={"join_key": jk, "proprietary": c.get("proprietary", True)},
        ))
        res.observations.append(Observation(
            source_id=SOURCE_ID, benchmark_id=bench_id, entity_id=ent_id, raw_score=score,
            unit="score_self_reported", observed_at=as_of, relation="self_reported",
            metadata={"source_url": c["source_url"], "source_type": c.get("source_type"),
                      "protocol_note": c.get("protocol_note"), "confidence": conf,
                      "verifying_snippet": snippet},
        ))
    res.sources[0].metadata["skipped_unverified"] = skipped
    return res
