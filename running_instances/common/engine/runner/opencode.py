"""Opencode backend: run `opencode run` against a vLLM OpenAI-compatible endpoint.

The vLLM provider is defined in a config file passed via OPENCODE_CONFIG, which the
runner rewrites from its arguments on construction. The `--format json` event
stream is the transcript.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import time

from ..types import TurnFailure, TurnResult, Usage
from ..workspace import Workspace

OPENCODE_BIN = os.path.expanduser("~/.opencode/bin/opencode")


class OpencodeRunner:
    def __init__(
        self,
        served_name: str,
        base_url: str,
        config_path: str,
        name: str,
        reasoning: str = "xhigh",
        timeout: int = 18000,
        api_key: str = "dummy",
        bin: str = OPENCODE_BIN,
    ) -> None:
        self.served_name = served_name
        self.base_url = base_url
        self.cfg = pathlib.Path(os.path.expanduser(config_path))
        self.name = name
        self.reasoning = reasoning
        self.timeout = timeout
        self.api_key = api_key
        self.bin = bin
        # A "worker" subagent on the same model and reasoning effort as the main agent.
        self.subagent_model = served_name
        self.cfg.parent.mkdir(parents=True, exist_ok=True)
        self.cfg.write_text(
            json.dumps(
                {
                    "$schema": "https://opencode.ai/config.json",
                    "provider": {
                        "vllm": {
                            "npm": "@ai-sdk/openai-compatible",
                            "options": {"baseURL": f"{base_url}/v1", "apiKey": api_key},
                            "models": {
                                served_name: {
                                    "name": served_name,
                                    "options": {"reasoningEffort": reasoning},
                                }
                            },
                        }
                    },
                    "model": f"vllm/{served_name}",
                    "agent": {
                        "worker": {
                            "description": (
                                "General implementation subagent. Delegate a "
                                "self-contained implementation task; it edits "
                                "files in the repo and reports back when done."
                            ),
                            "mode": "subagent",
                            "model": f"vllm/{served_name}",
                        },
                    },
                },
                indent=2,
            )
        )

    def _env(self, wd) -> dict:
        base = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("OPENCODE_", "OPENAI_"))
        }
        base["OPENCODE_CONFIG"] = str(self.cfg)
        base["PWD"] = str(wd)  # opencode takes the project dir from $PWD, not getcwd
        return base

    def run_turn(
        self,
        workspace: Workspace,
        agent: str,
        index: int,
        prompt: str,
        budget: int | None = None,
    ) -> TurnResult:
        cmd = [
            self.bin,
            "run",
            "--standalone",
            "--format",
            "json",
            "--auto",
            "-m",
            f"vllm/{self.served_name}",
            prompt,
        ]
        try:
            p = subprocess.run(
                cmd,
                cwd=workspace.path,
                env=self._env(workspace.path),
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise TurnFailure(
                f"opencode turn {index} timeout after {self.timeout}s"
            ) from e
        usage = self._usage(p.stdout)
        # The exit code is unreliable (often 1 after a clean run), so success is
        # judged from the event stream instead (see _completed).
        if not self._completed(p.stdout):
            dump = pathlib.Path(os.path.expanduser("~/.cache/opencode_failures"))
            dump.mkdir(parents=True, exist_ok=True)
            f = dump / f"{int(time.time())}_{agent}_{index}_{os.getpid()}.log"
            f.write_text(
                f"=== CMD ===\n{' '.join(cmd)}\n=== RC {p.returncode} ===\n"
                f"=== STDERR ===\n{p.stderr or ''}\n=== STDOUT ===\n{p.stdout or ''}",
                encoding="utf-8",
            )
            raise TurnFailure(
                f"opencode turn {index} did not complete (rc={p.returncode}, "
                f"stream truncated; stderr:{(p.stderr or '').strip()[:80]!r}; "
                f"full dump: {f})"
            )
        return TurnResult(
            index=index,
            agent=agent,
            prompt=prompt,
            transcript=p.stdout or p.stderr,
            diff=workspace.diff_base(),
            usage=usage,
        )

    @staticmethod
    def _completed(out: str) -> bool:
        """True if the last JSON event is the assistant's final `text` message."""
        last = None
        for line in (out or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("type"):
                last = ev["type"]
        return last == "text"

    @staticmethod
    def _usage(out: str) -> Usage:
        u = Usage()
        reasoning = 0
        for line in out.splitlines():
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("type") == "step_finish":
                tk = (ev.get("part") or {}).get("tokens") or {}
                u.input_tokens += tk.get("input", 0)
                u.output_tokens += tk.get("output", 0)
                reasoning += tk.get("reasoning", 0)
                c = tk.get("cache") or {}
                u.cache_read_tokens += c.get("read", 0)
                u.cache_creation_tokens += c.get("write", 0)
        if reasoning:
            u.by_model["reasoning"] = {"output_tokens": reasoning}
        return u
