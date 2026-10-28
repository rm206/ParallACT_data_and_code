"""Gold-test access for scenarios with ``test_access == OWN``.

Each turn gets readable copies of its gold tests in ``_gold_tests/`` and a
``./run-tests`` script (both git-excluded). The script runs the tests via
``docker exec`` in one container per turn, started from the instance's eval image,
using the same steps as ``eval/runner.py``.

Which tests a turn gets:
  contradictory  AB -> combined_test_patch      + agentA_fail_to_pass + agentB_fail_to_pass
                 A  -> agentA_test_patch         + agentA_fail_to_pass
                 B  -> agentB_test_patch         + agentB_fail_to_pass
  complementary  AB -> integration_test_patch    + integration_fail_to_pass

If docker or the container is unavailable, ``run-tests`` just reports that and
the turn continues.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path

from .workspace import Workspace

RUN_TESTS = "run-tests"
_GOLD_DIR = "_gold_tests"

# Pull images one at a time: concurrent multi-GB pulls can all exceed the start
# timeout. Container starts stay parallel once the image is local.
_PULL_LOCK = threading.Lock()
_PULL_TIMEOUT = 7200
_RUN_TIMEOUT = 900  # container start from a local image

# Images this process pulled; only these are removed by evict_pulled_image.
_PULLED: set[str] = set()


def _ensure_image(image: str, log) -> bool:
    """Pull `image` if missing (one pull at a time); return True if it is available."""

    def present() -> bool:
        return (
            subprocess.run(
                ["docker", "image", "inspect", image], capture_output=True, text=True
            ).returncode
            == 0
        )

    try:
        if present():
            return True
        with _PULL_LOCK:
            if present():
                return True
            log(f"image PULL start  image={image}")
            p = subprocess.run(
                ["docker", "pull", "--platform", "linux/amd64", image],
                capture_output=True,
                text=True,
                timeout=_PULL_TIMEOUT,
            )
            if p.returncode != 0:
                log(
                    f"image PULL FAILED rc={p.returncode} err={(p.stderr or '').strip()[:200]}"
                )
                return False
            _PULLED.add(image)
            log(f"image PULL ok  image={image}")
            return True
    except Exception as e:  # noqa: BLE001 — docker missing/slow must not abort the run
        log(f"image PULL EXCEPTION {e!r}")
        return False


def evict_pulled_image(image: str, log) -> None:
    """`docker rmi` the image if this process pulled it; call once its containers are removed."""
    with _PULL_LOCK:
        if image not in _PULLED:
            return
        r = subprocess.run(["docker", "rmi", image], capture_output=True, text=True)
        if r.returncode == 0:
            _PULLED.discard(image)
            log(f"image EVICTED  image={image}")
        else:
            log(
                f"image evict skipped rc={r.returncode} err={(r.stderr or '').strip()[:160]}"
            )


def _test_set(seed: dict, agent: str) -> tuple[list[str], list[str]]:
    """(test_patches, fail_to_pass) the given agent should see/run."""
    fam = seed.get("family")
    if fam == "complementary":
        if agent == "AB":
            return [seed["integration_test_patch"]], list(
                seed["integration_fail_to_pass"]
            )
        # Not reached: the parallel gold-test scenario is contradictory-only.
        return [seed[f"agent{agent}_test_patch"]], list(
            seed[f"agent{agent}_fail_to_pass"]
        )
    if agent == "AB":
        return (
            [seed["combined_test_patch"]],
            list(seed["agentA_fail_to_pass"]) + list(seed["agentB_fail_to_pass"]),
        )
    return [seed[f"agent{agent}_test_patch"]], list(seed[f"agent{agent}_fail_to_pass"])


def _tests_arg(fail_to_pass: list[str]) -> str:
    """Comma-separated test files/names from fail_to_pass ids (as in eval/runner.tests_arg_for)."""
    items: list[str] = []
    for tid in fail_to_pass:
        f = tid.split("::")[0].split(" | ")[0]
        if f and f not in items:
            items.append(f)
    return ",".join(items)


def _readable(test_patches: list[str]) -> dict[str, str]:
    """Files for `_gold_tests/`: each raw patch, plus source for files the patch adds."""
    files: dict[str, str] = {}
    for i, patch in enumerate(test_patches):
        files[f"{_GOLD_DIR}/{i:02d}_gold_test.patch"] = patch
        for m in re.finditer(
            r"^diff --git a/.+? b/(.+?)$.*?^new file mode.*?(^@@.*)", patch, re.M | re.S
        ):
            path, body = m.group(1), m.group(2)
            lines = []
            for ln in body.splitlines():
                if ln.startswith("@@") or ln.startswith("\\"):
                    continue
                if ln.startswith("+"):
                    lines.append(ln[1:])
                elif ln.startswith((" ", "-")):
                    continue
            files[f"{_GOLD_DIR}/{Path(path).name}"] = "\n".join(lines) + "\n"
    return files


# Containers left by a crashed run can be removed with:
#   docker ps -aq --filter name=gt_run_ | xargs docker rm -f
_NAME_PREFIX = "gt_run_"

_IN_CONTAINER = r"""set -u
cd /app
BASE=__BASE__
git reset --hard "$BASE" >/dev/null 2>&1
git clean -fdq >/dev/null 2>&1
git config user.email v@v.x >/dev/null 2>&1
git config user.name evaluator >/dev/null 2>&1
APPLIED=ok
git apply /verify/code.patch 2>>/verify/apply.err || APPLIED=fail
for tp in /verify/test_*.patch; do
  [ -e "$tp" ] && (git apply "$tp" 2>>/verify/apply.err || echo TESTPATCH_FAIL >>/verify/apply.err)
done
bash /verify/run_script.sh "$1" > /verify/stdout.log 2> /verify/stderr.log || true
python /verify/parser.py /verify/stdout.log /verify/stderr.log /verify/output.json \
  2>>/verify/apply.err || echo '{"tests":[]}' > /verify/output.json
echo "$APPLIED" > /verify/applied.txt
"""

_RUN_TESTS = r"""#!/usr/bin/env python3
# Provisioned per agent turn; runs THIS workspace's gold tests in a warm
# container via `docker exec`. Reads its config from the sidecar json. Every
# invocation is appended to CFG["log"] (a persistent file under the run dir) so
# the harness can later verify the agent actually ran its tests and what it saw.
import datetime, json, os, subprocess, sys
CFG = json.loads(r'''__CFG__''')
BASE, EXCHANGE, CNAME = CFG["base"], CFG["exchange"], CFG["cname"]
TESTS_ARG, IDS, LOG = CFG["tests_arg"], CFG["ids"], CFG["log"]

def sh(*a, **k):
    return subprocess.run(a, capture_output=True, text=True, **k)

def logline(msg):
    try:
        with open(LOG, "a") as f:
            f.write(f"{datetime.datetime.now():%F %T}  {msg}\n")
    except OSError:
        pass

# 1. Snapshot the agent's current change vs base (mirrors Workspace.diff_base;
#    _gold_tests/ and run-tests are git-excluded, so they are never included).
ws = os.path.dirname(os.path.abspath(__file__))
sh("git", "add", "-A", cwd=ws)
diff = sh("git", "diff", "--cached", BASE, cwd=ws).stdout
with open(os.path.join(EXCHANGE, "code.patch"), "w") as f:
    f.write(diff)
open(os.path.join(EXCHANGE, "apply.err"), "w").close()

print("Running your gold tests in the project environment "
      "(clean container, may take a minute)...", flush=True)
r = sh("docker", "exec", CNAME, "bash", "/verify/run_in_container.sh", TESTS_ARG)
if r.returncode != 0:
    logline(f"INVOKE diff_bytes={len(diff)} -> docker exec FAILED rc={r.returncode}")
    sys.stderr.write("run-tests: the test environment is unavailable right now; "
                     "your changes were not tested.\n" + (r.stderr or "") + "\n")
    sys.exit(1)

# 2. Read results and report.
try:
    data = json.load(open(os.path.join(EXCHANGE, "output.json")))
    statuses = {x["name"]: x["status"] for x in data.get("tests", [])}
except Exception:
    statuses = {}
try:
    applied = open(os.path.join(EXCHANGE, "applied.txt")).read().strip()
except OSError:
    applied = "?"
got = {i: statuses.get(i, "MISSING") for i in IDS}
n_pass = sum(1 for s in got.values() if s == "PASSED")
logline(f"INVOKE diff_bytes={len(diff)} applied={applied} "
        f"result={n_pass}/{len(IDS)} " + json.dumps(got))
print(f"\nRESULT: {n_pass}/{len(IDS)} passed")
for i, s in got.items():
    print(f"  {s:7} {i}")
if n_pass == len(IDS):
    print("\nAll your gold tests pass.")
    sys.exit(0)
# On failure, show the real test output so the agent can fix it.
tail = ""
for name in ("stdout.log", "stderr.log"):
    p = os.path.join(EXCHANGE, name)
    if os.path.exists(p):
        tail += open(p, errors="replace").read()
tail = "\n".join(tail.splitlines()[-60:])
print("\n--- test output (tail) ---")
print(tail)
print("--------------------------")
print(f"{len(IDS) - n_pass} not passing. Adjust your changes and run ./run-tests again.")
sys.exit(1)
"""


class NullTestAccess:
    """Used when a scenario has no test access; every call is a no-op."""

    def attach(self, workspace: Workspace, agent: str) -> None:
        return None

    def cleanup(self) -> None:
        return None


class GoldTestAccess:
    """Provisions gold tests and a container per turn.

    Logs go to ``run_dir``: ``gt.log`` (container lifecycle) and
    ``run_tests_<agent>.log`` (each ``./run-tests`` call and its result).
    """

    def __init__(self, seed: dict, run_dir: Path) -> None:
        self._seed = seed
        self._run_dir = Path(run_dir)
        self._run_dir.mkdir(parents=True, exist_ok=True)
        self._containers: list[str] = []
        self._exchanges: list[Path] = []

    def _log(self, msg: str) -> None:
        import datetime

        try:
            with (self._run_dir / "gt.log").open("a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now():%F %T}  {msg}\n")
        except OSError:
            pass

    def attach(self, workspace: Workspace, agent: str) -> None:
        test_patches, ids = _test_set(self._seed, agent)
        workspace.provision_untracked(_readable(test_patches))

        # Exchange dir, mounted at /verify in the container.
        exchange = Path(tempfile.mkdtemp(prefix="gt_ex_", dir="/tmp"))
        self._exchanges.append(exchange)
        rt = self._seed["runtime"]
        (exchange / "run_script.sh").write_text(rt["run_script"], encoding="utf-8")
        (exchange / "parser.py").write_text(rt["parser"], encoding="utf-8")
        for i, tp in enumerate(test_patches):
            (exchange / f"test_{i}.patch").write_text(tp, encoding="utf-8")
        (exchange / "run_in_container.sh").write_text(
            _IN_CONTAINER.replace("__BASE__", shlex.quote(self._seed["base_commit"])),
            encoding="utf-8",
        )

        cname = _NAME_PREFIX + uuid.uuid4().hex[:12]
        started = self._start_container(cname, exchange, rt["image_uri"])
        if started:
            self._containers.append(cname)
            self._log(
                f"container {cname} STARTED  agent={agent} "
                f"image={rt['image_uri']} ids={len(ids)}"
            )
        else:
            self._log(
                f"container START FAILED  agent={agent} "
                f"image={rt['image_uri']} (run-tests will report unavailable)"
            )

        cfg = {
            "base": self._seed["base_commit"],
            "exchange": str(exchange),
            "cname": cname if started else "",
            "tests_arg": _tests_arg(ids),
            "ids": ids,
            "log": str(self._run_dir / f"run_tests_{agent}.log"),
        }
        self._write_run_tests(workspace, cfg, unavailable=not started)
        workspace.gitignore(RUN_TESTS, _GOLD_DIR + "/")

    def _start_container(self, cname: str, exchange: Path, image: str) -> bool:
        try:
            # Pull separately so a slow pull doesn't count against _RUN_TIMEOUT.
            if not _ensure_image(image, self._log):
                return False
            r = subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--platform",
                    "linux/amd64",
                    "--name",
                    cname,
                    "--entrypoint",
                    "sleep",
                    "-v",
                    f"{exchange}:/verify",
                    image,
                    "infinity",
                ],
                capture_output=True,
                text=True,
                timeout=_RUN_TIMEOUT,
            )
            if r.returncode != 0:
                self._log(
                    f"docker run FAILED rc={r.returncode} "
                    f"err={(r.stderr or '').strip()[:200]}"
                )
            return r.returncode == 0
        except Exception as e:  # noqa: BLE001 — docker missing/slow must not abort the run
            self._log(f"docker run EXCEPTION {e!r}")
            return False

    def _write_run_tests(
        self, workspace: Workspace, cfg: dict, unavailable: bool
    ) -> None:
        import stat

        script = workspace.path / RUN_TESTS
        if unavailable:
            script.write_text(
                "#!/usr/bin/env bash\n"
                "echo 'run-tests: test environment unavailable for this run.' >&2\n"
                "exit 1\n",
                encoding="utf-8",
            )
        else:
            script.write_text(
                _RUN_TESTS.replace("__CFG__", json.dumps(cfg)), encoding="utf-8"
            )
        script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP)

    def cleanup(self) -> None:
        for cname in self._containers:
            subprocess.run(
                ["docker", "rm", "-f", cname], capture_output=True, text=True
            )
            self._log(f"container {cname} REMOVED")
        self._containers.clear()
        for ex in self._exchanges:
            subprocess.run(["rm", "-rf", str(ex)], capture_output=True)
        self._exchanges.clear()


def make(seed: dict, test_access, run_dir: Path) -> "GoldTestAccess | NullTestAccess":
    from .types import TestAccess

    if test_access is TestAccess.OWN:
        return GoldTestAccess(seed, run_dir)
    return NullTestAccess()
