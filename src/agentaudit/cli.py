"""Command-line interface: ``agentaudit run|report|serve|demo-db|verify``."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentaudit", description=__doc__)
    parser.add_argument(
        "--root", default=os.environ.get("AGENTAUDIT_ROOT", "."), help="project root"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run an experiment config (writes results/<experiment>/<run>/)")
    r.add_argument("config")
    r.add_argument("--quiet", action="store_true")
    sub.add_parser("report", help="regenerate research/generated tables and figures")
    d = sub.add_parser("demo-db", help="build the audit database the console serves")
    d.add_argument("--seed", type=int, default=0)
    d.add_argument("--claims", type=int, default=600)
    s = sub.add_parser("serve", help="serve the forensic console and API")
    s.add_argument("--host", default=os.environ.get("AGENTAUDIT_HOST", "127.0.0.1"))
    s.add_argument("--port", type=int, default=int(os.environ.get("AGENTAUDIT_PORT", "8000")))
    v = sub.add_parser("verify", help="verify the integrity of an audit database")
    v.add_argument("db", nargs="?", default=None)
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    if args.cmd == "run":
        from agentaudit.experiments.runner import run_experiment

        print(run_experiment(Path(args.config), root, quiet=args.quiet).relative_to(root))
        return 0
    if args.cmd == "report":
        from agentaudit.experiments.report import generate_report

        for p in generate_report(root):
            print(p.relative_to(root))
        return 0
    if args.cmd == "demo-db":
        from agentaudit.api.demo import build_demo

        path = build_demo(root, seed=args.seed, n_claims=args.claims)
        print(path.relative_to(root) if path.is_relative_to(root) else path)
        return 0
    if args.cmd == "serve":
        import uvicorn

        from agentaudit.api.app import create_app

        uvicorn.run(create_app(root), host=args.host, port=args.port, log_level="info")
        return 0
    if args.cmd == "verify":
        from agentaudit.api.demo import open_db, verify_db

        log, signer, witness, every = open_db(root, Path(args.db) if args.db else None)
        print(json.dumps(verify_db(log, signer, witness, every).as_dict(), indent=1))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
