"""FastAPI serving layer (spec §19, §21 query plane).

Read endpoints expose the warehouse; POST /recommend and POST /route run the
decision engines. Every recommendation response carries the interpreted profile,
data dates, evidence coverage, and assumptions (spec §18). FastAPI is optional:

    pip install '.[server]'
    uvicorn llm_pareto.server:app --reload
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
except ImportError:  # pragma: no cover
    FastAPI = None

from .recommend import recommend
from .router import route
from .pipeline import today
from .store import Store

DB_PATH = "outputs/leaderboard.db"
PROFILE_DIR = Path("profiles")


def _store() -> Store:
    return Store(DB_PATH)


def _rows(sql: str, params: tuple = (), limit: int = 500) -> list[dict]:
    s = _store()
    try:
        return [dict(r) for r in s.query(sql + " LIMIT ?", params + (limit,))]
    finally:
        s.close()


if FastAPI is not None:
    app = FastAPI(title="llm-pareto meta-leaderboard", version="0.1.0")

    class RecommendRequest(BaseModel):
        profile: str                      # profile name (in profiles/) or path
        as_of: Optional[str] = None
        output_dir: Optional[str] = None

    class RouteRequest(BaseModel):
        profile: str
        as_of: Optional[str] = None
        quality_threshold: Optional[float] = None
        risk_tier: str = "low"
        budget_max: Optional[float] = None

    def _resolve_profile(name: str) -> str:
        p = Path(name)
        if p.exists():
            return str(p)
        cand = PROFILE_DIR / (name if name.endswith(".toml") else f"{name}.toml")
        if cand.exists():
            return str(cand)
        raise HTTPException(404, f"profile not found: {name}")

    @app.get("/sources")
    def sources():
        return _rows("SELECT source_id,name,layer,domain,status FROM sources ORDER BY layer,source_id")

    @app.get("/entities")
    def entities(entity_type: Optional[str] = None):
        if entity_type:
            return _rows("SELECT entity_id,display_name,entity_type,organization,family_id FROM entities WHERE entity_type=?", (entity_type,))
        return _rows("SELECT entity_id,display_name,entity_type,organization,family_id FROM entities")

    @app.get("/benchmarks")
    def benchmarks():
        return _rows("SELECT benchmark_id,source_id,name,domain,task_type,metric_name,direction,protocol_version FROM benchmarks ORDER BY benchmark_id")

    @app.get("/observations")
    def observations(benchmark_id: Optional[str] = None):
        if benchmark_id:
            return _rows("SELECT observation_id,benchmark_id,entity_id,raw_score,observed_at FROM observations WHERE benchmark_id=?", (benchmark_id,))
        return _rows("SELECT observation_id,benchmark_id,entity_id,raw_score,observed_at FROM observations")

    @app.get("/prices")
    def prices():
        return _rows("SELECT deployment_id,entity_id,family_id,as_of,input_usd_per_million,output_usd_per_million,context_tokens FROM prices ORDER BY deployment_id")

    @app.get("/lineage/{observation_id}")
    def lineage(observation_id: int):
        rows = _rows("""SELECT l.observation_id,l.snapshot_id,l.source_row_locator,l.parser_version,
                               s.uri,s.retrieved_at,s.sha256
                        FROM observation_lineage l JOIN raw_snapshots s ON s.snapshot_id=l.snapshot_id
                        WHERE l.observation_id=?""", (observation_id,))
        if not rows:
            raise HTTPException(404, "no lineage for observation")
        return rows

    @app.get("/profiles")
    def profiles():
        return [p.stem for p in PROFILE_DIR.glob("*.toml")]

    @app.get("/profiles/{name}")
    def profile_detail(name: str):
        import tomllib
        return tomllib.loads(Path(_resolve_profile(name)).read_text())

    @app.post("/recommend")
    def post_recommend(req: RecommendRequest):
        s = _store()
        try:
            return recommend(s, _resolve_profile(req.profile), req.as_of or s.latest_data_date() or today())
        finally:
            s.close()

    @app.post("/route")
    def post_route(req: RouteRequest):
        s = _store()
        try:
            return route(s, _resolve_profile(req.profile), req.as_of or s.latest_data_date() or today(),
                         quality_threshold=req.quality_threshold, risk_tier=req.risk_tier,
                         budget_max=req.budget_max)
        finally:
            s.close()
else:  # pragma: no cover
    app = None
