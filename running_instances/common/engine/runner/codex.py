"""Codex backend: run `codex exec` against a vLLM Responses API endpoint (/v1/responses).

The `--json` event stream is the transcript. A non-zero exit or timeout raises
TurnFailure.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import tempfile

from ..types import TurnFailure, TurnResult, Usage
from ..workspace import Workspace


class CodexRunner:
    def __init__(
        self,
        served_name: str,
        base_url: str,
        config_home: str,
        name: str,
        reasoning: str = "xhigh",
        timeout: int = 18000,
        api_key: str = "dummy",
    ) -> None:
        self.served_name = served_name
        self.base_url = base_url
        # Not used as CODEX_HOME; each turn gets a fresh one (see _make_home).
        self.home = os.path.expanduser(config_home)
        self.name = name
        self.reasoning = reasoning
        self.timeout = timeout
        self.api_key = api_key
        # Subagents inherit the session model (see _config_text).
        self.subagent_model = served_name

    def _config_text(self) -> str:
        # No `default_subagent_model` or [agents] preset: spawn_agent checks a named
        # model against a built-in OpenAI catalog and rejects others, while a spawn
        # with no model inherits the session model.
        return (
            f'model = "{self.served_name}"\n'
            f'model_provider = "vllm"\n'
            f'model_reasoning_effort = "{self.reasoning}"\n'
            f"[model_providers.vllm]\n"
            f'name = "vllm"\n'
            f'base_url = "{self.base_url}/v1"\n'
            f'wire_api = "responses"\n'
            f'env_key = "OPENAI_API_KEY"\n'
        )

    def _make_home(self) -> str:
        """A fresh CODEX_HOME for one `codex exec`, deleted after the turn.

        Concurrent `codex exec` processes sharing a home can deadlock on its
        SQLite state locks.
        """
        home = tempfile.mkdtemp(prefix="codexhome_")
        pathlib.Path(home, "config.toml").write_text(self._config_text())
        return home

    def _env(self, home: str) -> dict:
        base = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("CODEX_", "OPENAI_"))
        }
        base["CODEX_HOME"] = home
        base["OPENAI_API_KEY"] = self.api_key
        return base

    def run_turn(
        self,
        workspace: Workspace,
        agent: str,
        index: int,
        prompt: str,
        budget: int | None = None,
    ) -> TurnResult:
        last = workspace.path / "_codex_last.txt"
        cmd = [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "--dangerously-bypass-approvals-and-sandbox",
            "-C",
            str(workspace.path),
            "--json",
            "-o",
            str(last),
            prompt,
        ]
        home = self._make_home()
        try:
            p = subprocess.run(
                cmd,
                cwd=workspace.path,
                env=self._env(home),
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise TurnFailure(
                f"codex turn {index} timeout after {self.timeout}s"
            ) from e
        finally:
            shutil.rmtree(home, ignore_errors=True)
        usage = self._usage(p.stdout)
        try:
            last.unlink()  # keep it out of the diff
        except OSError:
            pass
        if p.returncode != 0:
            raise TurnFailure(
                f"codex turn {index} exit {p.returncode}: {(p.stderr or '')[:200]}"
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
    def _usage(out: str) -> Usage:
        u = Usage()
        reasoning = 0
        for line in out.splitlines():
            try:
                ev = json.loads(line)
            except Exception:
                continue
            tu = ev.get("usage")
            if ev.get("type") == "turn.completed" and isinstance(tu, dict):
                u.input_tokens += tu.get("input_tokens", 0)
                u.output_tokens += tu.get("output_tokens", 0)
                u.cache_read_tokens += tu.get("cached_input_tokens", 0)
                u.cache_creation_tokens += tu.get("cache_write_input_tokens", 0)
                reasoning += tu.get("reasoning_output_tokens", 0)
        if reasoning:
            u.by_model["reasoning"] = {"output_tokens": reasoning}
        return u
