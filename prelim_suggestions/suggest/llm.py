"""Stdlib-only chat client for a vLLM OpenAI-compatible server.

The server is expected to run with --enable-auto-tool-choice
--tool-call-parser qwen3_xml --reasoning-parser qwen3, so replies carry native
`tool_calls` and a separate `reasoning_content`.

Env: VLLM_BASE_URL (default http://localhost:8000/v1), VLLM_MODEL (default
Qwen/Qwen3.8-27B-FP8), VLLM_API_KEY (default "EMPTY"; ignored unless the server
sets --api-key), VLLM_TEMPERATURE, VLLM_TOP_P, VLLM_MAX_TOKENS, VLLM_TIMEOUT.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "http://localhost:8000/v1"
DEFAULT_MODEL = "Qwen/Qwen3.8-27B-FP8"


class Client:
    """Minimal chat client for one vLLM-served model, with tool-calling."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str = "EMPTY",
        model: str = DEFAULT_MODEL,
        max_retries: int = 5,
        timeout: int = 600,
        temperature: float = 0.6,
        top_p: float = 0.95,
        max_tokens: int = 8192,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or "EMPTY"
        self.model = model
        self.max_retries = max_retries
        self.timeout = timeout
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice=None,
        max_tokens: int | None = None,
    ) -> dict:
        """Run one chat completion and return the assistant message dict.

        Retries transport errors, bad bodies and 429/5xx with exponential backoff."""
        url = f"{self.base_url}/chat/completions"
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": max_tokens or self.max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                req = urllib.request.Request(
                    url, data=body, headers=headers, method="POST"
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8", "replace"))
                return data["choices"][0]["message"]
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                last_err = RuntimeError(f"bad response body: {str(e)[:150]}")
                time.sleep(min(2**attempt, 20))
            except urllib.error.HTTPError as e:
                try:
                    detail = e.read().decode("utf-8", "replace")[:600]
                except Exception:
                    detail = ""
                last_err = RuntimeError(f"HTTP {e.code}: {detail}")
                if e.code in (429, 500, 502, 503, 504):
                    time.sleep(min(2**attempt, 20))
                    continue
                raise last_err from None
            except (urllib.error.URLError, TimeoutError) as e:
                last_err = e
                time.sleep(min(2**attempt, 20))
        raise RuntimeError(f"chat failed after {self.max_retries} retries: {last_err}")


def from_env() -> Client:
    return Client(
        base_url=os.environ.get("VLLM_BASE_URL", DEFAULT_BASE_URL),
        api_key=os.environ.get("VLLM_API_KEY", "EMPTY"),
        model=os.environ.get("VLLM_MODEL", DEFAULT_MODEL),
        temperature=float(os.environ.get("VLLM_TEMPERATURE", "0.6")),
        top_p=float(os.environ.get("VLLM_TOP_P", "0.95")),
        max_tokens=int(os.environ.get("VLLM_MAX_TOKENS", "8192")),
        timeout=int(os.environ.get("VLLM_TIMEOUT", "600")),
    )
