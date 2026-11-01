# ParallACT: Data and Code

Website: [https://lingyunxiao18.github.io/ParallACT_website/](https://lingyunxiao18.github.io/ParallACT/)
<!-- Paper Link -->

## Layout

```
dataset/
  v1/generated/{contradictory,complementary}/   58 instances
  v1/seeds/{contradictory,complementary}/       27 instances
  v2/generated/{contradictory,complementary}/   70 instances
prelim_suggestions/     1. pick candidate SWE-bench Pro tasks and rank them
author_new_instances/   2. author instances from the ranked candidates and verify them
running_instances/      3. serve a model and run agent harnesses on the instances
eval/                   4. grade the run bundles
```

## Setup

```bash
uv sync
```

Outside Python you need:

| for | needs |
|---|---|
| running + eval | Docker |
| running | the harness CLIs you use: `claude`, `codex`, `opencode` supported |
| running (`*_redis` scenarios) | `redis-server` |
| running | an OpenAI/Anthropic-compatible model endpoint; `running_instances/serve_model_scripts/` serves one with vLLM |
| eval (`reconciler` strategy) | `CooperBench/Qwen2.5-Coder-0.5B-Merge-Resolver` |
| building instances | Docker, `codex`, `git`, and a model endpoint for `prelim_suggestions` |

Environment variables are listed in `.env.example`.

## Instance format

One JSON file per instance, `instance_<id>.json`:

| field | meaning |
|---|---|
| `instance_id`, `repo`, `base_commit`, `family` | identity and starting point |
| `agentA_problem_statement`, `agentB_problem_statement` | the two requests |
| `agentA_solution`, `agentB_solution` | reference implementations (diffs against `base_commit`) |
| `agentA_test_patch`, `agentB_test_patch`, `agentA_fail_to_pass`, `agentB_fail_to_pass`, `agentA_pass_to_pass` | each request's tests |
| contradictory: `reconciliation_patch`, `reconciliation_explanation`, `combined_test_patch` | a correct merge of both and the tests it must pass |
| complementary: `integration_test_patch`, `integration_fail_to_pass` | the integration tests over both halves |
| `mutex_type`, `shared_artifact`, `diversity_mechanism`, `natural_language_explanation` | what the two requests share and why they interact |
| `runtime` | `image_uri`, `run_script`, `parser`, `selected_test_files_to_run`, `before_repo_set_cmd`, `repo_language` |

## Usage

Run one harness x model over a corpus (from `running_instances/common/`):

```bash
uv run python run.py --harness codex --model qwen --corpus v2 --scenario-concurrency 8
```

Bundles go to `run_outputs/<corpus>/<harness>__<model>/<label>/<family>/<instance_id>/<scenario>/`.
See `running_instances/README.md`.

**Grade** (from the repo root):

```bash
EVAL_RUN_TIMEOUT=2400 uv run python -m eval.grade --corpus v2 --family both --jobs 4
```

Results go to `eval_outputs/<corpus>/...`, one JSON per scenario plus a
`summary.json` per harness × model × label × family. See `eval/README.md`.

Build new instances: `prelim_suggestions/README.md`, then `author_new_instances/README.md`.
