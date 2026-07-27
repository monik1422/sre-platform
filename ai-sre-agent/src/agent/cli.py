"""CLI entrypoint for the AI SRE agent.

Examples:
    python -m agent.cli rca --window 15 --service sample-api --out /tmp/rca.md
    python -m agent.cli signals            # just dump gathered evidence as JSON
"""
from __future__ import annotations

import argparse
import dataclasses
import logging
import sys

from agent import config
from agent.rca import run
from agent.report import render_markdown
from agent.signals import gather


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
    )


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    parser = argparse.ArgumentParser(prog="ai-sre-agent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_rca = sub.add_parser("rca", help="Run a full RCA and print/write the report")
    p_rca.add_argument("--window", type=int, help="Lookback window in minutes")
    p_rca.add_argument("--service", type=str, help="Target service name")
    p_rca.add_argument("--namespace", type=str, help="Target namespace")
    p_rca.add_argument("--out", type=str, default="", help="Write Markdown report to this path")

    sub.add_parser("signals", help="Gather and print the raw signal bundle as JSON")

    args = parser.parse_args(argv)

    cfg = config.load()
    overrides = {}
    if getattr(args, "window", None):
        overrides["lookback_minutes"] = args.window
    if getattr(args, "service", None):
        overrides["target_service"] = args.service
    if getattr(args, "namespace", None):
        overrides["target_namespace"] = args.namespace
    if overrides:
        cfg = dataclasses.replace(cfg, **overrides)

    if args.cmd == "signals":
        print(gather(cfg).model_dump_json(indent=2))
        return 0

    if args.cmd == "rca":
        bundle, rca = run(cfg)
        md = render_markdown(bundle, rca)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(md)
            logging.getLogger("cli").info("wrote report to %s", args.out)
        print(md)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
