"""Entry point: author contradictory dataset instances.

Run:  python -m authoring.author_contradictory \
          [--target N] [--concurrency N] [--limit N] [--model ...] [--reasoning ...]
"""

from __future__ import annotations

from ._entry import main

if __name__ == "__main__":
    main("contradictory")
