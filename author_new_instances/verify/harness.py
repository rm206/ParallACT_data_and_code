"""The engine: run a family's list of Checks against a seed, produce a Report."""

from __future__ import annotations

from . import runner
from .report import Check, CheckResult, Report


def verify(seed: dict, checks: list[Check], verbose: bool = True) -> Report:
    results: list[CheckResult] = []
    for i, c in enumerate(checks, 1):
        if verbose:
            print(f"  [{i}/{len(checks)}] {c.name} ...", flush=True)
        r = runner.run_suite(seed, c.code, c.merge, c.test_patch, c.fail_to_pass)
        actual = r["all_passed"]
        res = CheckResult(
            name=c.name,
            expected=c.expected,
            actual=actual,
            ok=(actual == c.expected),
            applied=r["applied"],
            n_pass=r["n_pass"],
            n_total=r["n_total"],
            detail=r["statuses"],
        )
        if verbose:
            print(
                f"      expect={'PASS' if c.expected else 'FAIL'} "
                f"actual={'PASS' if actual else 'FAIL'} "
                f"({r['n_pass']}/{r['n_total']}, apply={r['applied']}) "
                f"{'OK' if res.ok else 'MISMATCH'}",
                flush=True,
            )
        results.append(res)
    return Report(
        instance_id=seed["instance_id"],
        family=seed["family"],
        sound=all(r.ok for r in results),
        results=results,
    )
