"""The scenario registry and `expand()`, which turns a config into a schedule of turns.

Nineteen scenarios: oracle, orchestrator, 4 sequential, 4 reentrant, 4 parallel,
2 Redis-transport parallel variants, a communication oracle, and 2 gold-test-access
variants.
"""

from __future__ import annotations

from .types import (
    ChannelKind,
    Coordination,
    ExecutionMode,
    Schedule,
    ScenarioConfig,
    TestAccess,
    Turn,
    Visibility,
)


def _seq(order: tuple[str, str], vis: Visibility) -> ScenarioConfig:
    a, b = order
    tag = "hist" if vis is Visibility.WITH_HISTORY else "repo"
    return ScenarioConfig(
        name=f"sequential_{a}{b}_{tag}",
        mode=ExecutionMode.SEQUENTIAL,
        order=order,
        visibility=vis,
    )


def _reentrant(order: tuple[str, ...], vis: Visibility) -> ScenarioConfig:
    tag = "hist" if vis is Visibility.WITH_HISTORY else "repo"
    return ScenarioConfig(
        name=f"reentrant_{''.join(order)}_{tag}",
        mode=ExecutionMode.REENTRANT,
        order=order,
        visibility=vis,
    )


def _parallel(
    coord: Coordination, channel: ChannelKind | None = None
) -> ScenarioConfig:
    # Coordinating modes default to the file queue. An explicit `channel` is
    # appended to the name (e.g. parallel_message_redis).
    if channel is None:
        channel = (
            ChannelKind.FILE
            if coord
            in (
                Coordination.MESSAGE,
                Coordination.SYNC,
                Coordination.COMM_ORACLE,
            )
            else ChannelKind.NONE
        )
        suffix = ""
    else:
        suffix = f"_{channel.value}"
    return ScenarioConfig(
        name=f"parallel_{coord.value}{suffix}",
        mode=ExecutionMode.PARALLEL,
        order=("A", "B"),
        coordination=coord,
        channel=channel,
    )


_ALL: list[ScenarioConfig] = [
    ScenarioConfig(name="oracle", mode=ExecutionMode.ORACLE, order=("AB",)),
    # Like oracle, but the agent must delegate each requirement to one of two
    # subagents and do no implementation itself.
    ScenarioConfig(name="orchestrator", mode=ExecutionMode.ORCHESTRATOR, order=("AB",)),
    _seq(("A", "B"), Visibility.REPO_ONLY),
    _seq(("A", "B"), Visibility.WITH_HISTORY),
    _seq(("B", "A"), Visibility.REPO_ONLY),
    _seq(("B", "A"), Visibility.WITH_HISTORY),
    _reentrant(("A", "B", "A", "B"), Visibility.REPO_ONLY),
    _reentrant(("A", "B", "A", "B"), Visibility.WITH_HISTORY),
    _reentrant(("B", "A", "B", "A"), Visibility.REPO_ONLY),
    _reentrant(("B", "A", "B", "A"), Visibility.WITH_HISTORY),
    _parallel(Coordination.UNAWARE),
    _parallel(Coordination.AWARE),
    _parallel(Coordination.MESSAGE),
    _parallel(Coordination.SYNC),
    # Same send-msg/recv-msg surface over per-agent Redis inboxes (drained on
    # read). Needs a reachable Redis and the redis package.
    _parallel(Coordination.MESSAGE, ChannelKind.REDIS),
    _parallel(Coordination.SYNC, ChannelKind.REDIS),
    # parallel_message where each agent is also given the partner's requirement
    # and told to communicate to jointly solve both.
    _parallel(Coordination.COMM_ORACLE),
    # Each agent can read its gold tests and run them with ./run-tests (see
    # testaccess.py): the oracle gets the full test set, each parallel agent its
    # own half. The parallel variant is contradictory-only, since complementary's
    # per-half tests are producer/consumer.
    ScenarioConfig(
        name="oracle_with_gold_tests",
        mode=ExecutionMode.ORACLE,
        order=("AB",),
        test_access=TestAccess.OWN,
    ),
    ScenarioConfig(
        name="parallel_oracle_with_gold_tests",
        mode=ExecutionMode.PARALLEL,
        order=("A", "B"),
        coordination=Coordination.UNAWARE,
        channel=ChannelKind.NONE,
        test_access=TestAccess.OWN,
        families=("contradictory",),
    ),
]

REGISTRY: dict[str, ScenarioConfig] = {s.name: s for s in _ALL}


def expand(scenario: ScenarioConfig) -> Schedule:
    turns = [Turn(index=i, agent=a) for i, a in enumerate(scenario.order)]
    concurrent = scenario.mode is ExecutionMode.PARALLEL
    return Schedule(turns=turns, concurrent=concurrent)
