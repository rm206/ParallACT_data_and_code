You are evaluating one solved SWE-bench-Pro task. This task is **task A** — the
original, standalone ticket. Your job is to judge whether an *independent* task B
could pair with it into a contradictory or complementary seed (see your
instructions for the definitions and soundness bars).

Repository: {repo}  (language: {repo_language})
Instance: {instance_id}
Base commit (state BEFORE the fix): {base_commit}

A working copy of the repository at the base commit is checked out for you to
explore with the tools. All tool paths are relative to its root.

## Task A — problem statement (what this original task asked for)
{problem_statement}

## Task A — requirements (behavior the fix had to satisfy)
{requirements}

## Task A — interface (the symbol/API the fix centered on)
{interface}

## Task A — tests it made pass (fail_to_pass)
{fail_to_pass}

## Task A — gold patch (the official solution; source changes)
```diff
{patch}
```

## Task A — test patch (tests added/changed for this task)
```diff
{test_patch}
```

## Your task
Explore the real code at the base commit. Decide whether there is an
independently-motivated **task B** that pairs with task A as a contradictory
(mutex) seed and/or a complementary seed, following the definitions and soundness
bars in your instructions. Remember: task B must read as its own ticket a
different developer would file — never as "the other half" of task A. Prefer real
structure in the code over an invented split, and be calibrated, not optimistic.
When ready, call `finish` with the assessment object. Begin by exploring; do not
guess from the patch alone.
