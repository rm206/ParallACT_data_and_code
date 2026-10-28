# prelim-suggestions

Prelim exploration over SWE-bench Pro (`ScaleAI/SWE-bench_Pro`, config `default`,
split `test`, 642 rows) with `Qwen/Qwen3.8-27B-FP8` served by vLLM, using native
tool calling. `swebench_pro/` holds the dataset and repo mechanics, `suggest/` the
stage itself. It runs in the repo's uv environment (`uv sync`).

## What it does
For each selected SWE-bench Pro task (task A), an agent explores the repo at its
base commit and judges whether an independent task B could pair with it into a
*contradictory* or *complementary* instance, with a 0–5 confidence. The output is
a suggestion for the authoring step (`../author_new_instances`), not a finished
instance.

## Run
Serve the model on a GPU machine with docker:
```bash
bash ../running_instances/serve_model_scripts/serve_prelim.sh
```
Then:
```bash
./run_prelim.sh 1      # try it: 1 candidate end-to-end
./run_prelim.sh 5      # extends to 5
./run_prelim.sh 100    # extends to 100
CONCURRENCY=8 ./run_prelim.sh 100
```
`run_prelim.sh` waits for the server at `VLLM_BASE_URL`, then runs
`python -m suggest.run --target N --concurrency C` (`C` from the second argument
or `CONCURRENCY`, default 4). With a server already up, the steps can be run
directly from this folder:
```bash
uv run python -m swebench_pro.download      # rows -> outputs/rows/ (suggest.run also does this)
uv run python -m suggest.run --target 100   # select -> explore -> order (resumable)
uv run python -m suggest.order --model Qwen/Qwen3.8-27B-FP8   # rebuild the orderings only
```

## Resumability
`--target` is a high-water mark; rerun the same command to resume.
- `candidates.jsonl` is a fixed draw that grows with `--target` and never reshuffles.
- Each assessment is written atomically when its instance completes, so a crash
  leaves nothing partial. Instances with an assessment are skipped (including
  `incomplete` ones that never called `finish`); failed instances are retried.
- Scratch is disposable and recreated as needed.

## Storage
- **Kept** in `./outputs/` (or `$PRELIM_OUTPUTS`): `candidates.jsonl`,
  `assessments/<model_slug>/<id>.json`, `ordering_{contradictory,complementary}.jsonl`,
  plus the downloaded `rows/` (re-downloadable).
- **Scratch** in `$PRELIM_TMP` (default `<repo>/.local/prelim`): git `mirrors/` and
  per-instance `checkouts/`, the only place the agent reads. Each checkout is
  deleted after its instance and a repo's mirror once its instances are done, so
  peak usage is about one mirror plus one checkout per concurrent worker.
- Model weights and the HF datasets cache follow `HF_HOME`.

## Config (env)
`VLLM_MODEL` (default `Qwen/Qwen3.8-27B-FP8`), `VLLM_BASE_URL`
(`http://localhost:8000/v1`), `VLLM_TEMPERATURE` (0.6), `VLLM_TOP_P` (0.95),
`VLLM_MAX_TOKENS` (8192), `VLLM_TIMEOUT` (600), `VLLM_API_KEY` (`EMPTY`);
`PRELIM_TMP`, `PRELIM_OUTPUTS`; `CONCURRENCY` (4, `run_prelim.sh` only).

## Excluded instances
`suggest/exclude_ids.txt` lists the 80 SWE-bench Pro tasks used by the v1
instances (`dataset/v1`); selection never re-picks them.
