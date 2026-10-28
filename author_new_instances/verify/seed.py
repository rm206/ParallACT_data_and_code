"""Load and lightly validate a flat, self-contained seed JSON."""

from __future__ import annotations

import json
from pathlib import Path

# Fields every seed must carry to be verifiable in docker.
_RUNTIME = ["image_uri", "selected_test_files_to_run", "run_script", "parser"]
_COMMON = ["family", "base_commit", "agentA_solution", "agentB_solution"]


def load(path: str | Path) -> dict:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    missing = [k for k in _COMMON if not d.get(k)]
    rt = d.get("runtime", {})
    missing += [f"runtime.{k}" for k in _RUNTIME if not rt.get(k)]
    if d.get("family") == "contradictory":
        missing += [
            k
            for k in [
                "combined_test_patch",
                "reconciliation_patch",
                "agentA_test_patch",
                "agentB_test_patch",
            ]
            if not d.get(k)
        ]
    elif d.get("family") == "complementary":
        missing += [
            k
            for k in ["integration_test_patch", "integration_fail_to_pass"]
            if not d.get(k)
        ]
    if missing:
        raise ValueError(f"seed missing fields: {missing}")
    return d
