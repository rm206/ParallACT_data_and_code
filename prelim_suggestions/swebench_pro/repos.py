"""Check out a repository at a base commit under scratch.

One bare mirror per repo and a detached `git worktree` per instance, so instances
of the same repo share one object store. Checkouts and mirrors are deleted once
no longer needed to keep scratch bounded.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

from . import layout


class GitError(RuntimeError):
    pass


# One lock per repo so concurrent workers do not clone the same mirror twice or
# run overlapping `git worktree` operations against the same object store.
_repo_locks: dict[str, threading.Lock] = {}
_repo_locks_guard = threading.Lock()


def _repo_lock(repo: str) -> threading.Lock:
    with _repo_locks_guard:
        lock = _repo_locks.get(repo)
        if lock is None:
            lock = _repo_locks[repo] = threading.Lock()
        return lock


def _run(args: list[str], cwd: str | Path | None = None, timeout: int = 1800) -> str:
    p = subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if p.returncode != 0:
        raise GitError(f"$ {' '.join(args)}\n{p.stderr.strip()}")
    return p.stdout


def repo_url(repo: str) -> str:
    return f"https://github.com/{repo}.git"


def mirror_path(repo: str) -> Path:
    return layout.MIRRORS_DIR / f"{layout.repo_slug(repo)}.git"


def checkout_path(instance_id: str) -> Path:
    return layout.CHECKOUTS_DIR / instance_id


def ensure_mirror(repo: str) -> Path:
    """Return the repo's bare mirror, cloning it on first use."""
    layout.MIRRORS_DIR.mkdir(parents=True, exist_ok=True)
    mirror = mirror_path(repo)
    if not (mirror / "HEAD").exists():
        _run(["git", "clone", "--mirror", repo_url(repo), str(mirror)])
    return mirror


def _has_commit(mirror: Path, commit: str) -> bool:
    try:
        _run(
            ["git", "-C", str(mirror), "cat-file", "-e", f"{commit}^{{commit}}"],
            timeout=60,
        )
        return True
    except GitError:
        return False


def ensure_checkout(repo: str, base_commit: str, instance_id: str) -> Path:
    """Return a worktree of `repo` at `base_commit`, creating it if needed.

    Git operations are serialized per repo, so this is thread-safe."""
    layout.CHECKOUTS_DIR.mkdir(parents=True, exist_ok=True)
    dest = checkout_path(instance_id)
    if dest.exists() and any(dest.iterdir()):
        return dest
    with _repo_lock(repo):
        if dest.exists() and any(dest.iterdir()):
            return dest
        mirror = ensure_mirror(repo)
        if not _has_commit(mirror, base_commit):
            # The mirror may predate the commit (rare); refresh once.
            _run(["git", "-C", str(mirror), "remote", "update", "--prune"])
        if not _has_commit(mirror, base_commit):
            raise GitError(f"commit {base_commit} not found in {repo}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "-C", str(mirror), "worktree", "prune"])
        _run(
            [
                "git",
                "-C",
                str(mirror),
                "worktree",
                "add",
                "--detach",
                str(dest),
                base_commit,
            ]
        )
    return dest


def remove_checkout(repo: str, instance_id: str) -> None:
    """Delete one instance's worktree; best-effort, never raises."""
    dest = checkout_path(instance_id)
    if not dest.exists():
        return
    try:
        with _repo_lock(repo):
            mirror = mirror_path(repo)
            if (mirror / "HEAD").exists():
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(mirror),
                        "worktree",
                        "remove",
                        "--force",
                        str(dest),
                    ],
                    capture_output=True,
                    text=True,
                )
                subprocess.run(
                    ["git", "-C", str(mirror), "worktree", "prune"],
                    capture_output=True,
                    text=True,
                )
            shutil.rmtree(dest, ignore_errors=True)
    except Exception:  # noqa: BLE001 — cleanup must not kill the run
        shutil.rmtree(dest, ignore_errors=True)


def remove_mirror(repo: str) -> None:
    """Delete a repo's bare mirror once its instances are done."""
    mirror = mirror_path(repo)
    if mirror.exists():
        shutil.rmtree(mirror, ignore_errors=True)
