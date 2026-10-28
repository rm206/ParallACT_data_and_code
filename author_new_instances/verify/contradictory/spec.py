"""Contradictory (mutex) truth table: 7 checks scored on the combined AB suite."""

from __future__ import annotations

from ..report import Check


def build_checks(seed: dict) -> list[Check]:
    A_tp, A_ids = seed["agentA_test_patch"], seed["agentA_fail_to_pass"]
    B_tp, B_ids = seed["agentB_test_patch"], seed["agentB_fail_to_pass"]
    comb_tp = seed["combined_test_patch"]
    comb_ids = list(A_ids) + list(B_ids)
    A, B = seed["agentA_solution"], seed["agentB_solution"]
    recon = seed["reconciliation_patch"]
    return [
        Check("base vs A tests", False, [], A_tp, A_ids),
        Check("base vs B tests", False, [], B_tp, B_ids),
        Check("A_solution vs A tests", True, [A], A_tp, A_ids),
        Check("B_solution vs B tests", True, [B], B_tp, B_ids),
        Check(
            "concat-merge vs combined", False, [A, B], comb_tp, comb_ids, merge="concat"
        ),
        Check("git-merge vs combined", False, [A, B], comb_tp, comb_ids, merge="git"),
        Check("reconciliation vs combined", True, [recon], comb_tp, comb_ids),
    ]
