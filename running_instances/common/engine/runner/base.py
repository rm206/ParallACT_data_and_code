"""The backend seam: a Runner turns a prompt + workspace into a diff."""

from __future__ import annotations

from typing import Protocol

from ..types import TurnResult
from ..workspace import Workspace


class Runner(Protocol):
    name: str

    def run_turn(
        self,
        workspace: Workspace,
        agent: str,
        index: int,
        prompt: str,
        budget: int | None = None,
    ) -> TurnResult:
        """Run one agent turn in the workspace and return its diff + transcript.

        `budget` is an optional step cap; the current backends ignore it.
        """
        ...
