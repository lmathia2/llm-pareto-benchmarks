"""Shared adapter helpers (spec §6, §10.8).

- slug(): normalized identifier component.
- blocked_source(): record a source as terms/access blocked with ZERO fabricated
  rows, satisfying "record the condition rather than inventing data" (spec §1.10).
- Tier-B/C scrapers should fail CLOSED on schema drift (spec §10.8): if the parsed
  shape doesn't match expectations, raise rather than silently shifting columns.
"""
from __future__ import annotations

import re

from ..models import AdapterResult, SourceRecord


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def blocked_source(source_id: str, name: str, url: str, layer: str, domain: str,
                   as_of: str, reason: str) -> AdapterResult:
    res = AdapterResult()
    res.sources.append(SourceRecord(
        source_id=source_id, name=name, url=url, layer=layer, domain=domain,
        access_method="blocked", status="partial-blocked", as_of=as_of,
        license_or_terms="access/terms blocked; recorded, not scraped",
        metadata={"blocked": True, "reason": reason},
    ))
    return res


class SchemaDriftError(RuntimeError):
    """Raised by Tier-B/C adapters when the upstream shape no longer matches."""
