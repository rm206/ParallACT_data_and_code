"""Git working copy of a seed's repo at base_commit, obtained via a RepoSource.

A workspace diffs against base_commit, snapshots turns as commits, controls
whether the next turn sees prior history, and can add files excluded from diffs.
"""

from __future__ import annotations

import fcntl
import subprocess
import uuid
from pathlib import Path
from typing import Protocol

from .types import Visibility

_BASE_TAG = "run_base"


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return out.stdout


class RepoSource(Protocol):
    def materialize(self, seed: dict, dest: Path) -> None:
        """Populate `dest` with the repo checked out at seed['base_commit']."""
        ...


class GitCloneSource:
    """Clone the repo from GitHub and check out base_commit."""

    def __init__(self, base_url: str = "https://github.com") -> None:
        self.base_url = base_url

    def materialize(self, seed: dict, dest: Path) -> None:
        url = f"{self.base_url}/{seed['repo']}.git"
        subprocess.run(["git", "clone", "--quiet", url, str(dest)], check=True)
        subprocess.run(
            ["git", "checkout", "--quiet", seed["base_commit"]], cwd=dest, check=True
        )


class CachedCloneSource:
    """Clone workspaces from a local bare mirror per repo.

    The mirror `<cache_dir>/mirrors/<repo_slug>.git` is cloned from GitHub on
    first use, under a per-repo file lock and an atomic rename.
    """

    def __init__(self, cache_dir: Path, base_url: str = "https://github.com") -> None:
        self.mirrors = Path(cache_dir) / "mirrors"
        self.base_url = base_url

    def _mirror_path(self, repo: str) -> Path:
        return self.mirrors / f"{repo.replace('/', '__')}.git"

    def _ensure_mirror(self, repo: str) -> Path:
        mirror = self._mirror_path(repo)
        if mirror.exists():
            return mirror
        self.mirrors.mkdir(parents=True, exist_ok=True)
        lock = self.mirrors / f"{repo.replace('/', '__')}.lock"
        with open(lock, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)  # one cloner per repo, across processes
            try:
                if not mirror.exists():
                    tmp = mirror.with_name(mirror.name + ".tmp")
                    subprocess.run(["rm", "-rf", str(tmp)], check=False)
                    subprocess.run(
                        [
                            "git",
                            "clone",
                            "--mirror",
                            f"{self.base_url}/{repo}.git",
                            str(tmp),
                        ],
                        check=True,
                    )
                    tmp.rename(mirror)
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)
        return mirror

    def materialize(self, seed: dict, dest: Path) -> None:
        mirror = self._ensure_mirror(seed["repo"])
        subprocess.run(["git", "clone", "--quiet", str(mirror), str(dest)], check=True)
        subprocess.run(
            ["git", "checkout", "--quiet", seed["base_commit"]], cwd=dest, check=True
        )


class Workspace:
    def __init__(self, path: Path, base_commit: str) -> None:
        self.path = path
        self.base_commit = base_commit

    @classmethod
    def create(
        cls, seed: dict, root: Path, source: RepoSource | None = None
    ) -> "Workspace":
        path = root / f"ws_{uuid.uuid4().hex[:8]}"
        (source or GitCloneSource()).materialize(seed, path)
        base = seed["base_commit"]
        ws = cls(path, base)
        _git(path, "reset", "--hard", base)
        _git(path, "clean", "-fdq")
        _git(path, "config", "user.email", "runner@run.x")
        _git(path, "config", "user.name", "runner")
        _git(path, "tag", "-f", _BASE_TAG, base)
        return ws

    def diff_base(self) -> str:
        """Patch from base_commit to the current state, including new files.

        Files listed in .git/info/exclude are not included.
        """
        _git(self.path, "add", "-A")
        return _git(self.path, "diff", "--cached", self.base_commit)

    def snapshot(self, message: str) -> str:
        """Commit the turn's changes; return the commit sha."""
        _git(self.path, "add", "-A")
        _git(self.path, "commit", "-q", "--allow-empty", "-m", message)
        return _git(self.path, "rev-parse", "HEAD").strip()

    def apply_history_visibility(self, visibility: Visibility) -> None:
        """REPO_ONLY: collapse prior commits so the next turn cannot read history."""
        if visibility is Visibility.WITH_HISTORY:
            return
        _git(self.path, "reset", "--soft", self.base_commit)
        _git(self.path, "add", "-A")
        _git(self.path, "commit", "-q", "--allow-empty", "-m", "state")

    def provision_untracked(self, files: dict[str, str]) -> None:
        """Write scaffolding and gitignore it so it never appears in a diff."""
        ignore = self.path / ".git" / "info" / "exclude"
        with ignore.open("a", encoding="utf-8") as fh:
            for rel, content in files.items():
                dst = self.path / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(content, encoding="utf-8")
                fh.write(rel + "\n")

    def gitignore(self, *rel_paths: str) -> None:
        ignore = self.path / ".git" / "info" / "exclude"
        with ignore.open("a", encoding="utf-8") as fh:
            for rel in rel_paths:
                fh.write(rel + "\n")

    def cleanup(self) -> None:
        subprocess.run(["rm", "-rf", str(self.path)], capture_output=True)
