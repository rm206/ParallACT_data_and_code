"""Shared CLI for the two family entry points, including the codex binary, model
and reasoning settings."""

from __future__ import annotations

import argparse
from pathlib import Path

from .common import CodexConfig
from .pipeline import run_family


def main(family: str) -> None:
    ap = argparse.ArgumentParser(
        description=f"Author {family} dataset instances with codex."
    )
    ap.add_argument(
        "--target",
        type=int,
        default=35,
        help="stop after this many finalized instances (default 35).",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="cap attempts this run (for a short test batch).",
    )
    ap.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="how many instances to author at once for this family.",
    )
    ap.add_argument(
        "--repos",
        default=None,
        help="comma-separated repo allowlist (e.g. protonmail/webclients) "
        "to attempt only those candidates.",
    )
    ap.add_argument(
        "--ids-file",
        default=None,
        help="path to a newline-separated instance_id allowlist; attempt only those.",
    )
    ap.add_argument(
        "--max-correct",
        type=int,
        default=2,
        help="max codex correction passes per instance (default 2).",
    )
    ap.add_argument(
        "--author-codex",
        "--author-codex-bin",
        dest="author_codex",
        default="codex",
        help="codex for authoring and correction: codex | <path>.",
    )
    ap.add_argument(
        "--audit-codex",
        "--audit-codex-bin",
        dest="audit_codex",
        default="codex",
        help="codex for the audit step: codex | <path>.",
    )
    ap.add_argument("--model", default="gpt-5.6-sol", help="codex model (both steps).")
    ap.add_argument(
        "--reasoning", default="medium", help="model_reasoning_effort (both steps)."
    )
    ap.add_argument("--sandbox", default="workspace-write", help="codex --sandbox.")
    args = ap.parse_args()

    author_cfg = CodexConfig.for_name(
        args.author_codex, args.model, args.reasoning, args.sandbox
    )
    audit_cfg = CodexConfig.for_name(
        args.audit_codex, args.model, args.reasoning, args.sandbox
    )
    repos = [r.strip() for r in args.repos.split(",")] if args.repos else None
    ids = None
    if args.ids_file:
        ids = [
            l.strip() for l in Path(args.ids_file).read_text().splitlines() if l.strip()
        ]
    run_family(
        family,
        author_cfg,
        audit_cfg,
        target=args.target,
        max_correct=args.max_correct,
        limit=args.limit,
        concurrency=args.concurrency,
        repos=repos,
        ids=ids,
    )
