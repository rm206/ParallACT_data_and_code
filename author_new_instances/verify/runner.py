"""Docker executor: build one code state in the seed's image, run its tests with
the seed's run_script.sh, and parse per-test results with its parser.py.

Each check runs in a fresh `docker run --rm` container so no state carries over.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Bind-mount scratch, inside the project (gitignored .local/), deleted per check.
SCRATCH = (
    Path(os.environ.get("AUTHOR_SCRATCH", HERE.parent.parent / ".local" / "author"))
    / "verify"
)


def _entry_script(
    base_commit: str, code_patches: list[str], merge: str | None, tests_arg: str
) -> str:
    """Bash run inside the container. Applies the code state + test patch, runs
    the project's test runner, then the parser."""
    lines = [
        "set -u",
        "cd /app || { echo no-app >&2; echo fail > /verify/applied.txt; exit 0; }",
        f"BASE={shlex.quote(base_commit)}",
        "git reset --hard $BASE >/dev/null 2>/verify/apply.err",
        "git clean -fdq >/dev/null 2>&1",
        "git config user.email v@v.x >/dev/null 2>&1",
        "git config user.name verifier >/dev/null 2>&1",
        "APPLIED=ok",
    ]
    if merge is None:
        for i in range(len(code_patches)):
            lines.append(
                f"git apply /verify/code{i}.patch 2>>/verify/apply.err || APPLIED=fail"
            )
    elif merge == "concat":
        cat = " ".join(f"/verify/code{i}.patch" for i in range(len(code_patches)))
        lines += [
            f"cat {cat} > /verify/concat.patch",
            "git apply /verify/concat.patch 2>>/verify/apply.err || APPLIED=fail",
        ]
    elif merge == "git":
        # Two branches off base, then merge; a conflict is a legitimate FAIL.
        lines += [
            "git checkout -q -b _a $BASE",
            "git apply /verify/code0.patch 2>>/verify/apply.err && git add -A && "
            "git commit -qm A || APPLIED=fail",
            "git checkout -q -b _b $BASE",
            "git apply /verify/code1.patch 2>>/verify/apply.err && git add -A && "
            "git commit -qm B || APPLIED=fail",
            "git checkout -q _a",
            "git merge --no-edit _b >>/verify/apply.err 2>&1 || APPLIED=conflict",
        ]
    else:
        raise ValueError(f"unknown merge: {merge}")

    lines += [
        "git apply /verify/test.patch 2>>/verify/apply.err || echo TESTPATCH_FAIL >>/verify/apply.err",
        'PY="$(command -v python || command -v python3)"',
        f"bash /verify/run_script.sh {shlex.quote(tests_arg)} "
        "> /verify/stdout.log 2> /verify/stderr.log || true",
        '"$PY" /verify/parser.py /verify/stdout.log /verify/stderr.log '
        "/verify/output.json 2>>/verify/apply.err || echo '{\"tests\":[]}' > /verify/output.json",
        "echo $APPLIED > /verify/applied.txt",
    ]
    return "\n".join(lines) + "\n"


def run_suite(
    seed: dict,
    code_patches: list[str],
    merge: str | None,
    test_patch: str,
    fail_to_pass: list[str],
    timeout: int = 1800,
) -> dict:
    """Run one code-state + test set in the seed's image; return statuses and
    pass counts."""
    rt = seed["runtime"]
    image = rt["image_uri"]
    base_commit = seed["base_commit"]
    # Run exactly the files holding this check's target tests, derived from the
    # fail_to_pass ids (path before the test-name separator: pytest "::" or
    # mocha/jest " | "). Fall back to the seed's static list if none derivable.
    files = []
    for tid in fail_to_pass:
        f = tid.split("::")[0].split(" | ")[0]
        if f and f not in files:
            files.append(f)
    tests_arg = ",".join(files or rt["selected_test_files_to_run"])

    SCRATCH.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(SCRATCH)) as td:
        t = Path(td)
        (t / "run_script.sh").write_text(rt["run_script"], encoding="utf-8")
        (t / "parser.py").write_text(rt["parser"], encoding="utf-8")
        (t / "test.patch").write_text(test_patch, encoding="utf-8")
        for i, p in enumerate(code_patches):
            (t / f"code{i}.patch").write_text(p, encoding="utf-8")
        (t / "entry.sh").write_text(
            _entry_script(base_commit, code_patches, merge, tests_arg), encoding="utf-8"
        )

        # The images set ENTRYPOINT=/bin/bash, so override it and pass the script
        # path as the sole argument. Named so a client-side timeout can force-remove
        # the container (--rm only fires on normal exit).
        cname = f"verify_{uuid.uuid4().hex[:12]}"
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
            image,
            "/verify/entry.sh",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            subprocess.run(
                ["docker", "rm", "-f", cname], capture_output=True, text=True
            )
            return {
                "statuses": {tid: "MISSING" for tid in fail_to_pass},
                "all_passed": False,
                "applied": "timeout",
                "n_pass": 0,
                "n_total": len(fail_to_pass),
            }
        applied_file = t / "applied.txt"
        if not applied_file.exists():
            # docker failed before entry ran (e.g. image pull error) -> surface it.
            detail = (proc.stdout + proc.stderr)[-400:]
            return {
                "statuses": {tid: "MISSING" for tid in fail_to_pass},
                "all_passed": False,
                "applied": "infra_fail",
                "n_pass": 0,
                "n_total": len(fail_to_pass),
                "infra": detail,
            }

        applied = applied_file.read_text().strip() or "fail"
        statuses = {}
        out = t / "output.json"
        if out.exists():
            try:
                data = json.loads(out.read_text())
                statuses = {x["name"]: x["status"] for x in data.get("tests", [])}
            except Exception:
                pass

    got = {tid: statuses.get(tid, "MISSING") for tid in fail_to_pass}
    n_pass = sum(1 for s in got.values() if s == "PASSED")
    return {
        "statuses": got,
        "all_passed": n_pass == len(fail_to_pass) and fail_to_pass != [],
        "applied": applied,
        "n_pass": n_pass,
        "n_total": len(fail_to_pass),
    }


def cleanup_image(image_uri: str) -> None:
    """Remove an instance's image once it is done. AUTHOR_KEEP_IMAGES=1 keeps it."""
    if os.environ.get("AUTHOR_KEEP_IMAGES"):
        return
    try:
        subprocess.run(
            ["docker", "rmi", "-f", image_uri], capture_output=True, text=True
        )
    except Exception:  # noqa: BLE001 — cleanup must never kill the run
        pass
