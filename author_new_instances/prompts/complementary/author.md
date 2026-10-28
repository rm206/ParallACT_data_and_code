You are authoring ONE **complementary** dataset instance for a multi-agent coding
benchmark. Do your best-effort work and produce a single JSON file. Work only from
the real code in front of you.

# Where you are
Your working directory contains everything you need:
- `repo/` — the actual codebase, checked out at the instance's `base_commit`. READ IT to ground every diff.
- `source_row.json` — the original SWE-bench-Pro task this instance is derived from: `patch` (the gold single-task solution), `test_patch`, `problem_statement`, `interface`, `fail_to_pass`. **Agent A IS this task** (see below).
- `SUGGESTION.json` — a LOW-AUTHORITY hint from a small scout model proposing a possible agent-B task and the shared interface A and B would have to agree on. Treat it ONLY as a starting idea: verify it against the real code, and freely improve or replace it. It is NOT authoritative and may be wrong. Agent A is fixed (the original task); the scout's job was only to point at a plausible B and interface.
- `EXAMPLES.md` — two finished, verified complementary instances closest to this repo/language. Imitate their SHAPE, harness/test-id conventions, and how the two problem statements read as independent tickets. Do NOT copy their content.
- `seed_template.json` — a partial instance with `instance_id`, `repo`, `base_commit`, `family`, and `runtime` pre-filled. START FROM THIS.
- `SCHEMA.md` — the authoritative format. Obey it exactly.

# What a complementary instance is (READ CAREFULLY — this is the whole point)
This models TWO developers who, unaware of each other, file SEPARATE tickets that
turn out to require AGREEMENT on a shared interface to interoperate correctly. It
is **NOT** one feature split into a producer and a throwaway consumer.

- **Agent A is a REAL, standalone, INDEPENDENTLY-USEFUL task = the original
  SWE-bench-Pro task**, kept essentially intact. It would be filed and merged on
  its own merits even if agent B never existed. Agent A's `problem_statement`,
  `solution`, and tests come from `source_row.json` (trim to a coherent
  self-contained unit only if the original sprawls; never reduce A to a fragment
  that exists only to serve B).
- **Agent B is a DIFFERENT, independently-motivated task that YOU design**: a
  separate feature or bugfix with its OWN real-world motivation that a *different*
  developer would file on its own — and which happens to DEPEND ON / must AGREE
  WITH A across a shared interface (a config key, a data shape, an API contract, a
  format) to work end-to-end.

Each half is individually useful and independently mergeable. But the correct
END-TO-END behavior only appears when BOTH are present AND they agree on the
shared contract.

# INDEPENDENCE REQUIREMENT (critical — the instance is worthless without it)
- **A must have value beyond serving B.** A is the original real task with its own
  motivation and its own passing unit tests. If A's only purpose is to be consumed
  by B (a helper/field/method/API with no reason to exist except B), it FAILS.
- Read `agentA_problem_statement` and `agentB_problem_statement` as two tickets
  filed by strangers. They MUST read as two independently-motivated tasks that
  merely MEET at an interface.
  - ❌ FAILS if it reads as "produce X" + "consume X" of one feature, where one
    side is pointless alone (e.g. add an unused field/marker/method + wire the one
    call site that uses it).
  - ✅ PASSES if A is a genuinely useful capability or fix in its own right, B is a
    separately-motivated feature, and they simply must agree on a contract to
    interoperate (see EXAMPLES.md).

# What to produce
Fill `seed_template.json` into a complete instance and write it to `./OUTPUT_seed.json`.
Author these fields (see SCHEMA.md for exact shapes):
- `mutex_type`, `diversity_mechanism`, `shared_artifact`, `natural_language_explanation`
- `agentA_problem_statement`, `agentA_solution` (diff), `agentA_test_patch` (diff), `agentA_fail_to_pass`, `agentA_pass_to_pass` — **derive these from the original task** in `source_row.json`.
- `agentB_problem_statement`, `agentB_solution` (diff), `agentB_test_patch` (diff), `agentB_fail_to_pass` — **your independently-motivated counterpart task**.
- `integration_test_patch` (diff = ONE end-to-end test exercising the interoperation of A and B across the shared interface), `integration_fail_to_pass`
- in `runtime`, set `selected_test_files_to_run` to the NEW test files you create; leave every other `runtime` value exactly as given.

# The truth table your artifacts MUST satisfy (this is how it is judged)
| Code applied | Tests | Expected |
|---|---|---|
| agentA_solution only | integration test | FAIL |
| agentB_solution only | integration test | FAIL |
| agentA_solution + agentB_solution | integration test | PASS |

The A-only and B-only failures come from the two features not interoperating until
BOTH are present and agree on the contract — NOT from A being a pointless stub.
Each half ALSO has its own unit tests (`agentA_fail_to_pass` / `agentB_fail_to_pass`)
that pass with its own solution, proving each is independently useful.

# Hard rules
1. Every diff must apply to `base_commit` with `git apply` — match real file paths and context lines from `repo/`.
2. Agent A must remain the ORIGINAL task and be independently useful. Agent B must be an independently-motivated, standalone task — NOT a consumer invented solely to call A. Honor the INDEPENDENCE REQUIREMENT above.
3. Solution patches touch SOURCE files only. Test patches touch TEST files only. No overlap.
4. `agentA_fail_to_pass` / `agentB_fail_to_pass` must fail at base and pass with their own solution (each half's OWN unit tests).
5. Problem statements are BLIND: never mention the other agent, the other half, its files, or any test path. Do NOT over-specify the shared interface — leave the coordination genuinely necessary.
6. The interdependence must be real: the integration test must FAIL with A alone and FAIL with B alone, and PASS only with both.

# Output discipline (critical)
- Write EXACTLY ONE file: `./OUTPUT_seed.json`. A single JSON object, valid, matching SCHEMA.md.
- Do NOT modify anything under `repo/`, do NOT create other files, do NOT edit the input files. Everything except `OUTPUT_seed.json` is read-only.
