"""Shared typed data for the run engine. No logic; nothing here imports siblings."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TurnFailure(RuntimeError):
    """A turn did not complete cleanly after retries.

    The scenario is aborted without writing a bundle, so it is rerun next time.
    """


class RateLimited(TurnFailure):
    """The backend hit a usage/rate limit; the caller stops the whole run."""


class ExecutionMode(str, Enum):
    ORACLE = "oracle"
    ORCHESTRATOR = (
        "orchestrator"  # one agent, both statements, must delegate to 2 subagents
    )
    SEQUENTIAL = "sequential"
    REENTRANT = "reentrant"
    PARALLEL = "parallel"


class Coordination(str, Enum):
    UNAWARE = "unaware"  # no mention of another agent
    AWARE = "aware"  # told another agent exists, nothing more
    MESSAGE = "message"  # aware + told to use the shared channel
    SYNC = "sync"  # aware + told to checkpoint at sync points
    COMM_ORACLE = "comm_oracle"  # message + given the partner's requirement


class Visibility(str, Enum):
    REPO_ONLY = "repo_only"  # next turn sees file state only
    WITH_HISTORY = "with_history"  # next turn also sees prior edit history


class ChannelKind(str, Enum):
    NONE = "none"
    FILE = "file"  # shared JSONL queue on disk (QueueChannel)
    REDIS = "redis"  # per-agent Redis list inboxes (RedisChannel)


class TestAccess(str, Enum):
    NONE = "none"  # blind
    OWN = "own"  # may read and run its own gold tests


# "A", "B", or "AB" (oracle, both halves fused).
AgentId = str


@dataclass(frozen=True)
class Turn:
    index: int
    agent: AgentId


@dataclass(frozen=True)
class Schedule:
    turns: list[Turn]
    concurrent: bool  # True only for parallel: turns run from base, kept separate


@dataclass(frozen=True)
class ScenarioConfig:
    name: str
    mode: ExecutionMode
    order: tuple[AgentId, ...]
    coordination: Coordination = Coordination.UNAWARE
    visibility: Visibility = Visibility.REPO_ONLY
    channel: ChannelKind = ChannelKind.NONE
    test_access: TestAccess = TestAccess.NONE
    # Families this scenario applies to ("contradictory", "complementary"); None = all.
    families: tuple[str, ...] | None = None


@dataclass
class Usage:
    """Backend-neutral usage/cost for one turn; runners subclass it for extras."""

    cost_usd: float | None = None
    cost_basis: str | None = None  # "list" | "computed" | "actual" | None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    num_turns: int | None = None
    duration_ms: int | None = None
    is_error: bool = False
    stop_reason: str | None = None
    by_model: dict[str, dict[str, float | int | None]] = field(default_factory=dict)


@dataclass
class TurnResult:
    index: int
    agent: AgentId
    prompt: str
    transcript: str
    diff: str  # patch produced this turn
    usage: Usage | None = None


@dataclass
class RunResult:
    scenario: str
    seed_id: str
    base_commit: str
    backend: str
    turns: list[TurnResult] = field(default_factory=list)
    outputs: dict[str, str] = field(
        default_factory=dict
    )  # label -> patch (applies to base)
    comm_log: str = ""
    started_at: str = ""
    finished_at: str = ""
