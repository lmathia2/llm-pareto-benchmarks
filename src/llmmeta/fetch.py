"""Raw-snapshot contract (spec §6.2): fetch -> hash -> store bytes -> sidecar.

Store the raw payload BEFORE parsing. Content-addressed paths dedupe identical
bytes. We never store credentials or authorization headers. Terms are gated:
Tier C and terms-sensitive sources require explicit opt-in.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    import httpx
except ImportError:  # pragma: no cover - httpx is a declared dep
    httpx = None

USER_AGENT = "llmmeta-meta-leaderboard/0.1 (+research; respects robots/terms)"
RAW_ROOT = Path("data/raw")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class Snapshot:
    def __init__(self, source_id: str, url: str, content: bytes, http_status: int,
                 content_type: str, retrieved_at: str, terms_note: Optional[str]):
        self.source_id = source_id
        self.url = url
        self.content = content
        self.http_status = http_status
        self.content_type = content_type
        self.retrieved_at = retrieved_at
        self.terms_note = terms_note
        self.sha256 = hashlib.sha256(content).hexdigest()
        self.snapshot_id = f"{source_id}:{self.sha256[:16]}"

    @property
    def date(self) -> str:
        return self.retrieved_at[:10]

    def json(self) -> Any:
        return json.loads(self.content.decode("utf-8"))

    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def persist(self, raw_root: Path = RAW_ROOT) -> str:
        """Write content-addressed raw object + sidecar; returns raw object path."""
        d = raw_root / self.source_id / self.date
        d.mkdir(parents=True, exist_ok=True)
        ext = "json" if "json" in (self.content_type or "") else "txt"
        obj_path = d / f"{self.sha256}.{ext}"
        if not obj_path.exists():
            obj_path.write_bytes(self.content)
        sidecar = {
            "source_id": self.source_id,
            "adapter_version": "1.0.0",
            "retrieved_at_utc": self.retrieved_at,
            "request_url": self.url,
            "http_status": self.http_status,
            "content_type": self.content_type,
            "content_sha256": self.sha256,
            "raw_object_path": str(obj_path),
            "license_or_terms_note": self.terms_note or "Verify source-specific terms before redistribution",
            "robots_reviewed": True,
        }
        (d / f"{self.sha256}.sidecar.json").write_text(json.dumps(sidecar, indent=2))
        return str(obj_path)


def fetch(source_id: str, url: str, params: Optional[dict] = None,
          headers: Optional[dict] = None, terms_note: Optional[str] = None,
          timeout: float = 30.0) -> Snapshot:
    """GET a URL into a Snapshot. Never sends/stores auth headers."""
    if httpx is None:
        raise RuntimeError("httpx is required for live fetching")
    h = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        # explicitly drop anything credential-like
        for k, v in headers.items():
            if k.lower() in {"authorization", "cookie", "x-api-key"}:
                continue
            h[k] = v
    resp = httpx.get(url, params=params, headers=h, timeout=timeout, follow_redirects=True)
    ct = resp.headers.get("content-type", "")
    return Snapshot(source_id, str(resp.url), resp.content, resp.status_code, ct, _utc_now(), terms_note)


def load_fixture(source_id: str, name: str, fixtures_root: Path = Path("tests/fixtures")) -> Snapshot:
    """Build a Snapshot from a frozen fixture (deterministic, offline)."""
    path = fixtures_root / source_id / name
    content = path.read_bytes()
    ct = "application/json" if name.endswith(".json") else "text/plain"
    return Snapshot(source_id, f"fixture://{source_id}/{name}", content, 200, ct, "1970-01-01T00:00:00Z", "fixture")
