"""CLI: run scenarios across a corpus (<input-folder>/<family>/instance_*.json) and write bundles.

  uv run python -m engine.run --input-folder DIR --family comple --num-to-run 2 \
      [--scenario NAME ...] [--backend claude|claude-deepseek|claude-glm] [--model M]

Selection is sorted and resumable: --num-to-run N picks N instances per family that
still have unrun scenarios. The manifest and patches go to --out; transcripts,
prompts and per-turn patches go to --heavy-root.
"""

from __future__ import annotations

import argparse
import shutil
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from . import artifacts, corpus, orchestrator, scenarios, testaccess
from .runner import ClaudeCodeRunner
from .types import RateLimited
from .workspace import CachedCloneSource

# Scenario order used when running several scenarios of one instance at once.
# Scenarios differ in concurrent turns (orchestrator ~3, parallel_* 2, the rest 1);
# this order mixes them so each group of 4 stays at a similar load. Gold-test
# scenarios go last to keep their docker load separate.
SCENARIO_ORDER = [
    "orchestrator",
    "oracle",
    "sequential_AB_repo",
    "sequential_AB_hist",
    "parallel_unaware",
    "parallel_aware",
    "sequential_BA_repo",
    "sequential_BA_hist",
    "parallel_message",
    "parallel_sync",
    "reentrant_ABAB_repo",
    "reentrant_ABAB_hist",
    "parallel_message_redis",
    "parallel_sync_redis",
    "reentrant_BABA_repo",
    "reentrant_BABA_hist",
    "parallel_comm_oracle",
    "oracle_with_gold_tests",
    "parallel_oracle_with_gold_tests",
]


# Output namespace per backend, so runs of different models never collide or
# resume over each other: <root>/<harness_model>/<label>/<family>/...
BACKEND_HARNESS_MODEL = {
    "claude": "claude_code__opus-4.8",
    "claude-deepseek": "claude_code__deepseek-v4-flash-0731",
    "claude-glm": "claude_code__glm-5.3-flash",
}


def default_harness_model(backend: str) -> str:
    try:
        return BACKEND_HARNESS_MODEL[backend]
    except KeyError:
        raise SystemExit(
            f"no default --harness-model for backend {backend!r}; "
            f"pass --harness-model explicitly"
        )


def _scenario_names(selected: list[str] | None) -> list[str]:
    names = selected or list(scenarios.REGISTRY)
    unknown = [n for n in names if n not in scenarios.REGISTRY]
    if unknown:
        raise SystemExit(f"unknown --scenario: {', '.join(unknown)}")
    return names


_FAM_ALIAS = {
    "contra": "contradictory",
    "comple": "complementary",
    "contradictory": "contradictory",
    "complementary": "complementary",
}


class AllowList:
    """A parsed --instances-file.

    Lines are `<family> <instance_id>` (that family only) or a bare `<instance_id>`
    (any family). The same id can exist in both families, so qualify it to run one.
    """

    def __init__(self, by_family: dict[str, set[str]], anyfam: set[str]) -> None:
        self._by_family = by_family
        self._anyfam = anyfam

    def for_family(self, family: str) -> set[str]:
        return self._by_family.get(family, set()) | self._anyfam

    @property
    def all_ids(self) -> set[str]:
        out = set(self._anyfam)
        for s in self._by_family.values():
            out |= s
        return out


def _load_instances_file(path: str | None) -> AllowList | None:
    """Parse an --instances-file into an AllowList (None if no path).

    Blank lines and # comments are ignored. Ids not in the current corpus are
    skipped, so one file can cover several corpora.
    """
    if not path:
        return None
    by_family: dict[str, set[str]] = {}
    anyfam: set[str] = set()
    for raw in Path(path).read_text().splitlines():
        ln = raw.strip()
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split()
        if len(parts) == 1:
            anyfam.add(parts[0])
        else:
            fam = _FAM_ALIAS.get(parts[0].lower())
            if fam is None:
                raise SystemExit(
                    f"--instances-file: bad family {parts[0]!r} in line: {ln}"
                )
            by_family.setdefault(fam, set()).add(parts[1])
    allow = AllowList(by_family, anyfam)
    if not allow.all_ids:
        raise SystemExit(f"--instances-file {path} has no instance ids")
    return allow


def plan_family(
    input_folder: Path,
    family: str,
    scenario_names: list[str],
    num_to_run: int | None,
    tracked_fam: Path,
    allow: set[str] | None = None,
) -> list[tuple[Path, str, list[str]]]:
    """Pick the next `num_to_run` instances that still have unrun scenarios.

    Returns (path, seed_id, todo_scenarios) per instance. A scenario counts as run
    once its tracked manifest exists. `allow` restricts selection to those ids.
    """
    applicable = [
        s
        for s in scenario_names
        if scenarios.REGISTRY[s].families is None
        or family in scenarios.REGISTRY[s].families
    ]
    plan: list[tuple[Path, str, list[str]]] = []
    for path in corpus.list_instances(input_folder, family):
        if num_to_run is not None and len(plan) >= num_to_run:
            break
        seed_id = corpus.load(path)["instance_id"]
        if allow is not None and seed_id not in allow:
            continue
        todo = [
            s
            for s in applicable
            if not (tracked_fam / seed_id / s / "manifest.json").exists()
        ]
        if todo:
            plan.append((path, seed_id, todo))
    return plan


def _order_scenarios(todo: list[str], concurrency: int) -> list[str]:
    """At concurrency > 1 order by SCENARIO_ORDER (unknown names last); else keep `todo`'s order."""
    if concurrency <= 1:
        return list(todo)
    todo_set = set(todo)
    return [s for s in SCENARIO_ORDER if s in todo_set] + [
        s for s in todo if s not in SCENARIO_ORDER
    ]


def run_family(
    input_folder: Path,
    family: str,
    scenario_names: list[str],
    num_to_run: int | None,
    runner: ClaudeCodeRunner,
    out_root: Path,
    heavy_root: Path,
    label: str,
    harness_model: str,
    source: CachedCloneSource,
    scenario_concurrency: int = 1,
    allow: set[str] | None = None,
    scratch_root: Path | None = None,
    evict_gold_images: bool = False,
) -> int:
    tracked_fam = out_root / harness_model / label / family
    heavy_fam = heavy_root / harness_model / label / family
    # Repo checkouts and channel scratch; defaults to heavy_root if no scratch_root.
    work_root = (scratch_root or heavy_root) / harness_model / label / family / "_work"
    # _work holds only scratch. Wipe it so checkouts orphaned by a killed run don't
    # accumulate; resuming relies on the bundles, not on _work.
    shutil.rmtree(work_root, ignore_errors=True)
    work_root.mkdir(parents=True, exist_ok=True)

    def _run_scenario(seed: dict, seed_id: str, name: str) -> tuple[str, str, object]:
        """Run and write one scenario; returns (status, name, detail).

        status is 'ok', 'skip' (error) or 'rate' (RateLimited). Never raises, so
        in-flight scenarios can finish before the run stops.
        """
        scenario = scenarios.REGISTRY[name]
        run_dir = work_root / seed_id / name
        run_dir.mkdir(parents=True, exist_ok=True)
        print(f"[{family}/{name}] {seed_id} ...", flush=True)
        try:
            result = orchestrator.run_scenario(
                seed, scenario, runner, work_root, run_dir, source
            )
            bundle = tracked_fam / seed_id / name
            artifacts.write(result, bundle, heavy_fam / seed_id / name)
            # Gold-test logs are written to run_dir, which is scratch; keep them
            # with the bundle.
            for lg in sorted(run_dir.glob("gt.log")) + sorted(
                run_dir.glob("run_tests_*.log")
            ):
                try:
                    shutil.copy2(lg, bundle / lg.name)
                except OSError:
                    pass
            print(f"[{family}/{name}] -> {bundle}", flush=True)
            return ("ok", name, None)
        except RateLimited as e:
            return ("rate", name, e)
        except Exception as e:  # noqa: BLE001
            # One failed scenario must not abort the corpus; with no bundle it is
            # retried on the next run.
            print(f"[{family}/{name}] SKIPPED: {e!r}", flush=True)
            return ("skip", name, e)

    conc = max(1, scenario_concurrency)
    plan = plan_family(
        input_folder, family, scenario_names, num_to_run, tracked_fam, allow
    )
    for path, seed_id, todo in plan:
        seed = corpus.load(path)
        ordered = _order_scenarios(todo, conc)
        rate: RateLimited | None = None
        if conc == 1:
            for name in ordered:
                st, _, d = _run_scenario(seed, seed_id, name)
                if st == "rate":
                    rate = d  # type: ignore[assignment]
                    break
        else:
            # Keep up to `conc` scenarios in flight, submitting the next as a slot
            # frees. After a RateLimited, stop submitting and let in-flight ones drain.
            it = iter(ordered)
            with ThreadPoolExecutor(max_workers=conc) as pool:
                futs = {
                    pool.submit(_run_scenario, seed, seed_id, n)
                    for n in (next(it, None) for _ in range(conc))
                    if n is not None
                }
                while futs:
                    done, futs = wait(futs, return_when=FIRST_COMPLETED)
                    for f in done:
                        st, _, d = f.result()
                        if st == "rate" and rate is None:
                            rate = d  # type: ignore[assignment]
                    if rate is None:
                        for _ in done:
                            n = next(it, None)
                            if n is not None:
                                futs.add(pool.submit(_run_scenario, seed, seed_id, n))
        # Free disk by removing this instance's eval image if this process pulled it.
        if evict_gold_images:
            img = (seed.get("runtime") or {}).get("image_uri")
            if img:
                testaccess.evict_pulled_image(
                    img, lambda m: print(f"[{family}/{seed_id}] {m}", flush=True)
                )
        if rate is not None:
            print(
                f"[{family}] RATE-LIMITED; stopping run (resumable): {rate}", flush=True
            )
            raise rate
    print(f"[{family}] launched {len(plan)} instance(s)", flush=True)
    return len(plan)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Run coordination scenarios over a corpus."
    )
    ap.add_argument(
        "--input-folder",
        required=True,
        help="corpus root laid out as <folder>/<family>/instance_*.json",
    )
    ap.add_argument(
        "--family",
        default="both",
        help="contra|comple|both (aliases of contradictory/complementary)",
    )
    ap.add_argument(
        "--num-to-run",
        type=int,
        default=None,
        help="run this many not-yet-run instances per family (default: all)",
    )
    ap.add_argument(
        "--instances-file",
        default=None,
        help="path to a file of instance_ids (one per line; # comments "
        "ok; optional '<family> <id>'). Only these instances run. Ids "
        "not in this --input-folder are skipped, so one file can span "
        "several corpora.",
    )
    ap.add_argument(
        "--scenario",
        action="append",
        default=None,
        help="scenario name (repeatable); default is all registered",
    )
    ap.add_argument(
        "--backend",
        default="claude",
        help="agent backend: claude | claude-deepseek | claude-glm | <binary>",
    )
    ap.add_argument("--model", default=None, help="claude model override")
    ap.add_argument(
        "--harness-model",
        default=None,
        help="output namespace grouping runs by harness+model "
        "(default: derived from --backend, e.g. claude_code__opus-4.8)",
    )
    ap.add_argument(
        "--label",
        default=None,
        help="output namespace (default: input folder basename)",
    )
    ap.add_argument(
        "--out",
        default="runs_output",
        help="output root for manifests, patches and comm logs",
    )
    ap.add_argument(
        "--heavy-root",
        default=".local/running",
        help="root for prompts, transcripts, turn patches, checkouts, repo cache",
    )
    ap.add_argument(
        "--scenario-concurrency",
        type=int,
        default=1,
        help="how many scenarios of one instance to run at once (default 1 = serial)",
    )
    ap.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="retries for a transient turn failure (broken envelope, "
        "5xx, non-zero exit, timeout) before the scenario is skipped",
    )
    ap.add_argument(
        "--rate-limit-retries",
        type=int,
        default=2,
        help="retries when the account hits a usage/session limit "
        "before the whole run stops (resumable)",
    )
    ap.add_argument(
        "--rate-limit-delay",
        type=float,
        default=300.0,
        help="seconds to wait between usage/session-limit retries",
    )
    args = ap.parse_args()

    input_folder = Path(args.input_folder)
    scenario_names = _scenario_names(args.scenario)
    allow = _load_instances_file(args.instances_file)
    label = corpus.label_for(input_folder, args.label)
    harness_model = args.harness_model or default_harness_model(args.backend)
    runner = ClaudeCodeRunner.for_backend(
        args.backend,
        model=args.model,
        max_retries=args.max_retries,
        rate_limit_retries=args.rate_limit_retries,
        rate_limit_delay=args.rate_limit_delay,
    )
    # Absolute, because channel paths derived from it are embedded in send-msg /
    # recv-msg, which run with cwd = the agent's workspace.
    heavy_root = Path(args.heavy_root).resolve()
    source = CachedCloneSource(heavy_root / "repo_cache")

    print(
        f"corpus={input_folder}  label={label}  harness_model={harness_model}  "
        f"backend={runner.name}  scenarios={len(scenario_names)}",
        flush=True,
    )
    if allow is not None:
        matched = 0
        for fam in corpus.resolve_families(args.family):
            present = {
                corpus.load(p)["instance_id"]
                for p in corpus.list_instances(input_folder, fam)
            }
            matched += len(allow.for_family(fam) & present)
        total = len(allow.all_ids)
        print(
            f"instances-file: {matched}/{total} listed (family,id) pairs present in "
            f"this corpus ({total - matched} in other corpora/family — skipped)",
            flush=True,
        )
        if not matched:
            print(
                "WARNING: no listed instances match this --input-folder; "
                "nothing will run. Wrong corpus or file?",
                flush=True,
            )
    try:
        for family in corpus.resolve_families(args.family):
            run_family(
                input_folder,
                family,
                scenario_names,
                args.num_to_run,
                runner,
                Path(args.out),
                heavy_root,
                label,
                harness_model,
                source,
                scenario_concurrency=args.scenario_concurrency,
                allow=None if allow is None else allow.for_family(family),
            )
    except RateLimited as e:
        raise SystemExit(
            f"STOPPED: backend hit its usage/session limit — {e}\n"
            f"Re-run the same command once the limit resets; already-"
            f"finished scenarios are skipped."
        )


if __name__ == "__main__":
    main()
