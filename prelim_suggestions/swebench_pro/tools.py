"""Read-only tools the exploration agent uses to inspect a repo checkout.

Paths are confined to the checkout root, and observations are truncated so one
call cannot flood the model's context.
"""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
from pathlib import Path

MAX_OBS_CHARS = 8000  # cap on any single observation
MAX_READ_LINES = 400  # hard cap on read_file line count
_HAS_RG = shutil.which("rg") is not None

# Directories that are never worth exploring and only waste steps.
_SKIP_DIRS = {
    ".git",
    "node_modules",
    "vendor",
    "dist",
    "build",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".tox",
    "target",
}


def _truncate(s: str) -> str:
    if len(s) <= MAX_OBS_CHARS:
        return s
    return s[:MAX_OBS_CHARS] + f"\n... [truncated, {len(s) - MAX_OBS_CHARS} more chars]"


class RepoTools:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def _resolve(self, rel: str) -> Path | None:
        rel = (rel or ".").lstrip("/")
        p = (self.root / rel).resolve()
        try:
            p.relative_to(self.root)
        except ValueError:
            return None
        return p

    def list_dir(self, path: str = ".") -> str:
        p = self._resolve(path)
        if p is None or not p.exists():
            return f"error: no such path: {path}"
        if p.is_file():
            return f"{path} is a file ({p.stat().st_size} bytes); use read_file."
        entries = []
        for name in sorted(os.listdir(p)):
            if name in _SKIP_DIRS:
                entries.append(f"{name}/  [skipped]")
                continue
            full = p / name
            entries.append(f"{name}/" if full.is_dir() else name)
        return _truncate(
            f"{path}:\n" + "\n".join(entries) if entries else f"{path}: (empty)"
        )

    def read_file(self, path: str, start_line: int = 1, max_lines: int = 200) -> str:
        p = self._resolve(path)
        if p is None or not p.is_file():
            return f"error: no such file: {path}"
        max_lines = max(1, min(int(max_lines or 200), MAX_READ_LINES))
        start_line = max(1, int(start_line or 1))
        try:
            with p.open("r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except Exception as e:  # pragma: no cover - defensive
            return f"error reading {path}: {e}"
        chunk = lines[start_line - 1 : start_line - 1 + max_lines]
        numbered = "".join(f"{start_line + i:6d}\t{ln}" for i, ln in enumerate(chunk))
        header = (
            f"{path} lines {start_line}-{start_line + len(chunk) - 1} of {len(lines)}\n"
        )
        return _truncate(header + numbered)

    def grep(self, pattern: str, path: str = ".", max_matches: int = 50) -> str:
        base = self._resolve(path)
        if base is None or not base.exists():
            return f"error: no such path: {path}"
        max_matches = max(1, min(int(max_matches or 50), 200))
        if _HAS_RG:
            try:
                out = subprocess.run(
                    [
                        "rg",
                        "--line-number",
                        "--no-heading",
                        "--color",
                        "never",
                        "-m",
                        str(max_matches),
                        pattern,
                        str(base),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                res = out.stdout.strip()
                res = res.replace(str(self.root) + "/", "")
                return _truncate(res or f"no matches for /{pattern}/ under {path}")
            except Exception:
                pass  # fall through to python
        return self._grep_py(pattern, base, max_matches)

    def _grep_py(self, pattern: str, base: Path, max_matches: int) -> str:
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return f"error: bad regex: {e}"
        hits: list[str] = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fn in filenames:
                fp = Path(dirpath) / fn
                try:
                    with fp.open("r", encoding="utf-8", errors="replace") as f:
                        for i, ln in enumerate(f, 1):
                            if rx.search(ln):
                                rel = fp.relative_to(self.root)
                                hits.append(f"{rel}:{i}:{ln.rstrip()[:200]}")
                                if len(hits) >= max_matches:
                                    return _truncate("\n".join(hits))
                except Exception:
                    continue
        return _truncate("\n".join(hits) if hits else f"no matches for /{pattern}/")

    def find_files(self, name_glob: str, max_results: int = 100) -> str:
        max_results = max(1, min(int(max_results or 100), 500))
        hits: list[str] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fn in filenames:
                if fnmatch.fnmatch(fn, name_glob):
                    hits.append(str((Path(dirpath) / fn).relative_to(self.root)))
                    if len(hits) >= max_results:
                        return _truncate("\n".join(hits) + "\n... [more]")
        return _truncate(
            "\n".join(sorted(hits)) if hits else f"no files match {name_glob}"
        )

    def dispatch(self, name: str, args: dict) -> str:
        args = args or {}
        try:
            if name == "list_dir":
                return self.list_dir(args.get("path", "."))
            if name == "read_file":
                return self.read_file(
                    args.get("path", ""),
                    args.get("start_line", 1),
                    args.get("max_lines", 200),
                )
            if name == "grep":
                return self.grep(
                    args.get("pattern", ""),
                    args.get("path", "."),
                    args.get("max_matches", 50),
                )
            if name == "find_files":
                return self.find_files(
                    args.get("name_glob", "*"), args.get("max_results", 100)
                )
            return f"error: unknown tool '{name}'"
        except Exception as e:  # pragma: no cover - defensive
            return f"error running {name}: {e}"
