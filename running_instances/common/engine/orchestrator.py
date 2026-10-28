"""Execute one scenario against one seed and return a RunResult.

Parallel scenarios run each turn concurrently in its own workspace and keep the
outputs separate. Other modes share one workspace and emit one final patch.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import prompts, scenarios, testaccess
from .channel import Channel, NullChannel, QueueChannel, RedisChannel
from .runner import Runner
from .types import ChannelKind, RunResult, ScenarioConfig, TurnResult
from .workspace import RepoSource, Workspace


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_channel(kind: ChannelKind, agents: tuple[str, ...]) -> Channel:
    if kind is ChannelKind.FILE:
        return QueueChannel()
    if kind is ChannelKind.REDIS:
        return RedisChannel(agents=agents)
    return NullChannel()


def run_scenario(
    seed: dict,
    scenario: ScenarioConfig,
    runner: Runner,
    work_root: Path,
    run_dir: Path,
    source: RepoSource | None = None,
) -> RunResult:
    schedule = scenarios.expand(scenario)
    result = RunResult(
        scenario=scenario.name,
        seed_id=seed["instance_id"],
        base_commit=seed["base_commit"],
        backend=runner.name,
        started_at=_now(),
    )
    agents = tuple(dict.fromkeys(a for a in scenario.order if a != "AB"))
    channel = _make_channel(scenario.channel, agents=agents or ("A", "B"))
    channel.prepare(run_dir)
    tests = testaccess.make(seed, scenario.test_access, run_dir)

    try:
        if schedule.concurrent:
            _run_parallel(
                seed,
                scenario,
                runner,
                schedule,
                work_root,
                channel,
                tests,
                result,
                source,
            )
        else:
            _run_serial(
                seed,
                scenario,
                runner,
                schedule,
                work_root,
                channel,
                tests,
                result,
                source,
            )
    finally:
        tests.cleanup()

    result.comm_log = channel.read_log()
    result.finished_at = _now()
    return result


def _run_parallel(
    seed, scenario, runner, schedule, work_root, channel, tests, result, source=None
) -> None:
    spaces: dict[str, Workspace] = {}
    for turn in schedule.turns:
        ws = Workspace.create(seed, work_root, source)
        channel.attach(ws, turn.agent)
        tests.attach(ws, turn.agent)
        spaces[turn.agent] = ws

    def _one(turn) -> TurnResult:
        prompt = prompts.build_prompt(
            scenario,
            seed,
            turn.agent,
            is_followup=False,
            subagent_model=getattr(runner, "subagent_model", None),
        )
        return runner.run_turn(spaces[turn.agent], turn.agent, turn.index, prompt)

    try:
        with ThreadPoolExecutor(max_workers=len(schedule.turns)) as pool:
            turn_results = list(pool.map(_one, schedule.turns))
        for tr in turn_results:
            result.turns.append(tr)
            result.outputs[tr.agent] = tr.diff
    finally:
        for ws in spaces.values():
            ws.cleanup()


def _run_serial(
    seed, scenario, runner, schedule, work_root, channel, tests, result, source=None
) -> None:
    ws = Workspace.create(seed, work_root, source)
    channel.attach(ws, scenario.order[0])
    tests.attach(ws, scenario.order[0])
    try:
        for turn in schedule.turns:
            prompt = prompts.build_prompt(
                scenario,
                seed,
                turn.agent,
                is_followup=turn.index > 0,
                subagent_model=getattr(runner, "subagent_model", None),
            )
            tr = runner.run_turn(ws, turn.agent, turn.index, prompt)
            result.turns.append(tr)
            ws.snapshot(f"turn {turn.index} ({turn.agent})")
            ws.apply_history_visibility(scenario.visibility)
        result.outputs["final"] = ws.diff_base()
    finally:
        ws.cleanup()
