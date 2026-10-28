"""Diverse candidate selection from row metadata alone (no model, no checkout).

All eligible rows go into one deterministic priority order and the candidates are
its first `target` entries, so raising --target extends the same prefix and never
reshuffles. Repos are interleaved by language; within a repo, rows are interleaved
across subsystems with a fixed seed. Rows listed in exclude_ids.txt are skipped.

Usage: python -m suggest.select --target N
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

from swebench_pro import dataset as rows_source
from swebench_pro import layout

from .features import subsystem

SEED = 20260912
HERE = Path(__file__).resolve().parent
EXCLUDE_FILE = HERE / "exclude_ids.txt"

# Language per repo, used only to interleave the repo order. Unlisted repos fall
# back to the row's repo_language (or '?').
REPO_LANG = {
    "flipt-io/flipt": "go",
    "gravitational/teleport": "go",
    "future-architect/vuls": "go",
    "navidrome/navidrome": "go",
    "ansible/ansible": "python",
    "internetarchive/openlibrary": "python",
    "qutebrowser/qutebrowser": "python",
    "protonmail/webclients": "js",
    "element-hq/element-web": "js",
    "NodeBB/NodeBB": "js",
    "tutao/tutanota": "ts",
}


def load_exclude() -> set[str]:
    if not EXCLUDE_FILE.exists():
        return set()
    out = set()
    for line in EXCLUDE_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.add(line)
    return out


def load_candidates() -> list[dict]:
    if not layout.CANDIDATES.exists():
        return []
    out = []
    for line in layout.CANDIDATES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _lang_of(row: dict) -> str:
    return REPO_LANG.get(row["repo"]) or (row.get("repo_language") or "?").lower()


def _within_repo_order(rows: list[dict]) -> list[dict]:
    """Interleave a repo's rows across subsystems (larger subsystems first),
    seeded-shuffled within each subsystem. Deterministic across processes."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[subsystem(r)].append(r)
    rng = random.Random(f"{SEED}:{rows[0]['repo'] if rows else ''}")
    for g in groups.values():
        g.sort(key=lambda r: r["instance_id"])
        rng.shuffle(g)
    ordered_subsys = sorted(groups, key=lambda s: (-len(groups[s]), s))
    out: list[dict] = []
    t = 0
    biggest = max((len(g) for g in groups.values()), default=0)
    while t < biggest:
        for s in ordered_subsys:
            if t < len(groups[s]):
                out.append(groups[s][t])
        t += 1
    return out


def build_priority_order(rows: list[dict]) -> list[dict]:
    """Global diversity order over eligible rows: language-interleaved repos,
    subsystem-interleaved within each repo. Fully deterministic."""
    by_repo: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_repo[r["repo"]].append(r)
    repo_orders = {repo: _within_repo_order(rs) for repo, rs in by_repo.items()}

    # Repo sequence: round-robin across languages (deterministic).
    lang_to_repos: "OrderedDict[str, list[str]]" = OrderedDict()
    for lang in sorted({_lang_of(by_repo[r][0]) for r in by_repo}):
        lang_to_repos[lang] = sorted(
            [r for r in by_repo if _lang_of(by_repo[r][0]) == lang]
        )
    repo_sequence: list[str] = []
    i = 0
    maxlen = max((len(v) for v in lang_to_repos.values()), default=0)
    while i < maxlen:
        for repos in lang_to_repos.values():
            if i < len(repos):
                repo_sequence.append(repos[i])
        i += 1

    # Global round-robin: tier t takes the t-th row of each repo in sequence.
    out: list[dict] = []
    t = 0
    biggest = max((len(v) for v in repo_orders.values()), default=0)
    while t < biggest:
        for repo in repo_sequence:
            ro = repo_orders[repo]
            if t < len(ro):
                out.append(ro[t])
        t += 1
    return out


def _record(row: dict, rank: int) -> dict:
    return {
        "instance_id": row["instance_id"],
        "repo": row["repo"],
        "base_commit": row.get("base_commit"),
        "language": _lang_of(row),
        "subsystem": subsystem(row),
        "rank": rank,
    }


def _write_candidates(records: list[dict]) -> None:
    layout.OUTPUTS.mkdir(parents=True, exist_ok=True)
    tmp = layout.CANDIDATES.with_name(layout.CANDIDATES.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    tmp.replace(layout.CANDIDATES)


def ensure_candidates(target: int) -> list[dict]:
    """Ensure candidates.jsonl holds the first `target` of the deterministic
    diverse order. Monotonic: if it already holds >= target, nothing changes."""
    existing = load_candidates()
    if len(existing) >= target:
        return existing
    exclude = load_exclude()
    rows = [r for r in rows_source.iter_local_rows() if r["instance_id"] not in exclude]
    order = build_priority_order(rows)
    chosen = [_record(r, i + 1) for i, r in enumerate(order[:target])]
    if len(chosen) < target:
        print(
            f"[select] only {len(chosen)} eligible rows available (< target {target})"
        )
    _write_candidates(chosen)
    return chosen


def report(records: list[dict]) -> dict:
    return {
        "total": len(records),
        "by_language": dict(sorted(Counter(r["language"] for r in records).items())),
        "by_repo": dict(sorted(Counter(r["repo"] for r in records).items())),
        "distinct_subsystems": len({(r["repo"], r["subsystem"]) for r in records}),
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Select a diverse candidate set (high-water mark)."
    )
    ap.add_argument("--target", type=int, required=True)
    args = ap.parse_args()
    if rows_source.local_count() == 0:
        raise SystemExit(
            "no rows downloaded yet; run `python -m swebench_pro.download` first."
        )
    recs = ensure_candidates(args.target)
    rep = report(recs)
    print(f"candidates: {rep['total']} (target {args.target}) -> {layout.CANDIDATES}")
    print("  by language:", rep["by_language"])
    print("  by repo:    ", rep["by_repo"])
    print(f"  distinct (repo,subsystem): {rep['distinct_subsystems']}")


if __name__ == "__main__":
    main()
