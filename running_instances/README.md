# running_instances

Runs a coding-agent harness × model over a corpus of instances, across every
scenario, and writes one run bundle per (instance, scenario).

```
common/
  run.py               full-corpus runner (the CLI below)
  runners.py           (harness, model) -> runner pointed at that model's endpoint
  endpoints.py         model key -> served name + host/port
  engine/              scenarios, orchestrator, workspaces, channels, run bundle writer
  prompts_running/     prompt templates
  opencode_configs/    opencode provider configs (rewritten by the runner)
serve_model_scripts/   serve a model with vLLM in docker on a GPU machine
```

## Run

1. Serve the model (`serve_model_scripts/README.md`). The runners reach it at
   `127.0.0.1:8000` by default; set `MODEL_HOST` / `MODEL_PORT_<KEY>` otherwise.
2. Install the harness CLI: `claude` or `codex` on `PATH`, or opencode at
   `~/.opencode/bin/opencode`. Gold-test scenarios also need docker.
3. Run:

```bash
cd running_instances/common
uv run python run.py --harness claude --model glm --corpus v2 --scenario-concurrency 8
uv run python run.py --harness codex  --model qwen --corpus v1 --num-to-run 1   # 1 per family
```

- `--harness` is `claude`, `codex` or `opencode`; `--model` is a key in `endpoints.py`
  (`qwen` (default), `deepseek`, `glm`).
- `--corpus v1` runs `dataset/v1/{generated,seeds}`, `--corpus v2` runs
  `dataset/v2/generated`; or pass `--input-folder`.
- `--family contra|comple|both`, `--scenario NAME` (repeatable; default all),
  `--instances-file` to target exact ids, `--scenario-concurrency N` (default 8),
  `--timeout` per turn in seconds (default 3600).
- `--out` / `--heavy-root` move the bundle root and the per-turn files;
  `--evict-gold-images` removes each instance's eval image after its scenarios.
- Resumable: scenarios that already have a `manifest.json` are skipped.

The 19 scenarios are `oracle`, `orchestrator`, `sequential_{AB,BA}_{repo,hist}`,
`reentrant_{ABAB,BABA}_{repo,hist}`, `parallel_{unaware,aware,message,sync}`,
`parallel_{message,sync}_redis`, `parallel_comm_oracle`, `oracle_with_gold_tests`
and `parallel_oracle_with_gold_tests`; `common/engine/README.md` describes each.

## Run bundle

```
run_outputs/<corpus>/<harness>__<model>/<label>/<family>/<instance_id>/<scenario>/
  manifest.json              scenario, instance, timing, per-turn usage + usage_total
  outputs/                   final.patch (single-repo scenarios) or A.patch + B.patch (parallel)
  comm.jsonl                 peer messages (empty unless the scenario has a channel)
  turns/NN_<agent>/          prompt.txt, turn.patch, transcript.log
  gt.log, run_tests_*.log    gold-test logs (gold-test scenarios)
```

`<model>` is the served name and `<label>` the input folder's basename. Checkouts
go under `.local/run_scratch/work/` and are deleted as scenarios finish; bare repo
mirrors are kept in `.local/run_scratch/repo_cache/` (`--repo-cache`) for reuse.
