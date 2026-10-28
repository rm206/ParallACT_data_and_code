"""In-context example chooser.

Each candidate gets 2 worked examples from the same family's seed bank:

  score(seed) = same repo (+100) + same language (+10) + same code area (+5)
  pick #1 = highest score; pick #2 = highest score from a different repo when
  possible (else next highest), for variety.

Every seed in the bank is verified, so similarity only serves to match the
harness and test-id conventions of the repo being authored. Examples are trimmed
to the problem statements, explanation, shared artifact, and key patch hunks.
"""

from __future__ import annotations

import glob
import json
import re
from pathlib import Path

from . import common

_PLUS_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$", re.M)


def _primary_dir(diff: str | None) -> str:
    """Directory of the first non-test file a diff touches (a coarse area key)."""
    if not diff:
        return ""
    for path in _PLUS_FILE_RE.findall(diff):
        low = path.lower()
        if any(m in low for m in ("test", "spec", "__tests__")):
            continue
        return str(Path(path).parent)
    return ""


def _clip(s: str | None, n: int) -> str:
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[:n] + f"\n... [trimmed {len(s) - n} chars]"


class ExampleBank:
    """Loads the fixed family seeds once and serves ranked example pairs."""

    def __init__(self, family: str):
        self.family = family
        self.seeds = []
        for p in sorted(glob.glob(str(common.SEEDS / family / "*.json"))):
            try:
                s = json.load(open(p))
            except Exception:  # noqa: BLE001
                continue
            s["_repo"] = s.get("repo", "")
            s["_lang"] = (s.get("runtime", {}) or {}).get("repo_language", "").lower()
            s["_dir"] = _primary_dir(s.get("agentA_solution"))
            self.seeds.append(s)

    def _score(self, seed: dict, repo: str, language: str, subsystem: str) -> int:
        sc = 0
        if seed["_repo"] == repo:
            sc += 100
        if language and seed["_lang"] == language.lower():
            sc += 10
        if (
            subsystem
            and seed["_dir"]
            and (
                seed["_dir"] == subsystem
                or seed["_dir"] in subsystem
                or subsystem in seed["_dir"]
            )
        ):
            sc += 5
        return sc

    def choose(
        self, repo: str, language: str, subsystem: str, k: int = 2
    ) -> list[dict]:
        ranked = sorted(
            self.seeds,
            key=lambda s: (
                -self._score(s, repo, language, subsystem),
                s.get("instance_id", ""),
            ),
        )
        if not ranked:
            return []
        picks = [ranked[0]]
        # #2 prefers a different repo than #1 (variety), else next best.
        for s in ranked[1:]:
            if s["_repo"] != picks[0]["_repo"]:
                picks.append(s)
                break
        if len(picks) < k:
            for s in ranked[1:]:
                if s not in picks:
                    picks.append(s)
                    if len(picks) >= k:
                        break
        return picks[:k]


def _render_one(seed: dict, family: str, idx: int) -> str:
    lang = seed.get("_lang") or (seed.get("runtime", {}) or {}).get("repo_language", "")
    parts = [
        f"### Example {idx} — {seed.get('repo', '?')} ({lang})",
        f"- mutex_type: {seed.get('mutex_type', '')}    "
        f"diversity_mechanism: {seed.get('diversity_mechanism', '')}",
        f"- shared_artifact: {_clip(seed.get('shared_artifact'), 300)}",
        f"- why independent (natural_language_explanation): "
        f"{_clip(seed.get('natural_language_explanation'), 700)}",
        "",
        f"**agentA_problem_statement**\n{_clip(seed.get('agentA_problem_statement'), 1400)}",
        f"**agentB_problem_statement**\n{_clip(seed.get('agentB_problem_statement'), 1400)}",
        "",
        f"**agentA_solution (key hunks)**\n```diff\n{_clip(seed.get('agentA_solution'), 1300)}\n```",
        f"**agentB_solution (key hunks)**\n```diff\n{_clip(seed.get('agentB_solution'), 1300)}\n```",
    ]
    if family == "contradictory":
        parts += [
            f"**reconciliation_patch (key hunks)**\n```diff\n"
            f"{_clip(seed.get('reconciliation_patch'), 1300)}\n```",
            f"**reconciliation_explanation**\n{_clip(seed.get('reconciliation_explanation'), 600)}",
        ]
    else:
        parts += [
            f"**integration_test_patch (the one end-to-end test)**\n```diff\n"
            f"{_clip(seed.get('integration_test_patch'), 1300)}\n```",
        ]
    return "\n".join(parts)


def render_examples(family: str, repo: str, language: str, subsystem: str) -> str:
    """EXAMPLES.md content: 2 trimmed worked examples for this candidate."""
    bank = ExampleBank(family)
    picks = bank.choose(repo, language, subsystem, k=2)
    header = (
        f"# In-context examples ({family})\n"
        f"Two finished, verified {family} seeds, closest to the repo/language "
        f"you are authoring for. Imitate their SHAPE, harness/test-id style, and "
        f"the way the two problem statements read as independent tickets — do NOT "
        f"copy their content.\n"
    )
    return header + "\n\n".join(
        _render_one(s, family, i + 1) for i, s in enumerate(picks)
    )
