"""Run the prelim-suggestions stage as one resumable command.

    python -m suggest.run --target N [--concurrency C]

Downloads rows if missing, extends candidates.jsonl to the first N of the
selection order, explores each unassessed candidate, and rebuilds the orderings.
Assessments are written atomically on completion, so rerunning the same command
resumes. Instances run repo by repo; each checkout is deleted after its instance
and a repo's mirror once the repo is done.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from swebench_pro import dataset, download, layout, repos

from . import agent, llm, order, select


def _assessment_path(model: str, iid: str):
    return layout.assess_dir(model) / f"{iid}.json"


def _done(model: str, iid: str) -> bool:
    return _assessment_path(model, iid).exists()


def _write_assessment(model: str, rec: dict) -> None:
    d = layout.assess_dir(model)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{rec['instance_id']}.json"
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    tmp.replace(p)


def _group_by_repo_in_order(cands: list[dict]) -> "OrderedDict[str, list[dict]]":
    groups: "OrderedDict[str, list[dict]]" = OrderedDict()
    for c in cands:
        groups.setdefault(c["repo"], []).append(c)
    return groups


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Run the prelim-suggestions stage (resumable)."
    )
    ap.add_argument(
        "--target",
        type=int,
        required=True,
        help="high-water mark: ensure/explore this many candidates.",
    )
    ap.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="instances explored at once within a repo (default 4).",
    )
    ap.add_argument("--max-steps", type=int, default=40)
    ap.add_argument(
        "--force-finish-at",
        type=int,
        default=30,
        help="from this step on, force the model to call finish.",
    )
    ap.add_argument(
        "--repos",
        default=None,
        help="comma-separated repo allowlist (restrict this run).",
    )
    ap.add_argument("--model", default=None, help="override VLLM_MODEL for this run.")
    ap.add_argument("--base-url", default=None, help="override VLLM_BASE_URL.")
    ap.add_argument(
        "--keep-tmp",
        action="store_true",
        help="do not delete checkouts/mirrors (debug; scratch may fill).",
    )
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.model:
        os.environ["VLLM_MODEL"] = args.model
    if args.base_url:
        os.environ["VLLM_BASE_URL"] = args.base_url

    layout.ensure_persistent_dirs()
    layout.ensure_tmp_dirs()

    n_rows = download.ensure_rows()
    if n_rows == 0:
        raise SystemExit("no rows available after download.")

    cands = select.ensure_candidates(args.target)
    if args.repos:
        allow = {r.strip() for r in args.repos.split(",")}
        cands = [c for c in cands if c["repo"] in allow]
    rep = select.report(cands)

    client = llm.from_env()
    model = client.model
    system, template = agent.load_prompts(layout.PROMPTS_DIR)

    pending = [c for c in cands if not _done(model, c["instance_id"])]
    already = len(cands) - len(pending)
    print(f"model={model}  base={client.base_url}")
    print(
        f"candidates={len(cands)} (target {args.target})  done={already}  pending={len(pending)}"
    )
    print(f"  by language: {rep['by_language']}")
    print(f"  by repo:     {rep['by_repo']}")
    if not pending:
        counts = order.build_orderings(model)
        print(f"nothing to explore. orderings: {counts}")
        return

    rows_by_id = {c["instance_id"]: c for c in cands}
    groups = _group_by_repo_in_order(pending)
    lock = threading.Lock()
    state = {"ok": 0, "fail": 0, "done": already}
    total = len(cands)
    t0 = time.time()

    def explore(c: dict) -> None:
        iid, repo = c["instance_id"], c["repo"]
        if _done(model, iid):  # another pass/worker may have finished it
            return
        t1 = time.time()
        try:
            checkout = repos.ensure_checkout(repo, c["base_commit"], iid)
        except Exception as e:  # noqa: BLE001
            with lock:
                state["fail"] += 1
                print(f"  FAIL checkout {iid}: {str(e)[:120]}")
            return
        try:
            row = dataset.load_row(iid)
            result = agent.run_agent(
                row,
                checkout,
                client,
                system,
                template,
                max_steps=args.max_steps,
                force_finish_at=args.force_finish_at,
                verbose=args.verbose,
            )
            rec = {
                "instance_id": iid,
                "repo": repo,
                "base_commit": c["base_commit"],
                "model": model,
                "status": result["status"],
                "steps_used": result["steps_used"],
                "wall_seconds": round(time.time() - t1, 1),
                "timestamp": time.time(),
                "assessment": result["assessment"],
                "transcript": result["transcript"],
            }
            _write_assessment(model, rec)
            a = result["assessment"]
            with lock:
                state["ok"] += 1
                state["done"] += 1
                print(
                    f"  [{state['done']}/{total}] {result['status']:10s} "
                    f"contra={a['contradictory']['confidence']} "
                    f"comple={a['complementary']['confidence']}  {iid}  "
                    f"({result['steps_used']} steps, {rec['wall_seconds']}s)"
                )
        except Exception as e:  # noqa: BLE001 — one instance must not kill the run
            with lock:
                state["fail"] += 1
                print(f"  FAIL assess {iid}: {str(e)[:150]}")
        finally:
            if not args.keep_tmp:
                repos.remove_checkout(repo, iid)

    for repo, members in groups.items():
        print(f"---- repo {repo}: {len(members)} pending ----")
        with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
            list(pool.map(explore, members))
        if not args.keep_tmp:
            repos.remove_mirror(repo)

    counts = order.build_orderings(model)
    dt = time.time() - t0
    print(f"\ndone: ok={state['ok']} fail={state['fail']} in {dt / 60:.1f}min")
    print(f"assessments: {layout.assess_dir(model)}")
    print(f"orderings:   {counts}")


if __name__ == "__main__":
    main()
