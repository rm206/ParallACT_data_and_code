# engine

Runs two-agent (and single-agent baseline) coordination scenarios against a seed
and writes a bundle per run. A run produces patches against the seed's base commit
plus a manifest (and per-turn provenance); grading is a separate program (`eval/`)
that reads the bundle.

Agent backends sit behind a `Runner` interface (`runner/`): Claude Code
(`claude -p`), Codex (`codex exec`) and opencode (`opencode run`), each run as a
subprocess in the workspace directory. `engine/run.py` drives Claude Code only;
`../run.py` selects any of the three.

## Model

- A **turn** is one agent invocation in a workspace. Every execution mode is a
  schedule of turns:
  - `oracle` — one turn, both problem statements fused.
  - `orchestrator` — one turn, both statements fused; the agent must delegate
    each requirement to one of two subagents and do no implementation itself.
  - `sequential` — two turns, second starts from the first's result.
  - `reentrant` — four turns, alternating, each on the evolving result.
  - `parallel` — two turns from the same base, run concurrently, kept separate.
- A **scenario** is a declarative config in `scenarios.py`.
- A run's output is `outputs/*.patch`, each applying to `base_commit`.
  Single-repo modes emit `final.patch`; `parallel` emits `A.patch` and `B.patch`
  and does not merge them (merging is an eval concern).

## Scenarios

Nineteen scenarios are registered in `scenarios.py` (the name is the `--scenario`
value). `repo` = the next agent sees file state only; `hist` = it also sees the
prior agent's git history.

| Name | Mode | Turns | Coordination | Output |
|------|------|-------|--------------|--------|
| `oracle` | oracle | one agent, both problem statements fused | none | `final.patch` |
| `orchestrator` | orchestrator | one agent, both statements; must delegate each to one of two subagents and do no work itself | none | `final.patch` |
| `sequential_AB_repo` | sequential | A then B, B sees file state only | none | `final.patch` |
| `sequential_AB_hist` | sequential | A then B, B sees A's history | none | `final.patch` |
| `sequential_BA_repo` | sequential | B then A, A sees file state only | none | `final.patch` |
| `sequential_BA_hist` | sequential | B then A, A sees B's history | none | `final.patch` |
| `reentrant_ABAB_repo` | reentrant | A B A B, file state only | none | `final.patch` |
| `reentrant_ABAB_hist` | reentrant | A B A B, history visible | none | `final.patch` |
| `reentrant_BABA_repo` | reentrant | B A B A, file state only | none | `final.patch` |
| `reentrant_BABA_hist` | reentrant | B A B A, history visible | none | `final.patch` |
| `parallel_unaware` | parallel | A, B concurrent from base | not told another agent exists | `A.patch`, `B.patch` |
| `parallel_aware` | parallel | A, B concurrent from base | told another agent exists, no channel | `A.patch`, `B.patch` |
| `parallel_message` | parallel | A, B concurrent from base | told to use `send-msg`/`recv-msg` | `A.patch`, `B.patch` |
| `parallel_sync` | parallel | A, B concurrent from base | same channel, framed as sync points | `A.patch`, `B.patch` |
| `parallel_message_redis` | parallel | A, B concurrent from base | `parallel_message` over the Redis transport | `A.patch`, `B.patch` |
| `parallel_sync_redis` | parallel | A, B concurrent from base | `parallel_sync` over the Redis transport | `A.patch`, `B.patch` |
| `parallel_comm_oracle` | parallel | A, B concurrent from base | `parallel_message` plus each agent is given the partner's requirement and told to communicate to jointly solve both (`coordination/comm_oracle.md`) | `A.patch`, `B.patch` |
| `oracle_with_gold_tests` | oracle | as `oracle` | none; the agent can read and run the full gold test set | `final.patch` |
| `parallel_oracle_with_gold_tests` | parallel | as `parallel_unaware` (contradictory only) | none; each agent can read and run its own half's gold tests | `A.patch`, `B.patch` |

A channel is provisioned only for the `parallel_message*`, `parallel_sync*` and
`parallel_comm_oracle` scenarios. `recv-msg` returns at once; `recv-msg --wait [N]`
blocks up to N seconds (default 90) for a peer message and prints `no message yet`
on timeout. The default transport is an on-disk file queue that each agent reads
through a cursor. The `_redis` variants use per-agent Redis inboxes that are
drained on read; they need a reachable Redis (`REDIS_URL`, default
`redis://localhost:6379/0`) and the `redis` Python package, otherwise the scenario
fails and is skipped without a bundle. Both transports expose the same
`send-msg`/`recv-msg` commands.

Gold-test scenarios give each agent its tests under `_gold_tests/` and a
`./run-tests` command that runs them in a container from the instance's eval
image (`testaccess.py`). Without docker, `run-tests` reports that it is unavailable.
Container lifecycle goes to `gt.log` and each `./run-tests` call to
`run_tests_<agent>.log`.

## Files

| File | Holds |
|------|-------|
| `types.py` | Shared typed data and enums, including `Usage`, the backend-neutral cost/token record each runner fills (backend extras go on a `Usage` subclass). No logic. |
| `workspace.py` | Git working copy at `base_commit`, obtained via a `RepoSource` (`CachedCloneSource`, or `GitCloneSource` for a direct clone). Snapshot, diff against base, history visibility, untracked files. |
| `runner/base.py` | `Runner` protocol. |
| `runner/claude_code.py` | `ClaudeCodeRunner`: runs `claude -p` in a workspace and returns diff, transcript and usage (`ClaudeCodeUsage`). `for_backend` resolves `--backend`; `for_vllm` points it at a vLLM Anthropic endpoint. |
| `runner/codex.py` | `CodexRunner`: runs `codex exec` against a vLLM Responses API endpoint. |
| `runner/opencode.py` | `OpencodeRunner`: runs `opencode run` against a vLLM OpenAI-compatible endpoint. |
| `channel.py` | `Channel` protocol, `NullChannel`, `QueueChannel` (file queue) and `RedisChannel` (Redis inboxes). Both write the same per-workspace `send-msg`/`recv-msg` scripts. Message vs sync framing is in the prompt, not here. |
| `testaccess.py` | Gold-test provisioning and the per-turn test container for `test_access == OWN`. |
| `prompts.py` | `build_prompt(...)`: assembles a turn's prompt from templates in `prompts_running/`. |
| `scenarios.py` | The scenario registry and `expand()` (config -> schedule of turns). |
| `orchestrator.py` | `run_scenario(...) -> RunResult`: expands the schedule, manages workspaces, runs parallel turns concurrently, wires the channel and test access, applies visibility. |
| `artifacts.py` | Writes the run bundle (`manifest.json`, `outputs/`, `comm.jsonl`, `turns/`). This is the run/eval contract. |
| `corpus.py` | Resolves `--input-folder` + `--family` to a sorted list of instance files. |
| `run.py` | CLI entry point: corpus x scenarios -> orchestrate -> write bundles. Resumable. |

Prompt text lives in `../prompts_running/`, one subfolder per role: `task/`
(`oracle.md`, `orchestrator.md`, `single.md`), `coordination/` (`unaware.md`,
`aware.md`, `message.md`, `sync.md`, `comm_oracle.md`), `handoff/`
(`repo_only.md`, `with_history.md`) and `testaccess/` (`own.md`). A
`coordination/<mode>.<family>.md` file, if present, overrides `<mode>.md` for that
family.

## Running

The full-corpus runner is `running_instances/common/run.py` (see
`running_instances/README.md`). `engine/run.py` is the lower-level entry point; it
runs scenarios across a corpus laid out as `<input-folder>/<family>/instance_*.json`.

```
cd running_instances/common
uv run python -m engine.run --input-folder ../../dataset/v1/seeds --family comple \
    --num-to-run 2 [--scenario NAME ...] [--backend claude|claude-deepseek|claude-glm] [--model M]
```

- `--family` is `contra` | `comple` | `both`.
- `--num-to-run N` picks the next N instances per family in sorted order and is
  resumable: instances whose selected scenarios already have output are skipped,
  so N means "N not-yet-run instances".
- `--scenario` is repeatable; omitted = every registered scenario.
- `--backend`: `claude` (default) is the `claude` binary with
  `claude-opus-4-8[1m]` (`--model` overrides); `claude-deepseek` / `claude-glm`
  point Claude Code at OpenRouter (`OPENROUTER_API_KEY`); anything else is a
  literal binary/path and needs `--harness-model`.
- `--instances-file` restricts the run to listed ids (`<family> <id>` or bare `<id>`).
- `--scenario-concurrency N` runs up to N scenarios of one instance at once (default 1).
- `--max-retries`, `--rate-limit-retries`, `--rate-limit-delay` control turn
  retries; a usage limit that outlasts them stops the run, and re-running the
  same command resumes it.

## Run bundle layout

With `engine/run.py` the run/eval contract and the per-turn provenance go to
separate roots (`../run.py` puts both in one bundle by default). Both are
namespaced `<root>/<harness_model>/<label>/<family>/<seed_id>/<scenario>/`, where
`harness_model` defaults from `--backend` and `label` defaults to the
input-folder basename.

```
# --out (default runs_output/): the run/eval contract
<out>/<harness_model>/<label>/<family>/<seed_id>/<scenario>/
  manifest.json            scenario, seed, base_commit, backend, timing,
                           per-turn usage + summed usage_total (cost, tokens)
  outputs/                 patches handed to eval, each applies to base_commit
    final.patch            (single-repo modes)
    A.patch  B.patch       (parallel)
  comm.jsonl               peer-message log (empty for non-channel modes)
  gt.log, run_tests_*.log  gold-test logs (gold-test scenarios only)

# --heavy-root (default .local/running/): provenance, checkouts, cache
<heavy>/<harness_model>/<label>/<family>/<seed_id>/<scenario>/
  turns/NN_<agent>/
    prompt.txt             exact prompt sent
    transcript.log         backend transcript
    turn.patch             diff produced this turn
<heavy>/<harness_model>/<label>/<family>/_work/   workspace checkouts + channel scratch (ephemeral)
<heavy>/repo_cache/mirrors/                        bare per-repo mirrors, shared across runs
```

## Repo cache

Workspaces are cloned from a local bare mirror per repo
(`<heavy-root>/repo_cache/mirrors/<owner>__<repo>.git`; `../run.py` uses
`.local/run_scratch/repo_cache/`). The mirror is cloned from GitHub
on first use (under a lock, renamed into place atomically); each workspace is then
a local clone checked out at `base_commit` and is deleted after the scenario.

## Dependency direction

`types` <- everything. `orchestrator` depends on `runner`, `workspace`,
`channel`, `testaccess`, `prompts`, `scenarios`. `run` sits on top. Evaluation
reads only what `artifacts.py` writes.

## Extending

New per-run capabilities follow one pattern and touch neither `Runner`,
`orchestrator`'s core loop, nor the run/eval contract:

1. Add a flag to `types.py` (enum + field on `ScenarioConfig`).
2. Provision what the workspace needs (`workspace.py` or a module like `testaccess.py`).
3. Add the prompt fragment under `prompts_running/` and select it in `prompts.py`.
4. Set the flag per scenario in `scenarios.py`.

`TestAccess` follows this pattern: on `OWN`, `testaccess.py` provisions the gold
tests as untracked files (so they never enter a patch) plus a `run-tests` helper,
and `prompts_running/testaccess/own.md` tells the agent about them.

New backend: add a file under `runner/` implementing the `Runner` protocol.

New coordination framing: add a `coordination/` template and a `Coordination`
value. New combine strategy: eval-side only, not here.
