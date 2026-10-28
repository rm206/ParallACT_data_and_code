"""Manual cross-set diversity audit of a family's finalized instances.

Hands codex a compact summary of every instance in OUTPUT/<family>/ and saves its
advisory concentration report (labels, distribution counts, over-concentration
flags, buckets to avoid next) under WORK/<family>/. Finalized instances are not changed.

Run (from author_new_instances/):
  python -m authoring.diversity_audit --family both
"""

from __future__ import annotations

import glob
import json
import time
from pathlib import Path

from . import common, examples
from .common import CodexConfig


def _summary(family: str) -> list[dict]:
    rows = []
    for p in sorted(glob.glob(str(common.OUTPUT / family / "*.json"))):
        try:
            s = json.load(open(p))
        except Exception:  # noqa: BLE001
            continue
        rows.append(
            {
                "instance_id": s.get("instance_id", Path(p).stem),
                "repo": s.get("repo", ""),
                "subsystem": examples._primary_dir(s.get("agentA_solution")),
                "mutex_type": s.get("mutex_type", ""),
                "diversity_mechanism": s.get("diversity_mechanism", ""),
                "shared_artifact": (s.get("shared_artifact") or "")[:400],
                "agentA_problem_statement": (s.get("agentA_problem_statement") or "")[
                    :900
                ],
                "agentB_problem_statement": (s.get("agentB_problem_statement") or "")[
                    :900
                ],
            }
        )
    return rows


def run(family: str, cfg: CodexConfig) -> None:
    inst = _summary(family)
    if not inst:
        print(
            f"[{family}] no finalized instances in {common.OUTPUT / family}; nothing to audit."
        )
        return
    ts = time.strftime("%Y%m%d_%H%M%S")
    wd = common.WORK / family / f"_diversity_{ts}"
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "instances.jsonl").write_text("\n".join(json.dumps(x) for x in inst))
    prompt = (common.PROMPTS / family / "diversity.md").read_text()
    (wd / "PROMPT.md").write_text(prompt)
    print(
        f"[{family}] diversity audit over {len(inst)} instances via {cfg.describe()} ..."
    )
    common.run_codex(wd, prompt, cfg, "diversity_run.log")

    rep = wd / "DIVERSITY_report.json"
    if not rep.exists():
        print(
            f"[{family}] auditor wrote no DIVERSITY_report.json; see {wd / 'diversity_run.log'}"
        )
        return
    dest = common.WORK / family / f"diversity_report_{ts}.json"
    dest.write_text(rep.read_text())
    print(f"[{family}] report -> {dest}")
    try:
        d = json.loads(rep.read_text())
    except json.JSONDecodeError:
        print(f"[{family}] (report is not valid JSON; raw copy saved)")
        return
    for key in ("summary", "distribution", "concentration_flags", "avoid_next"):
        if key in d:
            print(f"\n== {key} ==")
            print(json.dumps(d[key], indent=2)[:1800])
