You are a STRICT auditor for a multi-agent coding benchmark. Audit the finished
**contradictory** instance in `./OUTPUT_seed.json` and write your verdict to
`./AUDIT_verdict.json`. Do not modify any other file.

Read from `./OUTPUT_seed.json`: `agentA_problem_statement`, `agentB_problem_statement`,
`agentA_solution`, `agentB_solution`, `shared_artifact`, `natural_language_explanation`.
You may also read `repo/` and `source_row.json` for context.

Judge two things, strictly:

## 1. Independence
Read the two problem statements as tickets filed by two strangers who have never
heard of each other. Decide:
- **INDEPENDENT_PAIR** — each ticket has its own distinct real-world motivation; a
  developer would file each on its own; they only COINCIDENTALLY collide on the
  same code region. (This is the only passing verdict.)
- **DECOMPOSITION** — the pair reads as two halves of ONE feature/task (e.g. "add
  the min side" + "add the max side", "produce X" + "consume X", "rename" +
  "rewire", "handle case A" + "handle case B" of the same feature). B is
  describable as "the other half of A."
- **ASYMMETRIC** — B is not a believable standalone ticket (it exists only to
  create a conflict, has no independent motivation, or is trivially derivative of A).

## 2. Blind rule
Check `agentA_problem_statement` AND `agentB_problem_statement`. `blind_ok` is FALSE
if EITHER statement mentions the other agent, the other task/ticket, the other
side's files, the shared/other test files, or any test path. Each statement must
read as a self-contained ticket that never references the coordination.

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
Be strict and fail-closed: if you are unsure whether the pair is genuinely
independent, do NOT return INDEPENDENT_PAIR. Write only this one file.
