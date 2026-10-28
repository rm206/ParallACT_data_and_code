"""Download SWE-bench Pro rows to outputs/rows/<instance_id>.json.

Skipped when rows are already on disk, unless --force is given. Repos are not
cloned here.

Usage: python -m swebench_pro.download [--force] [--split test]
"""

from __future__ import annotations

import argparse
import time

from . import dataset, layout


def ensure_rows(force: bool = False, split: str = dataset.DEFAULT_SPLIT) -> int:
    """Download rows unless some are on disk (or `force`); return the count on disk."""
    layout.ensure_persistent_dirs()
    if not force and dataset.local_count() > 0:
        return dataset.local_count()
    n = 0
    t0 = time.time()
    for row in dataset.iter_hf_rows(split=split):
        iid = row.get("instance_id")
        if not iid:
            continue
        if not force and dataset.row_path(iid).exists():
            n += 1
            continue
        dataset.write_row(row)
        n += 1
    print(
        f"rows: {dataset.local_count()} on disk ({n} seen, {time.time() - t0:.0f}s) "
        f"-> {layout.ROWS_DIR}"
    )
    return dataset.local_count()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Download SWE-bench Pro rows to plain files."
    )
    ap.add_argument(
        "--force", action="store_true", help="re-download even if rows exist."
    )
    ap.add_argument("--split", default=dataset.DEFAULT_SPLIT)
    args = ap.parse_args()
    ensure_rows(force=args.force, split=args.split)


if __name__ == "__main__":
    main()
