You are authoring ONE **contradictory** dataset instance for a multi-agent coding
benchmark. Do your best-effort work and produce a single JSON file. Work only from
the real code in front of you.

# Where you are
Your working directory contains everything you need:
- `repo/` — the actual codebase, checked out at the instance's `base_commit`. READ IT to ground every diff.
- `source_row.json` — the original SWE-bench-Pro task this instance is derived from: `patch` (the gold single-task solution), `test_patch`, `problem_statement`, `interface`, `fail_to_pass`. **Agent A IS this task** (see below).
- `SUGGESTION.json` — a LOW-AUTHORITY hint from a small scout model proposing a possible agent-B task and the shared code region A and B would collide on. Treat it ONLY as a starting idea: verify it against the real code, and freely improve or replace it. It is NOT authoritative and may be wrong. Agent A is fixed (the original task); the scout's job was only to point at a plausible B and collision point.
- `EXAMPLES.md` — two finished, verified contradictory instances closest to this repo/language. Imitate their SHAPE, harness/test-id conventions, and how the two problem statements read as independent tickets. Do NOT copy their content.
- `seed_template.json` — a partial instance with `instance_id`, `repo`, `base_commit`, `family`, and `runtime` pre-filled. START FROM THIS.
- `SCHEMA.md` — the authoritative format. Obey it exactly.

# What a contradictory instance is (READ CAREFULLY — this is the whole point)
This models TWO developers who, unaware of each other, file SEPARATE tickets that
happen to touch the SAME code region in INCOMPATIBLE ways. It is **NOT** one task
cut into two halves.

- **Agent A is a REAL, standalone task = the original SWE-bench-Pro task**, kept
  essentially intact. Agent A's `problem_statement`, `solution`, and tests come
  from `source_row.json` (you may trim to a single coherent, self-contained unit
  if the original sprawls across unrelated files, but A must remain the genuine
  original ticket — do NOT invent A, do NOT shrink it to a fragment).
- **Agent B is a DIFFERENT, independently-motivated task that YOU design**: a
  separate feature or bugfix, with its OWN real-world motivation, that a *different*
  developer would plausibly file on its own — and which happens to edit the same
  code region as A in a way that cannot coexist with A's change.

Each is correct alone. Concatenating or git-merging A's and B's changes breaks
(one clobbers the other, or they conflict). A single hand-written
`reconciliation_patch` satisfies BOTH developers' intents at once.

# INDEPENDENCE REQUIREMENT (critical — the instance is worthless without it)
Read `agentA_problem_statement` and `agentB_problem_statement` as two tickets in an
issue tracker, filed by strangers who have never heard of each other. They MUST
read as two unrelated tasks with distinct motivations that only COINCIDENTALLY
collide on shared code.
- ❌ FAILS if the pair reads as "add the X side" + "add the Y side" of one obvious
  feature (e.g. min-bound + max-bound; new-var + legacy-var; produce X + consume X;
  rename + rewire; recognize device-A + recognize device-B). B must NEVER be
  describable as "the other half of A."
- ✅ PASSES if each ticket has its own distinct real-world reason to exist and a
  developer would file it independently, and the collision is an accident of both
  touching the same function/struct/lines.
A good B is often a *different kind* of change than A (e.g. A is a feature, B is a
bugfix or a refactor of the same code; A tightens a behavior, B loosens it).

# What to produce
Fill `seed_template.json` into a complete instance and write it to `./OUTPUT_seed.json`.
Author these fields (see SCHEMA.md for exact shapes):
- `mutex_type`, `diversity_mechanism`, `shared_artifact`, `natural_language_explanation`
- `agentA_problem_statement`, `agentA_solution` (diff), `agentA_test_patch` (diff), `agentA_fail_to_pass`, `agentA_pass_to_pass` — **derive these from the original task** in `source_row.json`.
- `agentB_problem_statement`, `agentB_solution` (diff), `agentB_test_patch` (diff), `agentB_fail_to_pass` — **your independently-motivated counterpart task**.
- `combined_test_patch` (diff = A's tests ∪ B's tests), `reconciliation_patch` (diff), `reconciliation_explanation`
- in `runtime`, set `selected_test_files_to_run` to the NEW test files you create; leave every other `runtime` value exactly as given.

# The truth table your artifacts MUST satisfy (this is how it is judged)
| Code applied | Tests | Expected |
|---|---|---|
| base | A's tests | FAIL |
| base | B's tests | FAIL |
| agentA_solution | A's tests | PASS |
| agentB_solution | B's tests | PASS |
| agentA_solution + agentB_solution (concat) | combined | FAIL |
| agentA_solution + agentB_solution (git merge) | combined | FAIL |
| reconciliation_patch | combined | PASS |

# Hard rules
1. Every diff must apply to `base_commit` with `git apply` — match real file paths and context lines from `repo/`.
2. Agent A must remain the ORIGINAL task (do not invent A). Agent B must be an independently-motivated, standalone task — NOT a complement, mirror, or "other half" of A. Honor the INDEPENDENCE REQUIREMENT above.
3. Solution/reconciliation patches touch SOURCE files only. Test patches touch TEST files only. No overlap.
4. `agentA_fail_to_pass` / `agentB_fail_to_pass` must fail at base and pass with their own solution.
5. Problem statements are BLIND: never mention the other agent, the other half, its files, or any test path.
6. The conflict must be real: concatenating A and B (or git-merging them) must break the combined tests, and only the reconciliation must pass them.

# Output discipline (critical)
- Write EXACTLY ONE file: `./OUTPUT_seed.json`. A single JSON object, valid, matching SCHEMA.md.
- Do NOT modify anything under `repo/`, do NOT create other files, do NOT edit the input files. Everything except `OUTPUT_seed.json` is read-only.
