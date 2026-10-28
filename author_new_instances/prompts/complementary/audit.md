You are a STRICT auditor for a multi-agent coding benchmark. Audit the finished
**complementary** instance in `./OUTPUT_seed.json` and write your verdict to
`./AUDIT_verdict.json`. Do not modify any other file.

Read from `./OUTPUT_seed.json`: `agentA_problem_statement`, `agentB_problem_statement`,
`agentA_solution`, `agentB_solution`, `shared_artifact`, `natural_language_explanation`,
`integration_test_patch`. You may also read `repo/` and `source_row.json` for context.

Judge two things, strictly:

## 1. Independence
Read the two problem statements as tickets filed by two strangers, and check the
complementary-specific bar: **A must have value on its own, beyond serving B.**
- **INDEPENDENT_PAIR** — A is a genuinely useful capability or fix in its own right
  (independently mergeable, with its own motivation and unit tests); B is a
  separately-motivated feature; they simply must AGREE on a shared interface to
  interoperate. (This is the only passing verdict.)
- **DECOMPOSITION** — it reads as "produce X" + "consume X" of one feature: one
  side is pointless alone (e.g. an unused field/marker/method added by A, and B is
  the single call site that uses it), or A exists only to serve B.
- **ASYMMETRIC** — B is not a believable standalone ticket, or the coordination is
  over-specified so no real agreement is needed, or A is a stub with no independent
  value.

## 2. Blind rule
Check `agentA_problem_statement` AND `agentB_problem_statement`. `blind_ok` is FALSE
if EITHER statement mentions the other agent, the other task/ticket, the other
side's files, the shared/other test files, or any test path — or if it
over-specifies the shared interface so tightly that no genuine coordination
remains. Each statement must read as a self-contained ticket.

## Output
Write EXACTLY `./AUDIT_verdict.json`, a single JSON object:
```json
{
  "independence_verdict": "INDEPENDENT_PAIR | DECOMPOSITION | ASYMMETRIC",
  "blind_ok": true,
  "issues": ["short bullet for each problem found, or empty"],
  "rationale": "2-3 sentences justifying the verdict"
}
```
Be strict and fail-closed: if you are unsure whether A has independent value or the
pair is genuinely independent, do NOT return INDEPENDENT_PAIR. Write only this one file.
