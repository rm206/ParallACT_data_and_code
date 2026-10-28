"""Shared paths and helpers for authoring dataset instances (both families).

Agent-A rows and the confidence ordering come from prelim_suggestions/outputs/.
Results go to outputs/; per-instance scratch (clones, codex logs, verify I/O)
goes to <repo>/.local/author and is deleted.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

PKG = Path(__file__).resolve().parent  # .../author_new_instances/authoring
PKG_ROOT = PKG.parent  # .../author_new_instances

SEEDS = PKG_ROOT.parent / "dataset" / "v1" / "seeds"  # in-context example bank
INPUTS = PKG_ROOT / "inputs"
# rows/ comes from swebench_pro.download, ordering_<family>.jsonl from suggest.order.
PRELIM_OUTPUTS = Path(
    os.environ.get("PRELIM_OUTPUTS", PKG_ROOT.parent / "prelim_suggestions" / "outputs")
)
ROWS = PRELIM_OUTPUTS / "rows"  # Agent-A rows
ORDERING_DIR = PRELIM_OUTPUTS  # ordering_<family>.jsonl live here
RUN_SCRIPTS = INPUTS / "gt_harness"
PROMPTS = PKG_ROOT / "prompts"
SCHEMA_MD = PROMPTS / "seed_schema.md"

OUTPUT = Path(os.environ.get("AUTHOR_OUTPUT", PKG_ROOT / "outputs" / "generated"))
LEDGER_DIR = OUTPUT.parent  # outputs/ledger_<family>.jsonl

SCRATCH = Path(os.environ.get("AUTHOR_SCRATCH", PKG_ROOT.parent / ".local" / "author"))
WORK = Path(os.environ.get("AUTHOR_WORK", SCRATCH / "work"))


V2_IMAGE_REPO = "ghcr.io/scaleapi/swe-bench_pro-v2"


RUNNER_ID_NOTE = {
    "pytest": "This repo uses **pytest**. `*_fail_to_pass` ids MUST be pytest node "
    "ids: `path/to/test_file.py::TestClass::test_name`. "
    "`runtime.selected_test_files_to_run` = the new test file paths.",
    "mocha": "This repo uses **mocha**. `*_fail_to_pass` ids MUST be "
    "`test/file.js | <full title>` where <full title> is the describe/it "
    "titles joined by a SINGLE SPACE. "
    "`runtime.selected_test_files_to_run` = the new test file paths.",
    "jest": "This repo uses **jest**. `*_fail_to_pass` ids MUST be "
    "`test/file.tsx | <suite> | <test>` — the describe/it hierarchy joined "
    "by ' | ' (pipe). `runtime.selected_test_files_to_run` = the new test file paths.",
    "go": "This repo uses **`go test`**. `*_fail_to_pass` ids MUST be the BARE Go "
    "test function names (e.g. `TestFoo`). Put new tests in `*_test.go` files. "
    "`runtime.selected_test_files_to_run` = the list of those bare test function names.",
}

REPO_ID_NOTE = {
    "protonmail/webclients": "**protonmail/webclients is a yarn-workspaces monorepo; jest runs PER "
    "WORKSPACE.** Two DIFFERENT path conventions you MUST follow:\n"
    "- `runtime.selected_test_files_to_run`: FULL repo-root paths, e.g. "
    "`packages/components/containers/payments/subscription/Foo.test.tsx`.\n"
    "- `*_fail_to_pass` ids: the SAME file but **workspace-relative** (drop the "
    "leading `packages/<pkg>/`), then the jest name hierarchy: "
    "`containers/payments/subscription/Foo.test.tsx | <describe> | <it>`.\n"
    "Jest reports workspace-relative paths, so a repo-root path in a fail_to_pass "
    "id matches NOTHING (0 passes = harness_issue). **The exact id string must be "
    "byte-identical to what the harness parser emits** — a reference copy of THIS "
    "instance's parser is in `GROUND_TRUTH_PARSER.py`; read it and make your ids "
    "match how it builds `full_name`. Match the describe/it titles verbatim.",
}


def image_for(instance_id: str) -> str:
    """The v2 GHCR image for an instance (tagged by the full instance_id)."""
    return f"{V2_IMAGE_REPO}:{instance_id}"


@dataclass
class CodexConfig:
    """How to invoke codex: a binary (or path) plus an optional env overlay. Set
    CODEX_HOME in the environment to use a non-default codex profile."""

    bin: str = "codex"
    model: str = "gpt-5.6-sol"
    reasoning: str = "medium"
    sandbox: str = "workspace-write"
    env: dict = field(default_factory=dict)
    name: str = "codex"

    @classmethod
    def for_name(
        cls, name: str, model: str, reasoning: str, sandbox: str = "workspace-write"
    ) -> "CodexConfig":
        return cls(
            bin=name,
            model=model,
            reasoning=reasoning,
            sandbox=sandbox,
            env={},
            name=name,
        )

    def command(self, wd: Path) -> list[str]:
        return [
            self.bin,
            "exec",
            "-C",
            str(wd),
            "--skip-git-repo-check",
            "--sandbox",
            self.sandbox,
            "-m",
            self.model,
            "-c",
            f'model_reasoning_effort="{self.reasoning}"',
            "-",
        ]

    def describe(self) -> str:
        home = (
            f" CODEX_HOME={self.env['CODEX_HOME']}" if "CODEX_HOME" in self.env else ""
        )
        return f"{self.name} (bin={self.bin}{home}) model={self.model} reasoning={self.reasoning}"


def run_codex(wd: Path, prompt: str, cfg: CodexConfig, log_name: str) -> None:
    log = wd / log_name
    proc_env = {**os.environ, **cfg.env} if cfg.env else None
    with open(log, "w") as f:
        subprocess.run(
            cfg.command(wd),
            input=prompt,
            text=True,
            stdout=f,
            stderr=subprocess.STDOUT,
            env=proc_env,
        )


def load_row(instance_id: str) -> dict:
    return json.load(open(ROWS / f"{instance_id}.json"))


def detect_runner(wd: Path) -> str | None:
    """Runner for the seed. repo_language is authoritative for go/python; JS/TS
    consults the repo's own config for jest vs mocha."""
    repo = wd / "repo"
    row = wd / "source_row.json"
    lang, repo_name = "", None
    if row.exists():
        try:
            d = json.load(open(row))
        except Exception:  # noqa: BLE001
            d = {}
        lang = (d.get("repo_language") or "").lower()
        repo_name = d.get("repo")
    if lang in ("py", "python"):
        return "pytest"
    if lang in ("go", "golang"):
        return "go"
    pkg = repo / "package.json"
    if pkg.exists():
        try:
            scripts = json.loads(pkg.read_text()).get("scripts", {})
        except json.JSONDecodeError:
            scripts = {}
        test = (
            (scripts.get("test") or "")
            + " "
            + " ".join(v for k, v in scripts.items() if "test" in k)
        )
        if "jest" in test:
            return "jest"
        if "mocha" in test:
            return "mocha"
    if list(repo.glob(".mocharc*")):
        return "mocha"
    if list(repo.glob("jest.config*")) or list(repo.glob("jest.setup*")):
        return "jest"
    if list(repo.glob("go.mod")):
        return "go"
    if (
        list(repo.glob("pytest.ini"))
        or list(repo.glob("setup.cfg"))
        or list(repo.glob("pyproject.toml"))
        or list(repo.glob("tox.ini"))
        or list(repo.glob("setup.py"))
        or list(repo.glob("conftest.py"))
        or list(repo.glob("requirements*.txt"))
    ):
        return "pytest"
    JS_RUNNER = {
        "NodeBB/NodeBB": "mocha",
        "element-hq/element-web": "jest",
        "protonmail/webclients": "jest",
        "tutao/tutanota": "jest",
    }
    return JS_RUNNER.get(repo_name)


def clone_repo(repo: str, base_commit: str, dest: Path) -> None:
    """Fetch `repo` at `base_commit` into dest.

    Tries a shallow fetch of the exact commit first; falls back to fetching all
    branches for commits the server won't serve at --depth 1."""
    if (dest / ".git").exists():
        return
    dest.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/{repo}.git"
    subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
    subprocess.run(["git", "remote", "add", "origin", url], cwd=dest, check=True)

    if (
        subprocess.run(
            ["git", "fetch", "-q", "--depth", "1", "origin", base_commit], cwd=dest
        ).returncode
        == 0
    ):
        subprocess.run(["git", "checkout", "-q", "FETCH_HEAD"], cwd=dest, check=True)
        return

    subprocess.run(["git", "fetch", "-q", "origin"], cwd=dest, check=True)
    if (
        subprocess.run(
            ["git", "cat-file", "-e", f"{base_commit}^{{commit}}"], cwd=dest
        ).returncode
        != 0
    ):
        subprocess.run(
            [
                "git",
                "fetch",
                "-q",
                "--tags",
                "origin",
                "+refs/heads/*:refs/remotes/origin/*",
            ],
            cwd=dest,
        )
    subprocess.run(["git", "checkout", "-q", base_commit], cwd=dest, check=True)


def assemble(wd: Path) -> Path:
    """Inject the instance's own SWE-bench Pro v2 run_script + parser (from
    inputs/gt_harness/<instance_id>/) and the repo reset command. A missing
    ground-truth harness is a hard error."""
    seed = json.load(open(wd / "OUTPUT_seed.json"))
    gt = RUN_SCRIPTS / seed["instance_id"]
    rs, ps = gt / "run_script.sh", gt / "parser.py"
    if not (rs.exists() and ps.exists()):
        raise SystemExit(
            f"no ground-truth harness for {seed['instance_id']} at {gt} "
            f"(run_script.sh + parser.py expected)."
        )
    seed["runtime"]["run_script"] = rs.read_text()
    seed["runtime"]["parser"] = ps.read_text()
    seed["runtime"]["before_repo_set_cmd"] = (
        f"git reset --hard {seed['base_commit']}\ngit clean -fdx\n"
        f"git checkout {seed['base_commit']}"
    )
    out = wd / "seed.assembled.json"
    out.write_text(json.dumps(seed, indent=2))
    return out


def validate(wd: Path) -> list[str]:
    """Fast local checks before the container. Returns a list of problems ([] == OK)."""
    seed = json.load(open(wd / "seed.assembled.json"))
    fam = seed["family"]
    req = [
        "instance_id",
        "repo",
        "base_commit",
        "family",
        "runtime",
        "agentA_problem_statement",
        "agentA_solution",
        "agentA_test_patch",
        "agentA_fail_to_pass",
        "agentB_problem_statement",
        "agentB_solution",
        "agentB_test_patch",
        "agentB_fail_to_pass",
    ]
    req += (
        ["integration_test_patch", "integration_fail_to_pass"]
        if fam == "complementary"
        else [
            "combined_test_patch",
            "reconciliation_patch",
            "reconciliation_explanation",
        ]
    )
    problems = [f"missing/empty {k}" for k in req if not seed.get(k)]
    repo = wd / "repo"
    for f in [k for k in seed if k.endswith(("_solution", "_test_patch", "_patch"))]:
        p = wd / "_chk.patch"
        p.write_text(seed[f])
        r = subprocess.run(
            ["git", "apply", "--check", str(p)],
            cwd=repo,
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            problems.append(f"{f}: git apply --check failed ({r.stderr.strip()[:80]})")
    (wd / "_chk.patch").unlink(missing_ok=True)
    return problems


_VERIFY_LOCK = SCRATCH / ".verify.lock"


def verify(wd: Path) -> dict:
    """Run the docker truth-table verifier and classify the result. A file lock
    keeps concurrent instances and family processes from verifying at once."""
    import fcntl

    seed = wd / "seed.assembled.json"
    report = wd / "verification.json"
    cmd = [
        sys.executable,
        "-m",
        "verify.verify",
        str(seed),
        "--report",
        str(report),
        "--quiet",
    ]

    def _run():
        subprocess.run(
            cmd,
            cwd=str(PKG_ROOT),
            stdout=(wd / "verify_run.log").open("w"),
            stderr=subprocess.STDOUT,
        )

    if os.environ.get("AUTHOR_NO_VERIFY_LOCK"):
        _run()
    else:
        _VERIFY_LOCK.parent.mkdir(parents=True, exist_ok=True)
        with open(_VERIFY_LOCK, "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            _run()
    d = json.loads(report.read_text())
    return {"sound": d["sound"], "triage": _triage(d), "report": d}


def _triage(report: dict) -> str:
    if report["sound"]:
        return "sound"
    for r in report["results"]:
        if (
            r["expected"]
            and not r["actual"]
            and r["applied"] == "ok"
            and r["n_pass"] == 0
        ):
            return "harness_issue"
    return "seed_defect"


def cleanup_image(instance_id: str) -> None:
    """Remove an instance's image once it is done (each image serves one instance)."""
    try:
        from verify import runner

        runner.cleanup_image(image_for(instance_id))
    except Exception:  # noqa: BLE001
        pass


def finalize(wd: Path, family: str) -> Path:
    """Write the sound, audited instance to OUTPUT, keeping only the seed schema's
    keys in the order used by an existing example seed."""
    import glob

    seed = json.load(open(wd / "seed.assembled.json"))
    ex = json.load(open(sorted(glob.glob(str(SEEDS / family / "*.json")))[0]))
    order, rtorder = list(ex.keys()), list(ex["runtime"].keys())
    clean = {
        k: (
            {rk: seed["runtime"][rk] for rk in rtorder if rk in seed["runtime"]}
            if k == "runtime"
            else seed[k]
        )
        for k in order
        if k in seed
    }
    dest = OUTPUT / family / f"{seed['instance_id']}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    return dest
