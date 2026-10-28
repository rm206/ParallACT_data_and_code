"""Write the run bundle, split into two roots.

The tracked dir holds the run/eval contract (`manifest.json`, `outputs/*.patch`,
`comm.jsonl`); the heavy dir holds prompts, transcripts and per-turn patches.
Eval reads only the tracked dir.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .types import RunResult, TurnResult


def _usage_dict(turn: TurnResult) -> dict | None:
    """Serialize any Usage subclass generically (backend extras included)."""
    return None if turn.usage is None else asdict(turn.usage)


def _deep_add(dst: dict, src: dict) -> None:
    """Recursively sum int/float leaves of `src` into `dst`.

    bool/None keep the first value seen and other leaves the last, so any new
    numeric Usage field is summed without changes here.
    """
    for k, v in src.items():
        if isinstance(v, dict):
            node = dst.get(k)
            if not isinstance(node, dict):
                node = {}
                dst[k] = node
            _deep_add(node, v)
        elif isinstance(v, bool) or v is None:
            dst.setdefault(k, v)  # non-additive: keep a representative value
        elif isinstance(v, (int, float)):
            dst[k] = (dst.get(k) or 0) + v
        else:
            dst[k] = v  # str etc. — last-writer wins


def _sum_usage(turns: list[TurnResult]) -> dict:
    """Sum every numeric usage field across turns.

    `cost_usd` is None unless every turn reported a cost.
    """
    token_fields = (
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_creation_tokens",
    )
    total: dict = {f: 0 for f in token_fields}
    for t in turns:
        if t.usage is None:
            continue
        d = dict(asdict(t.usage))
        d.pop("cost_usd", None)
        _deep_add(total, d)

    costs = [t.usage.cost_usd for t in turns if t.usage is not None]
    total["cost_usd"] = (
        sum(c for c in costs if c is not None)
        if costs and all(c is not None for c in costs)
        else None
    )
    # codex/opencode report reasoning tokens under by_model["reasoning"].
    total["reasoning_output_tokens"] = (
        (total.get("by_model") or {}).get("reasoning", {}).get("output_tokens", 0)
    )
    return total


def write(result: RunResult, tracked_dir: Path, heavy_dir: Path) -> Path:
    """Write the contract to `tracked_dir` and provenance to `heavy_dir`; return `tracked_dir`."""
    (tracked_dir / "outputs").mkdir(parents=True, exist_ok=True)
    (heavy_dir / "turns").mkdir(parents=True, exist_ok=True)

    manifest = {
        "scenario": result.scenario,
        "seed_id": result.seed_id,
        "base_commit": result.base_commit,
        "backend": result.backend,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "turns": [
            {"index": t.index, "agent": t.agent, "usage": _usage_dict(t)}
            for t in result.turns
        ],
        "usage_total": _sum_usage(result.turns),
        "outputs": sorted(result.outputs),
    }
    (tracked_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    # comm log is named .jsonl because .gitignore drops *.log.
    for label, patch in result.outputs.items():
        (tracked_dir / "outputs" / f"{label}.patch").write_text(patch, encoding="utf-8")
    (tracked_dir / "comm.jsonl").write_text(result.comm_log, encoding="utf-8")

    for t in result.turns:
        d = heavy_dir / "turns" / f"{t.index:02d}_{t.agent}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "prompt.txt").write_text(t.prompt, encoding="utf-8")
        (d / "transcript.log").write_text(t.transcript, encoding="utf-8")
        (d / "turn.patch").write_text(t.diff, encoding="utf-8")
    return tracked_dir
