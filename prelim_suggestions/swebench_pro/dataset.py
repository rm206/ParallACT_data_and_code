"""SWE-bench Pro dataset rows (HF config `default`, split `test`).

Rows are fetched from Hugging Face once and stored as plain json files under
outputs/rows/; everything else reads those files rather than the HF cache.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from . import layout

HF_DATASET = "ScaleAI/SWE-bench_Pro"
CONFIG = "default"  # 642 rows
DEFAULT_SPLIT = "test"

# Fields kept from each row; a missing field becomes None.
KEEP_FIELDS = [
    "repo",
    "instance_id",
    "base_commit",
    "patch",
    "test_patch",
    "problem_statement",
    "requirements",
    "interface",
    "repo_language",
    "fail_to_pass",
    "pass_to_pass",
    "before_repo_set_cmd",
    "selected_test_files_to_run",
    "dockerhub_tag",
]


def iter_hf_rows(config: str = CONFIG, split: str = DEFAULT_SPLIT) -> Iterator[dict]:
    """Stream rows from Hugging Face (used only by the download step)."""
    from datasets import load_dataset

    ds = load_dataset(HF_DATASET, config, split=split)
    for row in ds:
        yield {k: row.get(k) for k in KEEP_FIELDS}


def row_path(instance_id: str) -> Path:
    return layout.ROWS_DIR / f"{instance_id}.json"


def write_row(row: dict) -> Path:
    layout.ROWS_DIR.mkdir(parents=True, exist_ok=True)
    p = row_path(row["instance_id"])
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(row, indent=2), encoding="utf-8")
    tmp.replace(p)
    return p


def load_row(instance_id: str) -> dict:
    return json.loads(row_path(instance_id).read_text(encoding="utf-8"))


def iter_local_rows(limit: int | None = None) -> Iterator[dict]:
    """Yield downloaded rows from outputs/rows/, sorted, up to `limit`."""
    files = sorted(layout.ROWS_DIR.glob("*.json"))
    if limit is not None:
        files = files[:limit]
    for f in files:
        yield json.loads(f.read_text(encoding="utf-8"))


def local_count() -> int:
    if not layout.ROWS_DIR.exists():
        return 0
    return sum(1 for _ in layout.ROWS_DIR.glob("*.json"))
