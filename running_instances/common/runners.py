"""Factory: (harness, model_key) -> a Runner pointed at that model's vLLM endpoint.

Each runner gets its own per-model config (claude ~/.claude-<key>, opencode
opencode_configs/<key>.json; codex uses a fresh home per turn) so concurrent runs
of different models don't collide.
"""

from __future__ import annotations

import pathlib

from endpoints import get
from engine.runner.claude_code import ClaudeCodeRunner
from engine.runner.codex import CodexRunner
from engine.runner.opencode import OpencodeRunner

HARNESSES = ("claude", "codex", "opencode")
_HERE = pathlib.Path(__file__).resolve().parent


def harness_model_label(harness: str, model_key: str) -> str:
    """Output-namespace segment, e.g. claude__qwen3-flash-next."""
    return f"{harness}__{get(model_key).served_name}"


def make_runner(harness: str, model_key: str, timeout: int = 3600):
    ep = get(model_key)
    if harness == "claude":
        return ClaudeCodeRunner.for_vllm(
            served_name=ep.served_name,
            base_url=ep.base_url,
            config_dir=f"~/.claude-{ep.key}",
            name=f"claude__{ep.key}",
            effort=ep.reasoning_effort,
            timeout=timeout,
        )
    if harness == "codex":
        return CodexRunner(
            ep.served_name,
            ep.base_url,
            config_home=f"~/.codex-{ep.key}-run",
            name=f"codex__{ep.key}",
            reasoning=ep.reasoning_effort,
            timeout=timeout,
        )
    if harness == "opencode":
        return OpencodeRunner(
            ep.served_name,
            ep.base_url,
            config_path=str(_HERE / "opencode_configs" / f"{ep.key}.json"),
            name=f"opencode__{ep.key}",
            reasoning=ep.reasoning_effort,
            timeout=timeout,
        )
    raise SystemExit(f"unknown harness {harness!r}; use one of {HARNESSES}")
