# eval

Grades run bundles against their instances. Self-contained (no imports from
`running_instances/`); reads only a bundle's `outputs/*.patch` + `manifest.json`
and the instance JSON.

## What it does

Per `(instance, scenario)`, apply the agent's code at `base_commit` in the
instance's image, add the gold test patches, and run the instance's own
`runtime.run_script` + `runtime.parser`. Groups:

- **Contradictory** → **A / B / scored**. `A` = `agentA_test_patch` and
  `agentA_fail_to_pass` on A's code, `B` likewise, `scored` = `combined_test_patch`
  with A's ∪ B's `fail_to_pass` on the combined code.
- **Complementary** → **scored only**: `integration_test_patch` /
  `integration_fail_to_pass`.

A group passes when every `fail_to_pass` id is `PASSED`; `pass_to_pass` (A/B only)
is reported but not required.

Parallel scenarios emit `A.patch` + `B.patch`; eval combines them by each strategy
and scores each:

- `concat`: the two diffs concatenated.
- `git-merge`: two branches off `base_commit`, `git merge`; a conflict fails.
- `reconciler`: `git-merge`, then each conflict hunk is resolved by the CooperBench
  merge-resolver model.

Serial scenarios (`oracle*`, `sequential_*`, `reentrant_*`, `orchestrator`) emit one
`final.patch`, graded as-is (A and B are both run on it). `scored_pass` is true if
any strategy passes.

Grading goes one instance at a time: pull its image if missing, grade every pending
bundle for it across all harness-model namespaces, then delete its scratch under
`--cache-root` (default `.local/eval_cache/`, gitignored).

## Usage

Run from the repo root:

```
uv run python -m eval.grade \
    --corpus v2 --family both \
    [--harness-model claude__qwen3-flash-next ...] \
    [--num-to-run N] [--scenario oracle ...] \
    [--strategies concat,git-merge,reconciler] [--jobs 2] \
    [--rmi-at-end] [--force]
```

With `--corpus v1|v2`, inputs are `dataset/v1/{generated,seeds}` or
`dataset/v2/generated`, `--runs` defaults to `run_outputs/<corpus>` and `--out` to
`eval_outputs/<corpus>`. Without `--corpus`, pass `--input-folder` (a
`<family>/instance_*.json` tree); `--runs` / `--out` then default to
`run_outputs/custom` / `eval_outputs/custom`. `--label` defaults to the input
folder's basename; `--harness-model` defaults to every directory under `<runs>` that
has that label.

Already-graded scenarios are skipped (`--force` re-grades); `--num-to-run` counts
not-yet-graded instances per family. `--jobs` grades that many bundles of one
instance concurrently. Each test run is capped at `EVAL_RUN_TIMEOUT` seconds
(default 2400). Images are kept by default; `--rmi-at-end` removes every image the
invocation touched once it finishes.

## Output

Reads bundles under `<runs>/<harness_model>/<label>/<family>/<instance_id>/<scenario>/`
and writes `<out>/<harness_model>/<label>/<family>/<instance_id>/<scenario>.json`:

| field | holds |
|------|------|
| `seed_id`, `scenario`, `family`, `repo`, `backend`, `harness_model`, `serial` | identity |
| `numbers` | usage, cost, turn count and wall time from the manifest |
| `groups` | `A`, `B` (contradictory only) and `scored: {<strategy>: {combine_status, pass, detail}}` |
| `A`, `B`, `scored_pass` | pass flags |
| `graded_at` | UTC timestamp |

Each runner result (`groups.A`, `groups.B`, `scored.<strategy>.detail`) keeps
`applied` (`ok`/`fail`/`timeout`), `tests_arg`, `all_tests` (every test
`name -> status`), the `fail_to_pass` / `pass_to_pass` subsets, `n_pass`, `n_total`,
`p2p_pass`, `p2p_total`, and stdout/stderr tails. `combine_status` is `ok`,
`apply_fail`, `conflict` or `reconcile_fail`.

`<out>/<harness_model>/<label>/<family>/summary.json` holds `harness_model`,
`family`, `n`, `scored_pass` and every result in that directory.

## Requirements

Docker and git. `git-merge` and `reconciler` fetch the instance repo from GitHub;
`reconciler` downloads its model from Hugging Face on first use (`torch`,
`transformers`, `peft` are project dependencies).

## Files

| File | Holds |
|------|------|
| `runner.py` | Docker: reset → apply combined code patch + gold test patches → run `run_script` → parse → per-test statuses + log tails. |
| `combine.py` | Combine output patches into one code patch applying to `base_commit`, or a failure status. |
| `reconciler.py` | CooperBench merge resolver (LoRA on `Qwen2.5-Coder-0.5B-Instruct`). |
| `grade.py` | `grade_bundle`, per-instance orchestration, and the CLI. |
| `corpus.py` | Corpus layout helpers. |
