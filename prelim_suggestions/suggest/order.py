"""Rank viable assessments into per-family orderings for the authoring step.

Reads outputs/assessments/<model_slug>/ and writes ordering_contradictory.jsonl
and ordering_complementary.jsonl under outputs/, highest confidence first. Each
line holds the instance, repo, base commit, subsystem, confidence and the model's
suggestion. The files are rebuilt on every call, so reruns are safe.

Usage: python -m suggest.order [--model MODEL]
"""

from __future__ import annotations

import argparse
import json

from swebench_pro import dataset as rows_source
from swebench_pro import layout

from .features import subsystem


def _load_assessments(model: str) -> list[dict]:
    d = layout.assess_dir(model)
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return out


def _rank(records: list[dict], family: str, rows_by_id: dict[str, dict]) -> list[dict]:
    entries = []
    for d in records:
        fam = (d.get("assessment") or {}).get(family) or {}
        if not fam.get("viable"):
            continue
        row = rows_by_id.get(d["instance_id"], {})
        entries.append(
            {
                "instance_id": d["instance_id"],
                "repo": d.get("repo"),
                "base_commit": d.get("base_commit"),
                "subsystem": subsystem(row) if row else "",
                "confidence": fam.get("confidence", 0),
                "status": d.get("status"),
                "suggestion": fam,
                "notes": (d.get("assessment") or {}).get("notes", ""),
            }
        )
    entries.sort(key=lambda e: (-e["confidence"], e["repo"] or "", e["instance_id"]))
    for i, e in enumerate(entries, 1):
        e["rank"] = i
    return entries


def build_orderings(model: str) -> dict[str, int]:
    records = _load_assessments(model)
    rows_by_id = {r["instance_id"]: r for r in rows_source.iter_local_rows()}
    counts = {}
    for family in ("contradictory", "complementary"):
        entries = _rank(records, family, rows_by_id)
        path = layout.ordering_path(family)
        tmp = path.with_name(path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            for e in entries:
                fh.write(json.dumps(e) + "\n")
        tmp.replace(path)
        counts[family] = len(entries)
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description="Rank viable suggestions.")
    ap.add_argument(
        "--model", default=None, help="model slug/id (default: VLLM_MODEL env)."
    )
    args = ap.parse_args()
    import os

    model = args.model or os.environ.get("VLLM_MODEL", "")
    if not model:
        raise SystemExit("no model given (pass --model or set VLLM_MODEL).")
    counts = build_orderings(model)
    for fam, n in counts.items():
        print(f"{fam:14s}: {n:3d} viable -> {layout.ordering_path(fam).name}")


if __name__ == "__main__":
    main()
