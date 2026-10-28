# Instance authoring

Authors two-agent dataset instances from the ranked candidates produced by
`../prelim_suggestions`. `codex` writes each instance, Docker runs its
soundness truth table in the task's SWE-bench Pro image, and the whole
author → verify → correct → audit → finalize loop runs inline. Pure stdlib; needs
`python3`, `codex`, `docker`, `git`.

## Run
```bash
# the two families are separate processes and can run in parallel
./run_authoring.sh contradictory 20
./run_authoring.sh complementary 10
LIMIT=1 AUTHOR_KEEP_WORK=1 ./run_authoring.sh contradictory 1
```

Progress: each instance prints its phase with elapsed seconds, e.g.
`[contr|flipt|e9c6eeb534f4] +0s stage (clone repo)` → `+3s author (codex)` →
`verify (docker truth table)` → `sound -> audit (codex)` → the `+1 (n/target)` summary line.

Concurrency: each family process defaults to concurrency 1, and a cross-process
file lock serializes the verify step so the two never run a container at once.
`CONCURRENCY>1` (or a third argument) also works; verify stays serialized but
codex calls run concurrently.

## Pipeline (per instance)
1. **stage**: clone repo@base; write the SWE-bench Pro row as Agent A, the
   suggestion, 2 in-context example seeds, the schema, a `seed_template`, and the author prompt + test-id notes.
2. **author**: `codex` writes `OUTPUT_seed.json` (Agent A = the SWE-bench Pro task;
   Agent B = a new independently-motivated task; + reconciliation / integration).
3. **assemble**: inject the task's own SWE-bench Pro `run_script.sh` + `parser.py`
   (from `inputs/gt_harness/<id>/`); missing ground truth is a hard error. The
   author is handed copies (`GROUND_TRUTH_*`) and must emit fail_to_pass ids
   byte-identical to what the parser produces.
4. **validate**: schema fields + every diff `git apply --check`s.
5. **verify**: docker truth table (contradictory 7 checks / complementary 3).
6. **correct**: feed the per-check diagnostic back to codex, re-verify (≤ 2).
7. **audit**: codex independence + blind-rule gate.
8. **finalize**: clean instance → `outputs/generated/<family>/<id>.json`.

## Storage
- **Persisted**: `./outputs/`: `generated/<family>/<id>.json`, `ledger_<family>.jsonl`.
- **Scratch**: `<repo>/.local/author/` (`AUTHOR_SCRATCH`): repo clones, codex logs,
  seed assembly, verify I/O. Each instance's workdir is deleted when it finishes,
  and so is its image (`AUTHOR_KEEP_IMAGES=1` keeps images).
- Resumable: finalized instances in `outputs/` are skipped; rerun the same command.

## Inputs
- `../prelim_suggestions/outputs/rows/<id>.json`: Agent-A rows (`python -m
  swebench_pro.download` from `prelim_suggestions/`).
- `../prelim_suggestions/outputs/ordering_{contradictory,complementary}.jsonl`:
  confidence-ranked candidates. `PRELIM_OUTPUTS` overrides this outputs directory.
- `inputs/gt_harness/<id>/{run_script.sh,parser.py}`: each task's ground-truth
  test harness.
- `../dataset/v1/seeds/{contradictory,complementary}/*.json`: example bank (shape only).

## Config (env)
`CONCURRENCY`, `LIMIT` (cap attempts this run), `AUTHOR_MODEL` (gpt-5.6-sol),
`AUTHOR_REASONING` (medium), `AUTHOR_CODEX` (codex binary or path; set
`CODEX_HOME` for a non-default profile), `PYTHON` (python3), `AUTHOR_SCRATCH`,
`AUTHOR_OUTPUT`, `AUTHOR_WORK`, `AUTHOR_KEEP_WORK=1` (keep workdirs),
`AUTHOR_KEEP_IMAGES=1`, `AUTHOR_NO_VERIFY_LOCK=1`.

## Diversity (manual, every ~10 instances)
```bash
python3 -m authoring.diversity_audit --family both
```
Advisory cross-set report, saved as `<AUTHOR_WORK>/<family>/diversity_report_<ts>.json`:
flags over-concentration, lists `avoid_next` buckets; changes nothing in `generated/`.
