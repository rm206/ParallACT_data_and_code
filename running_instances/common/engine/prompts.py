"""Assemble a turn's prompt from templates in prompts_running/.

A prompt is a task block, a coordination block (`coordination/<mode>.<family>.md`
if present, else `<mode>.md`), optional test-access text, and a handoff block on
follow-up turns. `{{TOKEN}}` markers are filled by plain string substitution.
"""

from __future__ import annotations

from pathlib import Path

from .types import ExecutionMode, ScenarioConfig, TestAccess, Visibility

_ROOT = Path(__file__).resolve().parent.parent / "prompts_running"


def _load(role: str, name: str) -> str:
    return (_ROOT / role / f"{name}.md").read_text(encoding="utf-8")


def _fill(text: str, tokens: dict[str, str]) -> str:
    for k, v in tokens.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def _load_coordination(scenario: ScenarioConfig, seed: dict) -> str:
    """The coordination block: a family-specific template wins over the generic."""
    mode = scenario.coordination.value
    specific = _ROOT / "coordination" / f"{mode}.{seed.get('family', '')}.md"
    if specific.is_file():
        return specific.read_text(encoding="utf-8")
    return _load("coordination", mode)


def build_prompt(
    scenario: ScenarioConfig,
    seed: dict,
    agent: str,
    is_followup: bool,
    subagent_model: str | None = None,
) -> str:
    if scenario.mode is ExecutionMode.ORCHESTRATOR:
        raw = _load("task", "orchestrator")
        if subagent_model:
            raw = _fill(raw, {"SUBAGENT_MODEL": subagent_model})
        else:
            # No subagent model known: drop the lines that mention it.
            raw = "\n".join(
                l for l in raw.splitlines() if "{{SUBAGENT_MODEL}}" not in l
            )
        task = _fill(
            raw,
            {
                "PROBLEM_A": seed["agentA_problem_statement"],
                "PROBLEM_B": seed["agentB_problem_statement"],
            },
        )
    elif agent == "AB":
        task = _fill(
            _load("task", "oracle"),
            {
                "PROBLEM_A": seed["agentA_problem_statement"],
                "PROBLEM_B": seed["agentB_problem_statement"],
            },
        )
    else:
        task = _fill(
            _load("task", "single"),
            {"PROBLEM": seed[f"agent{agent}_problem_statement"]},
        )

    parts = [task]

    peer = {"A": "B", "B": "A"}.get(agent, "")
    coord = _fill(
        _load_coordination(scenario, seed),
        {
            "SHARED_ARTIFACT": seed.get("shared_artifact", ""),
            "AGENT": agent,
            "PEER": peer,
            "PEER_PROBLEM": seed.get(f"agent{peer}_problem_statement", "")
            if peer
            else "",
        },
    )
    if coord.strip():
        parts.append(coord)

    if scenario.test_access is TestAccess.OWN:
        from . import testaccess

        _, ids = testaccess._test_set(seed, agent)
        listing = "\n".join(f"  {i}" for i in ids)
        parts.append(_fill(_load("testaccess", "own"), {"TEST_FILES": listing}))

    if is_followup:
        vis = (
            "with_history"
            if scenario.visibility is Visibility.WITH_HISTORY
            else "repo_only"
        )
        parts.append(_load("handoff", vis))

    return "\n\n".join(p.strip() for p in parts if p.strip()) + "\n"
