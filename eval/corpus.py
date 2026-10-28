"""Corpus layout helpers: ``<input_folder>/<family>/instance_*.json``.

A copy of ``running_instances/common/engine/corpus.py`` so eval has no dependency
on ``running_instances/``.
"""

from __future__ import annotations

import json
from pathlib import Path

FAMILIES = ("contradictory", "complementary")
_ALIAS = {
    "contra": "contradictory",
    "contradictory": "contradictory",
    "comple": "complementary",
    "complementary": "complementary",
}


def resolve_families(family: str) -> list[str]:
    """`contra`/`comple`/full names -> canonical; `both` -> both, in fixed order."""
    if family == "both":
        return list(FAMILIES)
    key = family.lower()
    if key not in _ALIAS:
        raise SystemExit(f"unknown --family {family!r}; use contra|comple|both")
    return [_ALIAS[key]]


def list_instances(input_folder: Path, family: str) -> list[Path]:
    """All instances for one canonical family, sorted."""
    return sorted((input_folder / family).glob("instance_*.json"))


def label_for(input_folder: Path, override: str | None = None) -> str:
    """Namespace label for outputs; defaults to the input folder's basename."""
    return override or input_folder.resolve().name


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
