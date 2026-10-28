"""Model-free features of a dataset row, used to stratify candidate selection.

`subsystem` names a task's code area from its gold patch alone: the directory of
the non-test file with the most added lines.
"""

from __future__ import annotations

import os
import re

_PLUS_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$", re.M)
_HUNK_RE = re.compile(r"^@@ ")

# A path is a "test" file (not representative of the task's subsystem) if any of
# these appear in it.
_TEST_MARKERS = (
    "__tests__",
    "/test/",
    "/tests/",
    "spec.",
    ".spec.",
    "_test.",
    "test_",
    "/testdata/",
    ".test.",
)


def _is_test_path(path: str) -> bool:
    p = path.lower()
    return any(m in p for m in _TEST_MARKERS)


def _added_lines_per_file(patch: str) -> dict[str, int]:
    """Count '+' (added) lines attributed to each `+++ b/<path>` file block."""
    counts: dict[str, int] = {}
    current: str | None = None
    for line in patch.splitlines():
        m = _PLUS_FILE_RE.match(line)
        if m:
            current = m.group(1).strip()
            counts.setdefault(current, 0)
            continue
        if current is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            counts[current] += 1
    return counts


def changed_source_files(patch: str | None) -> list[str]:
    """All non-test files touched by the patch, most-added-lines first."""
    if not patch:
        return []
    counts = _added_lines_per_file(patch)
    src = {p: n for p, n in counts.items() if not _is_test_path(p)}
    if not src:
        return []
    return sorted(src, key=lambda p: (-src[p], p))


def subsystem(row: dict) -> str:
    """Directory of the dominant changed source file, e.g. 'lib/ansible/module_utils'.

    The full dirname is used because repos nest their source roots at different
    depths, so no fixed path depth works for all of them. Root-level files map to
    '(root)'; empty or tests-only patches to 'unknown'.
    """
    files = changed_source_files(row.get("patch"))
    if not files:
        return "unknown"
    d = os.path.dirname(files[0])
    return d if d else "(root)"
