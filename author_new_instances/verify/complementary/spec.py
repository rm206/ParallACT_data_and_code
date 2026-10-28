"""Complementary truth table: 3 checks scored on the single integration test.

A-only and B-only must FAIL (each half is necessary); A+B must PASS.
"""

from __future__ import annotations

from ..report import Check


def build_checks(seed: dict) -> list[Check]:
    itp, iids = seed["integration_test_patch"], seed["integration_fail_to_pass"]
    A, B = seed["agentA_solution"], seed["agentB_solution"]
    return [
        Check("A only vs integration", False, [A], itp, iids),
        Check("B only vs integration", False, [B], itp, iids),
        Check("A+B vs integration", True, [A, B], itp, iids),
    ]
