"""Claude Code backend: run `claude -p` in the workspace dir.

Usage comes from the `--output-format json` envelope. Tokens are summed from
`modelUsage`, since the top-level `usage` omits helper models.

A turn counts as failed on `is_error` (which can be set even when `subtype` is
"success"), a broken envelope, a non-zero exit or a timeout. Failures are retried
with backoff, then raise TurnFailure, or RateLimited for usage limits.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field

from ..types import RateLimited, TurnFailure, TurnResult, Usage
from ..workspace import Workspace

_RETRYABLE_STATUS = {"429", "500", "502", "503", "504", "529"}
# Substrings of the envelope `result` that indicate an account usage limit.
_LIMIT_MARKERS = (
    "session limit",
    "usage limit",
    "rate limit",
    "hit your limit",
    "quota",
    "resets ",
)

# Pinned so a run doesn't depend on the account's default model; --model overrides.
DEFAULT_CLAUDE_MODEL = "claude-opus-4-8[1m]"
DEFAULT_CLAUDE_EFFORT = "high"


@dataclass
class ClaudeCodeUsage(Usage):
    duration_api_ms: int | None = None
    service_tier: str | None = None
    subagent_stats: dict[str, object] = field(default_factory=dict)


def _envelope(stdout: str) -> dict | None:
    """The parsed `--output-format json` result object, or None if unparseable."""
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _is_rate_limited(env: dict | None) -> bool:
    """True if the failure is an account usage/session/rate limit."""
    if env is None:
        return False
    if str(env.get("api_error_status")) == "429":
        return True
    msg = env.get("result")
    return isinstance(msg, str) and any(m in msg.lower() for m in _LIMIT_MARKERS)


def _fail_reason(env: dict | None, proc: "subprocess.CompletedProcess") -> str:
    if env is not None:
        return str(env.get("result") or env.get("subtype") or "is_error")[:200]
    return (proc.stderr or f"exit {proc.returncode}, no json envelope")[:200]


def _parse_usage(stdout: str) -> ClaudeCodeUsage | None:
    return _usage_from_env(_envelope(stdout))


def _usage_from_env(data: dict | None) -> ClaudeCodeUsage | None:
    if data is None:
        return None
    models: dict = data.get("modelUsage") or {}
    top_usage: dict = data.get("usage") or {}
    return ClaudeCodeUsage(
        cost_usd=data.get("total_cost_usd"),
        cost_basis="list",
        input_tokens=sum(m.get("inputTokens", 0) for m in models.values()),
        output_tokens=sum(m.get("outputTokens", 0) for m in models.values()),
        cache_read_tokens=sum(
            m.get("cacheReadInputTokens", 0) for m in models.values()
        ),
        cache_creation_tokens=sum(
            m.get("cacheCreationInputTokens", 0) for m in models.values()
        ),
        num_turns=data.get("num_turns"),
        duration_ms=data.get("duration_ms"),
        is_error=bool(data.get("is_error", False)),
        stop_reason=data.get("stop_reason"),
        by_model={
            name: {
                "input_tokens": m.get("inputTokens", 0),
                "output_tokens": m.get("outputTokens", 0),
                "cache_read_tokens": m.get("cacheReadInputTokens", 0),
                "cache_creation_tokens": m.get("cacheCreationInputTokens", 0),
                "cost_usd": m.get("costUSD"),
            }
            for name, m in models.items()
        },
        duration_api_ms=data.get("duration_api_ms"),
        service_tier=top_usage.get("service_tier"),
        subagent_stats=data.get("subagent_stats") or {},
    )


class ClaudeCodeRunner:
    name = "claude-code"

    def __init__(
        self,
        model: str | None = None,
        timeout: int = 18000,
        bin: str = "claude",
        env: dict[str, str] | None = None,
        name: str | None = None,
        max_retries: int = 2,
        retry_base_delay: float = 20.0,
        retry_max_delay: float = 300.0,
        rate_limit_retries: int = 2,
        rate_limit_delay: float = 300.0,
        scrub: tuple[str, ...] = (),
        effort: str | None = None,
    ) -> None:
        self.model = model
        self.effort = effort
        self.timeout = timeout
        self.bin = bin
        # Drop inherited CLAUDE_CODE_* session vars so an agent launched from inside
        # a Claude Code session doesn't attach to the parent session. `scrub` lists
        # extra keys to drop for a given backend.
        base = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("CLAUDE_CODE_") and k not in scrub
        }
        self.env = {**base, **(env or {})}
        # Subagent model, substituted into the orchestrator prompt.
        self.subagent_model = self.env.get("CLAUDE_CODE_SUBAGENT_MODEL")
        if name:
            self.name = name
        # Transient failures use exponential backoff; usage limits use a fixed
        # delay and their own retry cap.
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.retry_max_delay = retry_max_delay
        self.rate_limit_retries = rate_limit_retries
        self.rate_limit_delay = rate_limit_delay

    @classmethod
    def _openrouter_backend(
        cls, slug: str, config_dir: str, name: str, **kw
    ) -> "ClaudeCodeRunner":
        """Claude Code on OpenRouter's Anthropic-compatible endpoint, running model `slug`.

        The model is chosen by the role env vars, so every role and the subagent are
        set to `slug`. A `[1m]` suffix tells Claude Code the context window is 1M.
        """
        key = os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError(
                f"{name} backend needs OPENROUTER_API_KEY in the environment"
            )
        env = {
            "CLAUDE_CONFIG_DIR": os.path.expanduser(config_dir),
            "ANTHROPIC_BASE_URL": "https://openrouter.ai/api",
            "ANTHROPIC_AUTH_TOKEN": key,
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": slug,
            "ANTHROPIC_DEFAULT_SONNET_MODEL": slug,
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": slug,
            "CLAUDE_CODE_SUBAGENT_MODEL": slug,
            # Sent as thinking.budget_tokens; must stay below the request max_tokens.
            "MAX_THINKING_TOKENS": "32000",
        }
        return cls(
            model=None, bin="claude", env=env, name=name, scrub=("CLAUDE_EFFORT",), **kw
        )

    @classmethod
    def for_vllm(
        cls,
        served_name: str,
        base_url: str,
        config_dir: str,
        name: str,
        effort: str = "xhigh",
        **kw,
    ) -> "ClaudeCodeRunner":
        """Claude Code pointed at a vLLM server's Anthropic endpoint (/v1/messages).

        vLLM rejects Claude Code's default effort "high", so `effort` is passed via
        --effort and CLAUDE_CODE_EFFORT_LEVEL; only the env var reaches subagents.
        """
        env = {
            "CLAUDE_CONFIG_DIR": os.path.expanduser(config_dir),
            "ANTHROPIC_BASE_URL": base_url,
            "ANTHROPIC_API_KEY": "dummy",
            "ANTHROPIC_AUTH_TOKEN": "dummy",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": served_name,
            "ANTHROPIC_DEFAULT_SONNET_MODEL": served_name,
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": served_name,
            "CLAUDE_CODE_SUBAGENT_MODEL": served_name,
            "CLAUDE_CODE_EFFORT_LEVEL": effort,  # pins subagents too (--effort can't)
            "CLAUDE_CODE_ATTRIBUTION_HEADER": "0",
        }
        return cls(
            model=served_name,
            bin="claude",
            env=env,
            name=name,
            effort=effort,
            scrub=("CLAUDE_EFFORT",),
            **kw,
        )

    @classmethod
    def for_backend(
        cls, backend: str | None, model: str | None = None, **kw
    ) -> "ClaudeCodeRunner":
        """Resolve a --backend value to a configured runner.

        `claude`          -> `claude` on PATH, DEFAULT_CLAUDE_MODEL + DEFAULT_CLAUDE_EFFORT.
        `claude-deepseek` -> deepseek-v4-flash via OpenRouter (OPENROUTER_API_KEY).
        `claude-glm`      -> glm-5.3-flash via OpenRouter (OPENROUTER_API_KEY).
        anything else     -> a literal binary/path.
        """
        b = backend or "claude"
        env: dict[str, str] = {}
        if b == "claude-deepseek":
            return cls._openrouter_backend(
                "deepseek/deepseek-v4-flash-0731[1m]",
                "~/.claude-deepseek",
                "claude-code-deepseek",
                **kw,
            )
        if b == "claude-glm":
            return cls._openrouter_backend(
                "z-ai/glm-5.3-flash[1m]", "~/.claude-glm", "claude-code-glm", **kw
            )
        if b == "claude":
            m = model or DEFAULT_CLAUDE_MODEL
            env["CLAUDE_EFFORT"] = DEFAULT_CLAUDE_EFFORT
            env["CLAUDE_CODE_SUBAGENT_MODEL"] = m
            return cls(model=m, bin="claude", env=env, name="claude-code", **kw)
        return cls(model=model, bin=b, name=f"claude-code:{b}", **kw)

    def run_turn(
        self,
        workspace: Workspace,
        agent: str,
        index: int,
        prompt: str,
        budget: int | None = None,
    ) -> TurnResult:
        """Run one turn with retries; raise TurnFailure/RateLimited if it never completes cleanly."""
        cmd = [
            self.bin,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--permission-mode",
            "bypassPermissions",
        ]
        if self.model:
            cmd += ["--model", self.model]
        if self.effort:
            cmd += ["--effort", self.effort]
        tag = f"turn {index} ({agent})"

        attempt = 0
        while True:
            attempt += 1
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=workspace.path,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    env=self.env,
                )
            except subprocess.TimeoutExpired:
                self._backoff_or_raise(
                    attempt, tag, rate=False, reason=f"timeout after {self.timeout}s"
                )
                continue

            env = _envelope(proc.stdout)
            usage = _usage_from_env(env)
            clean = proc.returncode == 0 and env is not None and not env.get("is_error")
            if clean:
                # The envelope is only a summary; append the session JSONL from the
                # config dir's projects store for the full transcript.
                transcript = proc.stdout or proc.stderr
                sid = (env or {}).get("session_id")
                cfg = self.env.get("CLAUDE_CONFIG_DIR")
                if sid and cfg:
                    import glob as _glob

                    hits = _glob.glob(
                        os.path.join(cfg, "projects", "*", f"{sid}.jsonl")
                    )
                    if hits:
                        try:
                            transcript += (
                                "\n\n===SESSION_JSONL===\n"
                                + open(hits[0], encoding="utf-8").read()
                            )
                        except OSError:
                            pass
                return TurnResult(
                    index=index,
                    agent=agent,
                    prompt=prompt,
                    transcript=transcript,
                    diff=workspace.diff_base(),
                    usage=usage,
                )

            rate = _is_rate_limited(env)
            self._backoff_or_raise(
                attempt, tag, rate=rate, reason=_fail_reason(env, proc)
            )

    def _backoff_or_raise(
        self, attempt: int, tag: str, rate: bool, reason: str
    ) -> None:
        """Sleep before the next attempt, or raise RateLimited/TurnFailure once
        `attempt` (tries so far) exceeds the retry cap."""
        limit = self.rate_limit_retries if rate else self.max_retries
        kind = "RATE-LIMITED" if rate else "error"
        if attempt > limit:
            exc = RateLimited if rate else TurnFailure
            raise exc(f"{tag} {kind}: gave up after {attempt} attempt(s): {reason}")
        if rate:
            delay = self.rate_limit_delay
        else:
            delay = min(
                self.retry_max_delay, self.retry_base_delay * (2 ** (attempt - 1))
            )
        print(
            f"[{self.name}] {tag} {kind}; retry {attempt}/{limit} "
            f"in {delay:.0f}s: {reason}",
            flush=True,
        )
        time.sleep(delay)
