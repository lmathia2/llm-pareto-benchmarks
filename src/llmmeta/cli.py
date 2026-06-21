"""llmmeta command-line interface (spec §27). Every command is deterministic
and prints machine-readable JSON to stdout."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import discovery, pipeline, reporting
from .recommend import recommend
from .store import Store


def _out(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def cmd_init(args):
    with Store(args.db) as s:
        s.init_schema()
    _out({"ok": True, "db": args.db})


def cmd_registry(args):
    with Store(args.db) as s:
        n = pipeline.import_registry(s, args.path)
    _out({"sources_imported": n})


def cmd_discover(args):
    with Store(args.db) as s:
        as_of = args.as_of or pipeline.today()
        snap = discovery.fetch_hf_official()
        raw = snap.persist()
        s.record_snapshot(snap.snapshot_id, snap.source_id, snap.retrieved_at, snap.sha256,
                          snap.url, raw, snap.http_status, snap.terms_note, {})
        summary = discovery.record(s, snap, as_of)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(snap.text())
    _out(summary)


def cmd_ingest(args):
    with Store(args.db) as s:
        res = pipeline.ingest_source(s, args.source, as_of=args.as_of,
                                     use_fixture=args.fixture, save_fixture=not args.no_fixture)
    _out(res)


def cmd_prices(args):
    with Store(args.db) as s:
        res = pipeline.ingest_source(s, "provider_pricing", as_of=args.as_of)
    _out(res)


def cmd_normalize(args):
    with Store(args.db) as s:
        res = pipeline.recompute_normalized(s, method=args.method)
    _out(res)


def cmd_recommend(args):
    with Store(args.db) as s:
        as_of = args.as_of or pipeline.today()
        result = recommend(s, args.profile, as_of)
        paths = reporting.write_recommendation(result, args.output_dir) if args.output_dir else {}
    _out({"recommended_default": result["recommended_default"],
          "frontier_size": len(result["frontier"]),
          "n_candidates": result["n_candidates"], "n_eligible": result["n_eligible"],
          "outputs": paths})


def cmd_route(args):
    from .router import route
    with Store(args.db) as s:
        as_of = args.as_of or pipeline.today()
        res = route(s, args.profile, as_of, quality_threshold=args.quality,
                    risk_tier=args.risk, budget_max=args.budget)
    _out(res)


def cmd_ask(args):
    from .query_compiler import compile_query
    from .recommend import run_profile
    from .explain import answer_text
    with Store(args.db) as s:
        as_of = args.as_of or pipeline.today()
        prof, interp = compile_query(args.query, as_of)
        result = run_profile(s, prof, as_of, selection=prof["_selection"])
    if args.json:
        _out({"interpretation": interp, "result": result})
    else:
        print(answer_text(result, interp, args.query))


def cmd_dashboard(args):
    import subprocess, sys, os
    from pathlib import Path
    app = Path(__file__).resolve().parent / "dashboard.py"
    env = dict(os.environ, LLMMETA_DB=args.db)
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app)], env=env)


def cmd_export(args):
    with Store(args.db) as s:
        written = reporting.export_catalogs(s, args.output_dir)
    _out({"written": written})


def cmd_check(args):
    with Store(args.db) as s:
        res = pipeline.integrity_check(s)
    _out(res)


def cmd_analytics(args):
    from . import analytics
    if args.action == "parquet":
        with Store(args.db) as s:
            _out(analytics.export_parquet(s, args.output_dir))
    else:  # postgres-ddl
        from .store import SCHEMA_PATH
        ddl = analytics.postgres_ddl(SCHEMA_PATH)
        if args.output:
            Path(args.output).write_text(ddl)
            _out({"written": args.output})
        else:
            print(ddl)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="llmmeta")
    # parent carries --db so it can appear before OR after the subcommand
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--db", default="outputs/leaderboard.db")
    p.add_argument("--db", default="outputs/leaderboard.db")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", parents=[parent]); sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("registry", parents=[parent]); sp.add_argument("action", choices=["import"])
    sp.add_argument("path"); sp.set_defaults(func=cmd_registry)

    sp = sub.add_parser("discover", parents=[parent]); sp.add_argument("what", choices=["hf-official"])
    sp.add_argument("--output"); sp.add_argument("--as-of", dest="as_of"); sp.set_defaults(func=cmd_discover)

    sp = sub.add_parser("ingest", parents=[parent]); sp.add_argument("--source", required=True)
    sp.add_argument("--as-of", dest="as_of"); sp.add_argument("--fixture")
    sp.add_argument("--no-fixture", action="store_true"); sp.set_defaults(func=cmd_ingest)

    sp = sub.add_parser("prices", parents=[parent]); sp.add_argument("action", choices=["refresh"])
    sp.add_argument("--as-of", dest="as_of"); sp.set_defaults(func=cmd_prices)

    sp = sub.add_parser("normalize", parents=[parent]); sp.add_argument("--method", default="tie-aware-ecdf-v1")
    sp.set_defaults(func=cmd_normalize)

    sp = sub.add_parser("recommend", parents=[parent]); sp.add_argument("--profile", required=True)
    sp.add_argument("--as-of", dest="as_of"); sp.add_argument("--output-dir")
    sp.set_defaults(func=cmd_recommend)

    sp = sub.add_parser("route", parents=[parent]); sp.add_argument("--profile", required=True)
    sp.add_argument("--as-of", dest="as_of"); sp.add_argument("--quality", type=float)
    sp.add_argument("--risk", default="low", choices=["low", "medium", "high", "critical"])
    sp.add_argument("--budget", type=float); sp.set_defaults(func=cmd_route)

    sp = sub.add_parser("ask", parents=[parent]); sp.add_argument("--query", required=True)
    sp.add_argument("--as-of", dest="as_of"); sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_ask)

    sp = sub.add_parser("dashboard", parents=[parent]); sp.set_defaults(func=cmd_dashboard)

    sp = sub.add_parser("export", parents=[parent]); sp.add_argument("action", choices=["catalogs"])
    sp.add_argument("--output-dir", default="outputs/catalogs"); sp.set_defaults(func=cmd_export)

    sp = sub.add_parser("check", parents=[parent]); sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("analytics", parents=[parent])
    sp.add_argument("action", choices=["parquet", "postgres-ddl"])
    sp.add_argument("--output-dir", default="outputs/parquet"); sp.add_argument("--output")
    sp.set_defaults(func=cmd_analytics)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
