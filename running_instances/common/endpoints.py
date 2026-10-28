"""Model endpoint table.

Each model is served by vLLM (see serve_model_scripts/) at 127.0.0.1:8000 by default.
MODEL_HOST points at another machine; MODEL_PORT_<KEY> gives a model its own port so
several can run concurrently. vLLM serves both OpenAI /v1 (codex, opencode) and
Anthropic /v1/messages (claude) on the same port.
"""

from __future__ import annotations
import os
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Endpoint:
    key: str  # short model key; also the per-model profile suffix
    served_name: str  # vLLM --served-model-name (slash-free)
    port: int
    # vLLM's qwen endpoint rejects "high"; its levels are low < medium < xhigh.
    reasoning_effort: str = "xhigh"
    thinking_tokens: int = 16000  # not passed by runners.py
    host: str = "127.0.0.1"

    @property
    def base_url(self) -> str:  # claude ANTHROPIC_BASE_URL; codex/opencode add /v1
        return f"http://{self.host}:{self.port}"

    @property
    def openai_base(self) -> str:  # not used by runners.py
        return f"http://{self.host}:{self.port}/v1"


ENDPOINTS = {
    "qwen": Endpoint("qwen", "qwen3-flash-next", 8000),
    "deepseek": Endpoint("deepseek", "deepseek-v4-flash", 8000),
    "glm": Endpoint("glm", "glm-5.3-flash", 8000),
}


def get(key: str) -> Endpoint:
    """The endpoint for a model key. MODEL_HOST overrides the host for every model;
    MODEL_PORT_<KEY> (e.g. MODEL_PORT_GLM=8001) overrides one model's port."""
    try:
        ep = ENDPOINTS[key]
    except KeyError:
        raise SystemExit(f"unknown model key {key!r}; known: {', '.join(ENDPOINTS)}")
    return replace(
        ep,
        host=os.environ.get("MODEL_HOST", ep.host),
        port=int(os.environ.get(f"MODEL_PORT_{key.upper()}", ep.port)),
    )
