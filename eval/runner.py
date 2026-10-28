"""Docker test runner: apply a combined code patch and the seed's test patches at
``base_commit``, run the seed's ``run_script`` + ``parser`` in its image, and return
per-test statuses.

The in-container steps follow ``running_instances/common/engine/testaccess.py``
(``_IN_CONTAINER``), except that files touched by the gold test patches are first
reset to ``base_commit``, so agent edits to those files are discarded.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import uuid
from pathlib import Path

_DEFAULT_TIMEOUT = int(os.environ.get("EVAL_RUN_TIMEOUT", "2400"))

_TAIL_LINES = 80  # log tail lines kept in the result


def tests_arg_for(*id_lists: list[str]) -> str:
    """Comma-separated files/names to run, derived from test ids (pytest ``::``,
    mocha/jest ``' | '``, bare go names), as in testaccess.py's ``_tests_arg``."""
    items: list[str] = []
    for ids in id_lists:
        for tid in ids or []:
            f = tid.split("::")[0].split(" | ")[0]
            if f and f not in items:
                items.append(f)
    return ",".join(items)


def _entry_script(base_commit: str, has_code: bool) -> str:
    lines = [
        "set -u",
        "cd /app",
        f"BASE={shlex.quote(base_commit)}",
        "git reset --hard $BASE >/dev/null 2>&1",
        "git clean -fdq >/dev/null 2>&1",
        "git config user.email v@v.x >/dev/null 2>&1",
        "git config user.name evaluator >/dev/null 2>&1",
        "APPLIED=ok",
    ]
    if has_code:
        lines.append(
            "git apply /verify/combined.patch 2>>/verify/apply.err || APPLIED=fail"
        )
    lines += [
        'for tp in /verify/test_*.patch; do [ -e "$tp" ] || continue; '
        "for f in $(grep '^diff --git' \"$tp\" | sed -E 's#^diff --git a/(.*) b/.*#\\1#'); do "
        'git checkout $BASE -- "$f" 2>/dev/null || rm -f "$f"; done; done',
        "for tp in /verify/test_*.patch; do "
        '[ -e "$tp" ] && (git apply "$tp" 2>>/verify/apply.err || echo TESTPATCH_FAIL >>/verify/apply.err); done',
        'bash /verify/run_script.sh "$1" > /verify/stdout.log 2> /verify/stderr.log || true',
        "python /verify/parser.py /verify/stdout.log /verify/stderr.log /verify/output.json "
        "2>>/verify/apply.err || echo '{\"tests\":[]}' > /verify/output.json",
        "echo $APPLIED > /verify/applied.txt",
    ]
    return "\n".join(lines) + "\n"


def _tail(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-_TAIL_LINES:])
    except OSError:
        return ""


def run(
    seed: dict,
    combined_patch: str | None,
    test_patches: list[str],
    fail_to_pass: list[str],
    pass_to_pass: list[str] | None = None,
    scratch_dir: str | Path = ".",
    timeout: int | None = None,
) -> dict:
    """Run one code state against a set of tests in the seed's image.

    combined_patch: diff of the code state against base; None grades base unchanged.
    test_patches: gold test patches applied on top.
    fail_to_pass / pass_to_pass: the scored ids; they also select which files run.
    scratch_dir: parent of the temporary bind-mount dir (the temp dir is removed
    before returning).
    timeout: seconds; defaults to $EVAL_RUN_TIMEOUT (2400).

    Returns a dict:
      {applied: ok|fail|timeout, tests_arg,
       all_tests: {name: status, ...},        # every test the parser emitted
       fail_to_pass: {id: PASSED|FAILED|MISSING},
       pass_to_pass: {id: ...},
       n_pass, n_total, p2p_pass, p2p_total,
       stdout_tail, stderr_tail}
    """
    timeout = _DEFAULT_TIMEOUT if timeout is None else timeout
    rt = seed["runtime"]
    base = seed["base_commit"]
    p2p = list(pass_to_pass or [])
    tests_arg = tests_arg_for(fail_to_pass, p2p) or ",".join(
        rt.get("selected_test_files_to_run") or []
    )
    Path(scratch_dir).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(scratch_dir)) as td:
        t = Path(td)
        (t / "run_script.sh").write_text(rt["run_script"], encoding="utf-8")
        (t / "parser.py").write_text(rt["parser"], encoding="utf-8")
        if combined_patch is not None:
            (t / "combined.patch").write_text(combined_patch, encoding="utf-8")
        for i, tp in enumerate(test_patches):
            (t / f"test_{i}.patch").write_text(tp, encoding="utf-8")
        (t / "entry.sh").write_text(
            _entry_script(base, combined_patch is not None), encoding="utf-8"
        )
        cname = f"eval_{uuid.uuid4().hex[:12]}"
        cmd = [
            "docker",
            "run",
            "--rm",
            "--name",
            cname,
            "--platform",
            "linux/amd64",
            "--entrypoint",
            "bash",
            "-v",
            f"{td}:/verify",
            rt["image_uri"],
            "/verify/entry.sh",
            tests_arg,
        ]
        timed_out = False
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            if timed_out:
                subprocess.run(
                    ["docker", "rm", "-f", cname], capture_output=True, text=True
                )
        applied = (
            (t / "applied.txt").read_text().strip()
            if (t / "applied.txt").exists()
            else "fail"
        )
        if timed_out:
            applied = "timeout"
        all_tests: dict[str, str] = {}
        if (t / "output.json").exists():
            try:
                data = json.loads((t / "output.json").read_text())
                all_tests = {x["name"]: x["status"] for x in data.get("tests", [])}
            except Exception:
                pass
        stdout_tail, stderr_tail = _tail(t / "stdout.log"), _tail(t / "stderr.log")

    f2p = {tid: all_tests.get(tid, "MISSING") for tid in fail_to_pass}
    p2p_got = {tid: all_tests.get(tid, "MISSING") for tid in p2p}
    return {
        "applied": applied,
        "tests_arg": tests_arg,
        "all_tests": all_tests,
        "fail_to_pass": f2p,
        "pass_to_pass": p2p_got,
        "n_pass": sum(1 for s in f2p.values() if s == "PASSED"),
        "n_total": len(fail_to_pass),
        "p2p_pass": sum(1 for s in p2p_got.values() if s == "PASSED"),
        "p2p_total": len(p2p),
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
    }
