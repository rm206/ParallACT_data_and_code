"""
CLI: verify one self-contained seed (docker).

  python -m verify.verify <seed.json> [--report out.json]

Reads the seed's `family`, runs the matching truth table, prints the table and
writes a report JSON next to the seed (or to --report).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import harness, report, seed as seedmod
from .complementary import spec as comple_spec
from .contradictory import spec as contra_spec

_SPECS = {"contradictory": contra_spec, "complementary": comple_spec}


def main() -> None:
    ap = argparse.ArgumentParser(description="Verify a seed's soundness in docker.")
    ap.add_argument("seed", help="path to a self-contained seed JSON")
    ap.add_argument("--report", default=None, help="where to write the report JSON")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    s = seedmod.load(args.seed)
    fam = s["family"]
    if fam not in _SPECS:
        raise SystemExit(f"unknown family: {fam!r}")

    checks = _SPECS[fam].build_checks(s)
    print(
        f"verifying {fam} seed {s['instance_id']} ({len(checks)} checks) in docker..."
    )
    rep = harness.verify(s, checks, verbose=not args.quiet)
    print("\n" + rep.render())

    out = args.report or str(Path(args.seed).with_suffix(".verification.json"))
    report.write(rep, out)
    print(f"\nreport: {out}")
    raise SystemExit(0 if rep.sound else 1)


if __name__ == "__main__":
    main()
