"""Combine a run's output patch(es) into one code patch that applies to base_commit.

Serial scenarios' `final.patch` is used as-is. Parallel `A.patch` + `B.patch` are
combined by strategy:
    concat      textual concatenation of the two diffs
    git-merge   two branches off base, `git merge`; a conflict fails
    reconciler  git-merge, then resolve each conflict hunk with the merge-resolver model

Returns {"patch": <str|None>, "status": "ok"|"apply_fail"|"conflict"|"reconcile_fail"}.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(args, cwd, **kw):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, **kw)


def fetch_repo(repo: str, base_commit: str, dest: Path) -> Path:
    """Check out github.com/<repo> at base_commit into dest/repo (reused if present)."""
    rd = dest / "repo"
    if (rd / ".git").exists():
        _git(["reset", "--hard", base_commit], rd)
        _git(["clean", "-fdq"], rd)
        return rd
    rd.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q"], rd)
    _git(["remote", "add", "origin", f"https://github.com/{repo}.git"], rd)
    if _git(["fetch", "-q", "--depth", "1", "origin", base_commit], rd).returncode == 0:
        _git(["checkout", "-q", "FETCH_HEAD"], rd)
    else:
        _git(["fetch", "-q", "--depth", "50", "origin"], rd)
        _git(["checkout", "-q", base_commit], rd)
    return rd


def _apply_commit(rd: Path, base: str, branch: str, patch: str) -> bool:
    _git(["checkout", "-q", "-B", branch, base], rd)
    (rd / "_x.patch").write_text(patch, encoding="utf-8")
    ok = _git(["apply", "_x.patch"], rd).returncode == 0
    (rd / "_x.patch").unlink(missing_ok=True)
    if not ok:
        return False
    _git(["add", "-A"], rd)
    _git(
        ["-c", "user.email=e@e.x", "-c", "user.name=eval", "commit", "-qm", branch], rd
    )
    return True


def combine(seed: dict, outputs: dict[str, str], strategy: str, workdir: Path) -> dict:
    if "final" in outputs:
        return {"patch": outputs["final"], "status": "ok"}

    a, b = outputs.get("A"), outputs.get("B")
    if a is None or b is None:
        return {"patch": None, "status": "apply_fail"}

    if strategy == "concat":
        return {"patch": a.rstrip("\n") + "\n" + b, "status": "ok"}

    base = seed["base_commit"]
    rd = fetch_repo(seed["repo"], base, workdir)
    _git(["config", "user.email", "e@e.x"], rd)
    _git(["config", "user.name", "eval"], rd)
    if not _apply_commit(rd, base, "_a", a) or not _apply_commit(rd, base, "_b", b):
        return {"patch": None, "status": "apply_fail"}
    _git(["checkout", "-q", "_a"], rd)
    merged = _git(["merge", "--no-edit", "_b"], rd)

    if merged.returncode != 0:
        if strategy == "git-merge":
            _git(["merge", "--abort"], rd)
            return {"patch": None, "status": "conflict"}
        from . import reconciler

        conflicted = _git(["diff", "--name-only", "--diff-filter=U"], rd).stdout.split()
        for rel in conflicted:
            f = rd / rel
            try:
                resolved = reconciler.resolve_file(f.read_text(errors="replace"))
            except Exception:
                _git(["merge", "--abort"], rd)
                return {"patch": None, "status": "reconcile_fail"}
            if "<<<<<<<" in resolved:
                _git(["merge", "--abort"], rd)
                return {"patch": None, "status": "reconcile_fail"}
            f.write_text(resolved, encoding="utf-8")
            _git(["add", rel], rd)
        _git(
            [
                "-c",
                "user.email=e@e.x",
                "-c",
                "user.name=eval",
                "commit",
                "-qm",
                "reconciled",
            ],
            rd,
        )

    patch = _git(["diff", base, "HEAD"], rd).stdout
    return {"patch": patch, "status": "ok"}
