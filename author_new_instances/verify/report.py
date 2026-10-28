"""Types for one truth-table row (Check), its result, and the whole report."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class Check:
    """One truth-table row: build a code state, run a test set, expect PASS/FAIL."""

    name: str
    expected: bool  # True = every fail_to_pass id must PASS
    code: list[str]  # solution patches to apply (in order); [] = base
    test_patch: str  # test patch applied on top
    fail_to_pass: list[str]  # ids that must all pass for actual == True
    merge: str | None = None  # None | "concat" | "git" (then code == [A, B])


@dataclass
class CheckResult:
    name: str
    expected: bool
    actual: bool
    ok: bool  # actual == expected
    applied: str  # ok | fail | conflict
    n_pass: int
    n_total: int
    detail: dict = field(default_factory=dict)


@dataclass
class Report:
    instance_id: str
    family: str
    sound: bool
    results: list[CheckResult]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    def render(self) -> str:
        head = f"{self.family.upper()}  {self.instance_id}"
        line = "=" * max(60, len(head))
        rows = [
            line,
            head,
            line,
            f"{'row':<30} {'expect':<7} {'actual':<7} {'tests':<9} {'apply':<9} ok",
        ]
        for r in self.results:
            exp = "PASS" if r.expected else "FAIL"
            act = "PASS" if r.actual else "FAIL"
            rows.append(
                f"{r.name:<30} {exp:<7} {act:<7} "
                f"{f'{r.n_pass}/{r.n_total}':<9} {r.applied:<9} "
                f"{'✓' if r.ok else '✗'}"
            )
        rows.append(line)
        rows.append(f"VERDICT: {'SOUND ✓' if self.sound else 'UNSOUND ✗'}")
        return "\n".join(rows)


def write(report: Report, out_path: str | Path) -> None:
    Path(out_path).write_text(report.to_json(), encoding="utf-8")
