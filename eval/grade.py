"""Grade run bundles against their instances.

Reads only a bundle (``outputs/*.patch`` + ``manifest.json``) and the instance JSON.
Instances are processed one at a time: pull the image, grade every pending bundle for
it across all harness-model namespaces, then delete its scratch. Images are kept
unless ``--rmi-at-end``. Already-graded bundles are skipped unless ``--force``.

  uv run python -m eval.grade \
      --corpus v2 --family both \
      [--harness-model claude__qwen3-flash-next ...] [--num-to-run N] \
      [--scenario oracle ...] [--strategies concat,git-merge] [--jobs 2] \
      [--rmi-at-end] [--force]
"""

from __future__ import annotations

import argparse
import glob
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import combine, corpus, runner

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
LOCAL = REPO / ".local"

DEFAULT_STRATEGIES = ["concat", "git-merge", "reconciler"]
DEFAULT_RUNS = str(REPO / "run_outputs" / "custom")  # used only without --corpus
DEFAULT_OUT = str(REPO / "eval_outputs" / "custom")  # used only without --corpus
DEFAULT_CACHE = str(LOCAL / "eval_cache")

# Mirrors running_instances/common/run.py.
CORPUS_INPUTS = {
    "v1": [REPO / "dataset" / "v1" / "generated", REPO / "dataset" / "v1" / "seeds"],
    "v2": [REPO / "dataset" / "v2" / "generated"],
}


def _numbers(manifest: dict) -> dict:
    """Usage, cost, turn count and wall time from the manifest."""
    ut = manifest.get("usage_total", {}) or {}
    wall = None
    try:
        s = datetime.fromisoformat(manifest["started_at"])
        f = datetime.fromisoformat(manifest["finished_at"])
        wall = (f - s).total_seconds()
    except Exception:  # noqa: BLE001
        pass
    return {
        "usage_total": ut,
        "cost_usd": ut.get("cost_usd"),
        "input_tokens": ut.get("input_tokens"),
        "output_tokens": ut.get("output_tokens"),
        "reasoning_output_tokens": ut.get("reasoning_output_tokens"),
        "cache_read_tokens": ut.get("cache_read_tokens"),
        "cache_creation_tokens": ut.get("cache_creation_tokens"),
        "num_turns": len(manifest.get("turns", [])),
        "wall_seconds": wall,
    }


def _groups(seed: dict) -> dict:
    """Per-metric (test_patches, fail_to_pass ids, pass_to_pass ids).

    Contradictory instances score A, B and both combined; complementary instances
    are interdependent, so only the integration test is scored."""
    A, B = list(seed["agentA_fail_to_pass"]), list(seed["agentB_fail_to_pass"])
    if seed["family"] == "contradictory":
        return {
            "A": (
                [seed["agentA_test_patch"]],
                A,
                list(seed.get("agentA_pass_to_pass") or []),
            ),
            "B": (
                [seed["agentB_test_patch"]],
                B,
                list(seed.get("agentB_pass_to_pass") or []),
            ),
            "scored": ([seed["combined_test_patch"]], A + B, []),
        }
    return {
        "scored": (
            [seed["integration_test_patch"]],
            list(seed["integration_fail_to_pass"]),
            [],
        )
    }


def grade_bundle(
    bundle_dir: Path,
    seed: dict,
    merge_root: Path,
    scratch_dir: Path,
    strategies: list[str] | None = None,
) -> dict:
    """Grade one bundle against a loaded instance; keeps the full runner output
    for every group and strategy."""
    manifest = json.loads((bundle_dir / "manifest.json").read_text())
    outputs = {
        Path(p).stem: Path(p).read_text()
        for p in glob.glob(str(bundle_dir / "outputs" / "*.patch"))
    }
    groups = _groups(seed)
    serial = "final" in outputs
    strats = ["final"] if serial else (strategies or DEFAULT_STRATEGIES)
    work = merge_root / manifest["seed_id"] / manifest["scenario"]
    work.mkdir(parents=True, exist_ok=True)

    def run_group(code_patch: str | None, key: str) -> dict:
        tps, f2p, p2p = groups[key]
        detail = runner.run(
            seed, code_patch, tps, f2p, pass_to_pass=p2p, scratch_dir=scratch_dir
        )
        detail["pass"] = bool(f2p) and all(
            detail["fail_to_pass"].get(i) == "PASSED" for i in f2p
        )
        return detail

    # A / B are contradictory only.
    group_results: dict = {}
    if "A" in groups:
        if serial:
            a_code = b_code = outputs["final"]
        else:
            a_code, b_code = outputs.get("A"), outputs.get("B")
        group_results["A"] = run_group(a_code, "A") if a_code is not None else None
        group_results["B"] = run_group(b_code, "B") if b_code is not None else None

    # Serial scenarios have a single "final" strategy.
    scored: dict = {}
    for strat in strats:
        comb = combine.combine(seed, outputs, strat, work)
        if comb["patch"] is None:
            scored[strat] = {
                "combine_status": comb["status"],
                "pass": False,
                "detail": None,
            }
        else:
            det = run_group(comb["patch"], "scored")
            scored[strat] = {
                "combine_status": comb["status"],
                "pass": det["pass"],
                "detail": det,
            }

    a_pass = (group_results.get("A") or {}).get("pass") if "A" in groups else None
    b_pass = (group_results.get("B") or {}).get("pass") if "A" in groups else None
    return {
        "seed_id": manifest["seed_id"],
        "scenario": manifest["scenario"],
        "family": seed["family"],
        "repo": seed["repo"],
        "backend": manifest.get("backend"),
        "serial": serial,
        "numbers": _numbers(manifest),
        "groups": {
            "A": group_results.get("A"),
            "B": group_results.get("B"),
            "scored": scored,
        },
        "A": a_pass,
        "B": b_pass,
        "scored_pass": any(v["pass"] for v in scored.values()),
        "graded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _image_present(image: str) -> bool:
    r = subprocess.run(
        ["docker", "image", "inspect", image], capture_output=True, text=True
    )
    return r.returncode == 0


def _pull(image: str) -> bool:
    if _image_present(image):
        return True
    r = subprocess.run(
        ["docker", "pull", "--platform", "linux/amd64", image],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    return r.returncode == 0


def _rmi(image: str) -> None:
    subprocess.run(["docker", "rmi", "-f", image], capture_output=True, text=True)


def _discover_harness_models(runs_root: Path, label: str) -> list[str]:
    return sorted(
        p.name for p in runs_root.iterdir() if p.is_dir() and (p / label).exists()
    )


def grade_corpus(
    input_folder: Path,
    family: str,
    runs_root: Path,
    out_root: Path,
    cache_root: Path,
    harness_models: list[str] | None,
    label: str | None,
    num_to_run: int | None,
    scenarios: set[str] | None,
    strategies: list[str] | None,
    jobs: int,
    force: bool,
    rmi_at_end: bool,
) -> None:
    lbl = corpus.label_for(input_folder, label)
    hms = harness_models or _discover_harness_models(runs_root, lbl)
    if not hms:
        raise SystemExit(f"no harness-model dirs with label {lbl!r} under {runs_root}")
    print(
        f"corpus={input_folder} label={lbl} harness_models={hms} runs={runs_root} "
        f"out={out_root} cache={cache_root} jobs={jobs} rmi_at_end={rmi_at_end} "
        f"strategies={strategies or DEFAULT_STRATEGIES}",
        flush=True,
    )
    touched_images: set[str] = set()

    for fam in corpus.resolve_families(family):
        graded_instances = 0
        for seed_path in corpus.list_instances(input_folder, fam):
            if num_to_run is not None and graded_instances >= num_to_run:
                break
            seed = corpus.load(seed_path)
            iid = seed["instance_id"]
            pending: list[tuple[str, Path, Path]] = []
            for hm in hms:
                runs_fam = runs_root / hm / lbl / fam
                for mani in sorted(runs_fam.glob(f"{iid}/*/manifest.json")):
                    bundle_dir = mani.parent
                    scen = bundle_dir.name
                    if scenarios and scen not in scenarios:
                        continue
                    out_file = out_root / hm / lbl / fam / iid / f"{scen}.json"
                    if force or not out_file.exists():
                        pending.append((hm, bundle_dir, out_file))
            if not pending:
                continue
            graded_instances += 1

            image = seed["runtime"]["image_uri"]
            touched_images.add(image)
            inst_scratch = cache_root / iid
            merge_root = inst_scratch / "merge"
            exch_root = inst_scratch / "exchange"
            exch_root.mkdir(parents=True, exist_ok=True)
            present = _image_present(image)
            print(
                f"[{fam}] {iid}: {len(pending)} bundle(s) over {len({p[0] for p in pending})} "
                f"harness-model(s); image {'cached' if present else 'pulling'}...",
                flush=True,
            )
            if not present and not _pull(image):
                print(
                    f"[{fam}] {iid}: WARN image pull failed ({image}); "
                    f"trying anyway (may be local)",
                    flush=True,
                )

            def _grade(item: tuple[str, Path, Path]) -> None:
                hm, bundle_dir, out_file = item
                try:
                    res = grade_bundle(
                        bundle_dir, seed, merge_root, exch_root, strategies
                    )
                    res["harness_model"] = hm
                    out_file.parent.mkdir(parents=True, exist_ok=True)
                    out_file.write_text(json.dumps(res, indent=2))
                    n = res["numbers"]
                    print(
                        f"[{fam}] {hm} {iid} / {bundle_dir.name}: "
                        f"scored_pass={res['scored_pass']} A={res['A']} B={res['B']} "
                        f"cost={n['cost_usd']}",
                        flush=True,
                    )
                except Exception as e:  # noqa: BLE001 — one bundle must not kill the run
                    print(f"  ERROR {hm} {bundle_dir}: {e!r}", flush=True)

            try:
                if jobs > 1 and len(pending) > 1:
                    with ThreadPoolExecutor(max_workers=jobs) as pool:
                        list(pool.map(_grade, pending))
                else:
                    for item in pending:
                        _grade(item)
            finally:
                subprocess.run(["rm", "-rf", str(inst_scratch)], capture_output=True)

        _write_summaries(out_root, hms, lbl, fam)
        print(
            f"[{fam}] done ({graded_instances} instance(s) graded this run)", flush=True
        )

    if rmi_at_end and touched_images:
        print(f"--rmi-at-end: removing {len(touched_images)} image(s)...", flush=True)
        for img in sorted(touched_images):
            _rmi(img)


def _write_summaries(out_root: Path, hms: list[str], label: str, fam: str) -> None:
    for hm in hms:
        out_fam = out_root / hm / label / fam
        results = [
            json.loads(Path(p).read_text())
            for p in sorted(glob.glob(str(out_fam / "*" / "*.json")))
            if Path(p).name != "summary.json"
        ]
        if not results:
            continue
        passed = sum(1 for r in results if r["scored_pass"])
        (out_fam / "summary.json").write_text(
            json.dumps(
                {
                    "harness_model": hm,
                    "family": fam,
                    "n": len(results),
                    "scored_pass": passed,
                    "results": results,
                },
                indent=2,
            )
        )
        print(
            f"  summary {hm}/{fam}: {passed}/{len(results)} scored_pass "
            f"-> {out_fam / 'summary.json'}",
            flush=True,
        )


def _strats(s: str | None) -> list[str] | None:
    return s.split(",") if s else None


def main() -> None:
    ap = argparse.ArgumentParser(description="Grade run bundles.")
    ap.add_argument(
        "--corpus",
        choices=("v1", "v2"),
        default=None,
        help="resolve input(s) + roots by corpus (v1=dataset/v1/{generated,seeds}, "
        "v2=dataset/v2/generated). runs<-run_outputs/<corpus>, "
        "out<-eval_outputs/<corpus>. Overrides --input-folder/--runs/--out.",
    )
    ap.add_argument(
        "--input-folder", default=None, help="corpus root (ignored when --corpus set)"
    )
    ap.add_argument("--family", default="both", help="contra|comple|both")
    ap.add_argument(
        "--runs",
        default=None,
        help="run-bundles root (default: by --corpus, else run_outputs/custom)",
    )
    ap.add_argument(
        "--out",
        default=None,
        help="eval-results root (default: by --corpus, else eval_outputs/custom)",
    )
    ap.add_argument(
        "--cache-root",
        default=DEFAULT_CACHE,
        help="scratch root (default .local/eval_cache, gitignored)",
    )
    ap.add_argument(
        "--harness-model",
        action="append",
        default=None,
        help="harness__model namespace (repeatable); default = all found",
    )
    ap.add_argument(
        "--label", default=None, help="corpus label (default: input-folder basename)"
    )
    ap.add_argument(
        "--num-to-run",
        type=int,
        default=None,
        help="grade this many not-yet-graded instances per family",
    )
    ap.add_argument(
        "--scenario",
        action="append",
        default=None,
        help="limit to these scenarios (repeatable)",
    )
    ap.add_argument("--strategies", default=None, help="parallel combine strategies")
    ap.add_argument(
        "--jobs", type=int, default=1, help="bundles graded concurrently per instance"
    )
    ap.add_argument("--force", action="store_true", help="re-grade already-graded")
    ap.add_argument(
        "--rmi-at-end",
        action="store_true",
        help="docker rmi every image touched, once at the end (default: "
        "keep images — they are reused across models/evals)",
    )
    a = ap.parse_args()
    if a.corpus:
        inputs = list(CORPUS_INPUTS[a.corpus])
        runs_root = Path(a.runs) if a.runs else REPO / "run_outputs" / a.corpus
        out_root = Path(a.out) if a.out else REPO / "eval_outputs" / a.corpus
    else:
        if not a.input_folder:
            ap.error("pass --corpus {v1,v2} or --input-folder")
        inputs = [Path(a.input_folder)]
        runs_root = Path(a.runs) if a.runs else Path(DEFAULT_RUNS)
        out_root = Path(a.out) if a.out else Path(DEFAULT_OUT)
    scenarios = set(a.scenario) if a.scenario else None
    strategies = _strats(a.strategies)
    for input_folder in inputs:
        input_folder = input_folder.resolve()
        if not input_folder.is_dir():
            print(f"skip: corpus input not found -> {input_folder}", flush=True)
            continue
        grade_corpus(
            input_folder,
            a.family,
            runs_root,
            out_root,
            Path(a.cache_root),
            a.harness_model,
            a.label,
            a.num_to_run,
            scenarios,
            strategies,
            max(1, a.jobs),
            a.force,
            a.rmi_at_end,
        )


if __name__ == "__main__":
    main()
