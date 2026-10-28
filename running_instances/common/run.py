"""Run one harness x model over a corpus, across all scenarios with scenario concurrency.

  python3 run.py --harness claude --model glm --corpus v2 --scenario-concurrency 10
  python3 run.py --harness codex  --model glm --corpus v1 --num-to-run 1

Inputs:  v1 = dataset/v1/{generated,seeds}; v2 = dataset/v2/generated
Outputs: run_outputs/<v1|v2>/<harness>__<model>/<label>/<family>/<iid>/<scenario>/
         manifest.json, comm.jsonl, outputs/*.patch, turns/NN_agent/{prompt,transcript,turn.patch}
Scratch: .local/run_scratch/{work,repo_cache} (gitignored checkouts and bare-mirror cache)
"""

from __future__ import annotations

import argparse
import glob
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent
LOCAL = REPO / ".local"
sys.path.insert(0, str(HERE))

from engine import corpus  # noqa: E402
from engine.run import _load_instances_file, _scenario_names, run_family  # noqa: E402
from engine.workspace import CachedCloneSource  # noqa: E402
from runners import harness_model_label, make_runner  # noqa: E402

CORPUS_INPUTS = {
    "v1": [REPO / "dataset" / "v1" / "generated", REPO / "dataset" / "v1" / "seeds"],
    "v2": [REPO / "dataset" / "v2" / "generated"],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--harness", required=True, help="claude|codex|opencode")
    ap.add_argument("--model", default="qwen")
    ap.add_argument(
        "--corpus",
        choices=("v1", "v2"),
        default=None,
        help="resolve inputs + output roots by corpus (v1=dataset/v1/"
        "{generated,seeds}, v2=dataset/v2/generated). "
        "Outputs -> run_outputs/<corpus>/ unless --out is given. Overrides "
        "--input-folder when set.",
    )
    ap.add_argument(
        "--input-folder",
        default=None,
        help="explicit corpus folder (ignored when --corpus is set)",
    )
    ap.add_argument("--family", default="both", help="contra|comple|both")
    ap.add_argument(
        "--num-to-run",
        type=int,
        default=None,
        help="instances per family (default: all), counted across all "
        "of the corpus's input folders.",
    )
    ap.add_argument(
        "--instances-file",
        default=None,
        help="file of instance_ids (one per line; '# comments'; optional "
        "'<family> <id>'). Only these ids are run; ids absent from "
        "the input folder are skipped. Use to target exact instances.",
    )
    ap.add_argument(
        "--scenario",
        action="append",
        default=None,
        help="scenario (repeatable); default = all registered",
    )
    ap.add_argument("--scenario-concurrency", type=int, default=8)
    ap.add_argument(
        "--out",
        default=None,
        help="bundle root (default: run_outputs/<corpus>, else run_outputs/custom)",
    )
    ap.add_argument(
        "--heavy-root",
        default=None,
        help="root for prompts, transcripts, turn patches (default: same as --out)",
    )
    ap.add_argument("--repo-cache", default=None)
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument(
        "--evict-gold-images",
        action="store_true",
        help="docker rmi each instance's "
        "gold-test image after its scenarios finish (only images "
        "this run pulled). Leave off "
        "if an eval sharing those images runs concurrently.",
    )
    a = ap.parse_args()

    if a.corpus:
        inputs = list(CORPUS_INPUTS[a.corpus])
        out_root = pathlib.Path(a.out) if a.out else REPO / "run_outputs" / a.corpus
    else:
        if not a.input_folder:
            ap.error("pass --corpus {v1,v2} or --input-folder")
        inputs = [pathlib.Path(a.input_folder)]
        out_root = pathlib.Path(a.out) if a.out else REPO / "run_outputs" / "custom"
    out_root = out_root.resolve()
    # Transcripts go into the bundle by default.
    heavy = pathlib.Path(a.heavy_root).resolve() if a.heavy_root else out_root
    # Scratch stays out of the tracked outputs: per-scenario checkouts and channel
    # scratch under work/, bare mirror clones under repo_cache/.
    scratch = LOCAL / "run_scratch"
    work_base = scratch / "work"
    repo_cache = (
        pathlib.Path(a.repo_cache).resolve()
        if a.repo_cache
        else (scratch / "repo_cache").resolve()
    )
    hm = harness_model_label(a.harness, a.model)
    # Clear stale checkouts left by a killed run. Scoped to this harness-model so a
    # concurrent run of another model keeps its live workspaces.
    for d in glob.glob(str(work_base / hm / "**" / "_work" / "ws_*"), recursive=True):
        shutil.rmtree(d, ignore_errors=True)

    runner = make_runner(a.harness, a.model, timeout=a.timeout)
    source = CachedCloneSource(repo_cache)
    names = _scenario_names(a.scenario)
    allow = _load_instances_file(a.instances_file)
    # --num-to-run is a per-family budget for the whole corpus, spent across its input
    # folders, not per folder.
    families = corpus.resolve_families(a.family)
    remaining = {fam: a.num_to_run for fam in families}
    for input_folder in inputs:
        input_folder = input_folder.resolve()
        if not input_folder.is_dir():
            print(f"skip: corpus input not found -> {input_folder}", flush=True)
            continue
        label = corpus.label_for(input_folder)
        print(
            f"full-run: {hm} | corpus={input_folder} (label={label}) | fam={a.family} | "
            f"out={out_root} | num={a.num_to_run} | conc={a.scenario_concurrency} | "
            f"scenarios={len(names)}"
            + (
                f" | instances-file={a.instances_file} ({len(allow.all_ids)} ids)"
                if allow
                else ""
            ),
            flush=True,
        )
        for fam in families:
            budget = remaining[fam]
            if budget is not None and budget <= 0:
                continue
            ran = run_family(
                input_folder,
                fam,
                names,
                budget,
                runner,
                out_root,
                heavy,
                label,
                hm,
                source,
                scenario_concurrency=a.scenario_concurrency,
                allow=(allow.for_family(fam) if allow else None),
                scratch_root=work_base,
                evict_gold_images=a.evict_gold_images,
            )
            if budget is not None:
                remaining[fam] = budget - (ran or 0)


if __name__ == "__main__":
    main()
