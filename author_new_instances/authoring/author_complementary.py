"""Entry point: author complementary dataset instances.

Run:  python -m authoring.author_complementary \
          [--target N] [--concurrency N] [--limit N] [--model ...] [--reasoning ...]
"""

from __future__ import annotations

from ._entry import main

if __name__ == "__main__":
    main("complementary")
