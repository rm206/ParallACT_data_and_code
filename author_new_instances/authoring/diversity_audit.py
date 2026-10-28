"""Entry point: manual cross-set diversity audit of finalized instances.

Run:  python -m authoring.diversity_audit --family both \
          [--audit-codex-bin codex] [--model ...] [--reasoning ...]
"""

from __future__ import annotations

import argparse

from . import diversity
from .common import CodexConfig


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Cross-set diversity audit of finalized instances."
    )
    ap.add_argument(
        "--family", choices=["contradictory", "complementary", "both"], default="both"
    )
    ap.add_argument(
        "--audit-codex",
        "--audit-codex-bin",
        dest="audit_codex",
        default="codex",
        help="codex for the diversity audit: codex | <path>.",
    )
    ap.add_argument("--model", default="gpt-5.6-sol")
    ap.add_argument("--reasoning", default="medium")
    ap.add_argument("--sandbox", default="workspace-write")
    args = ap.parse_args()

    cfg = CodexConfig.for_name(
        args.audit_codex, args.model, args.reasoning, args.sandbox
    )
    fams = (
        ["contradictory", "complementary"] if args.family == "both" else [args.family]
    )
    for fam in fams:
        diversity.run(fam, cfg)


if __name__ == "__main__":
    main()
