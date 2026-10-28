# Seed format (authoritative)

A **seed** is one SWE-bench-Pro task deliberately split into two halves (Agent A,
Agent B) on a single repo at a single `base_commit`. There are two families:
**complementary** and **contradictory**. This document is the exact JSON shape a
finished seed must have. Match it field-for-field.

A seed is a single flat JSON object. All patch fields are unified `git diff` text
that applies cleanly to `base_commit` with `git apply`.

## Shared fields (both families)

| Field | Type | Meaning |
|---|---|---|
| `instance_id` | str | Provided in the template. Do not change. |
| `repo` | str | `owner/name`. Provided. Do not change. |
| `base_commit` | str | The commit every patch applies to. Provided. Do not change. |
| `family` | str | `"complementary"` or `"contradictory"`. Provided. Do not change. |
| `mutex_type` | str | Short tag for the coupling (e.g. `interference`, `codec_pair`). You set this. |
| `diversity_mechanism` | str | Short tag for what makes this seed distinct (e.g. `signature_collision_existing_fn`). You set this. |
| `shared_artifact` | str | One line naming the exact file + function/region both halves touch or agree on. |
| `natural_language_explanation` | str | 2–4 sentences: why this is a valid seed of its family. |
| `runtime` | obj | Provided in the template. Fill ONLY `selected_test_files_to_run` (see below). Leave the image/`run_script`/`parser`/`before_repo_set_cmd` sentinels untouched. |
| `agentA_problem_statement` | str | The task given to Agent A. Self-contained. Must NOT mention Agent B, "another agent", the other half's files, or any test file path. |
| `agentA_solution` | str (diff) | Gold solution for A's half. Applies to base. Touches only source files, never test files. |
| `agentA_test_patch` | str (diff) | The hidden tests for A's half. Applies to base. Touches only test files. |
| `agentA_fail_to_pass` | list[str] | pytest/jest node IDs that FAIL at base and PASS once `agentA_solution` is applied. |
| `agentA_pass_to_pass` | list[str] | (optional) existing tests that stay green. May be `[]`. |
| `agentB_problem_statement` | str | The task given to Agent B. Same rules as A's. |
| `agentB_solution` | str (diff) | Gold solution for B's half. Applies to base. Source files only. |
| `agentB_test_patch` | str (diff) | Hidden tests for B's half. Applies to base. Test files only. |
| `agentB_fail_to_pass` | list[str] | Node IDs that FAIL at base and PASS once `agentB_solution` is applied. |

`selected_test_files_to_run`: set it to the list of NEW test-file paths your
`*_test_patch` (and the integration/combined patch) create or modify — the paths
before `::` / ` | ` in your fail_to_pass ids.

## Complementary — extra fields

The two halves compose. Neither half alone satisfies the payoff; only A+B does.

| Field | Type | Meaning |
|---|---|---|
| `integration_test_patch` | str (diff) | One end-to-end test that exercises A's half THROUGH B's half (or vice-versa). Test files only. |
| `integration_fail_to_pass` | list[str] | Node IDs of that integration test. |

**Truth table the verifier will enforce (must hold exactly):**

| Code applied | Tests run | Expected |
|---|---|---|
| `agentA_solution` only | integration | **FAIL** |
| `agentB_solution` only | integration | **FAIL** |
| `agentA_solution` + `agentB_solution` | integration | **PASS** |

## Contradictory — extra fields

The two halves edit the same code in incompatible ways. Each is correct alone; a
mechanical merge breaks. A hand-written reconciliation satisfies both.

| Field | Type | Meaning |
|---|---|---|
| `combined_test_patch` | str (diff) | A's tests AND B's tests together in one patch (union). Test files only. |
| `reconciliation_patch` | str (diff) | The single coherent source change that satisfies both halves. Applies to base. Source files only. |
| `reconciliation_explanation` | str | 1–3 sentences on how the reconciliation resolves the conflict. |

**Truth table the verifier will enforce (must hold exactly):**

| Code applied | Tests run | Expected |
|---|---|---|
| base (unchanged) | A's tests | **FAIL** |
| base (unchanged) | B's tests | **FAIL** |
| `agentA_solution` | A's tests | **PASS** |
| `agentB_solution` | B's tests | **PASS** |
| `agentA_solution` + `agentB_solution` (concatenated) | combined | **FAIL** |
| `agentA_solution` + `agentB_solution` (git merge of two branches off base) | combined | **FAIL** (break or conflict) |
| `reconciliation_patch` | combined | **PASS** |

## Hard rules (both families)

1. Every diff applies to `base_commit` with `git apply` — verify paths and context lines against the real repo you were given.
2. Solution patches touch **source** files only. Test patches touch **test** files only. They must not overlap.
3. `*_fail_to_pass` tests must genuinely FAIL at base (the feature is absent) and PASS with the matching solution.
4. Problem statements are blind: no reference to the other agent, the other half's files, or any test path.
5. Output the seed as ONE JSON object matching this schema. Write nothing else.
