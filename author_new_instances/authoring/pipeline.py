"""Per-family authoring pipeline: walk the confidence-ranked ordering, author each
instance with codex, verify its truth table in docker, audit it with codex, and
finalize it into OUTPUT/<family>/.

The scheduler takes the highest-confidence candidate from the repo with the fewest
instances built or in flight, which spreads instances across repos.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import common, examples
from .common import CodexConfig


def load_ordering(family: str) -> list[dict]:
    path = common.ORDERING_DIR / f"ordering_{family}.jsonl"
    if not path.exists():
        raise SystemExit(f"no ordering file at {path}")
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _done_ids(family: str) -> set[str]:
    """Instances already finalized (output) or reserved by the fixed seeds."""
    done = {Path(p).stem for p in glob.glob(str(common.OUTPUT / family / "*.json"))}
    done |= {Path(p).stem for p in glob.glob(str(common.SEEDS / family / "*.json"))}
    return done


def next_candidate(remaining: list[dict], built: dict[str, int]) -> dict:
    """Least-built repo first, then highest confidence."""
    return min(
        remaining, key=lambda c: (built.get(c["repo"], 0), -c.get("confidence", 0))
    )


def stage(family: str, entry: dict, cfg: CodexConfig) -> Path:
    iid = entry["instance_id"]
    row = common.load_row(iid)
    short = row["repo"].split("/")[-1]
    wd = common.WORK / family / f"{short}__{iid[-12:]}"
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "source_row.json").write_text(json.dumps(row, indent=2))
    # The scout suggestion is a low-authority hint.
    (wd / "SUGGESTION.json").write_text(
        json.dumps(
            {
                "confidence": entry.get("confidence"),
                "suggestion": entry.get("suggestion", {}),
                "notes": entry.get("notes", ""),
            },
            indent=2,
        )
    )
    (wd / "EXAMPLES.md").write_text(
        examples.render_examples(
            family,
            row["repo"],
            row.get("repo_language", ""),
            entry.get("subsystem", ""),
        )
    )
    (wd / "SCHEMA.md").write_text(common.SCHEMA_MD.read_text())
    prompt = (common.PROMPTS / family / "author.md").read_text()
    (wd / "seed_template.json").write_text(
        json.dumps(
            {
                "instance_id": iid,
                "repo": row["repo"],
                "base_commit": row["base_commit"],
                "family": family,
                "runtime": {
                    "image_uri": common.image_for(iid),
                    "repo_language": row["repo_language"],
                    "before_repo_set_cmd": "<<HARNESS>>",
                    "selected_test_files_to_run": "<<AGENT: your new test files>>",
                    "run_script": "<<HARNESS>>",
                    "parser": "<<HARNESS>>",
                },
            },
            indent=2,
        )
    )
    common.clone_repo(row["repo"], row["base_commit"], wd / "repo")
    runner = common.detect_runner(wd)
    if runner in common.RUNNER_ID_NOTE:
        prompt += (
            f"\n\n## Test-id convention for THIS repo (runner: {runner})\n"
            f"{common.RUNNER_ID_NOTE[runner]}\n"
        )
    # Grading uses this instance's ground-truth run_script + parser, so the author
    # gets copies of both.
    gt = common.RUN_SCRIPTS / iid
    if (gt / "parser.py").exists():
        (wd / "GROUND_TRUTH_PARSER.py").write_text((gt / "parser.py").read_text())
    if (gt / "run_script.sh").exists():
        (wd / "GROUND_TRUTH_run_script.sh").write_text(
            (gt / "run_script.sh").read_text()
        )
    prompt += (
        "\n\n## CRITICAL — your tests are graded by THIS instance's real harness\n"
        "`runtime.run_script` and `runtime.parser` are the EXACT SWE-bench-Pro v2 "
        "scripts for this instance (copies in your workdir: "
        "`GROUND_TRUTH_run_script.sh`, `GROUND_TRUTH_PARSER.py`). Read both. Two "
        "hard requirements: (1) your new test files must actually be run by the "
        "run_script when passed via `runtime.selected_test_files_to_run`; (2) every "
        "`*_fail_to_pass` id MUST be byte-identical to the `name` the parser emits "
        "for that test (match how it builds the name exactly). A mismatch means 0 "
        "tests are found (harness_issue), not a pass.\n"
    )
    # Repo-specific notes (e.g. webclients workspace-relative test paths).
    if row["repo"] in common.REPO_ID_NOTE:
        prompt += (
            f"\n\n## CRITICAL — {row['repo']}-specific test conventions\n"
            f"{common.REPO_ID_NOTE[row['repo']]}\n"
        )
    (wd / "PROMPT.md").write_text(prompt)
    return wd


def author(wd: Path, cfg: CodexConfig) -> bool:
    common.run_codex(wd, (wd / "PROMPT.md").read_text(), cfg, "author_run.log")
    return (wd / "OUTPUT_seed.json").exists()


def correct(wd: Path, family: str, report: dict, cfg: CodexConfig) -> None:
    fails = [r for r in report["results"] if not r["ok"]]
    diag = "\n".join(
        f"- check '{r['name']}': expected {'PASS' if r['expected'] else 'FAIL'}, "
        f"got {'PASS' if r['actual'] else 'FAIL'} "
        f"({r['n_pass']}/{r['n_total']} target tests passed; patch apply={r['applied']})"
        for r in fails
    )
    feedback = (wd / "PROMPT.md").read_text() + (
        "\n\n## CORRECTION NEEDED\nYour previous ./OUTPUT_seed.json (still present) "
        "failed these verifier checks:\n" + diag + "\n\nEach expectation is fixed by "
        "the family truth table. Diagnose the cause and rewrite ./OUTPUT_seed.json so "
        "EVERY check matches. Keep the same schema and the test-id convention above."
    )
    common.run_codex(wd, feedback, cfg, "correct_run.log")


def audit(wd: Path, family: str, cfg: CodexConfig) -> dict:
    """Codex audits the instance for independence and the blind rule. A missing
    or unparseable verdict counts as a fail."""
    prompt = (common.PROMPTS / family / "audit.md").read_text()
    (wd / "AUDIT_verdict.json").unlink(missing_ok=True)
    common.run_codex(wd, prompt, cfg, "audit_run.log")
    vf = wd / "AUDIT_verdict.json"
    if not vf.exists():
        return {
            "pass": False,
            "verdict": "NO_VERDICT",
            "blind_ok": False,
            "rationale": "auditor wrote no verdict file",
        }
    try:
        v = json.loads(vf.read_text())
    except json.JSONDecodeError:
        return {
            "pass": False,
            "verdict": "BAD_JSON",
            "blind_ok": False,
            "rationale": "verdict not valid json",
        }
    verdict = str(v.get("independence_verdict", "")).upper()
    blind_ok = bool(v.get("blind_ok"))
    v["pass"] = (verdict == "INDEPENDENT_PAIR") and blind_ok
    v["verdict"] = verdict
    v["blind_ok"] = blind_ok
    return v


def _log(family: str, entry: dict) -> None:
    # The ledger is under outputs/, not scratch, so it accumulates across resumes.
    p = common.LEDGER_DIR / f"ledger_{family}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _process_one(
    family: str,
    c: dict,
    author_cfg: CodexConfig,
    audit_cfg: CodexConfig,
    max_correct: int,
) -> dict:
    """Author, verify, correct, audit and finalize one candidate. Returns its
    ledger record."""
    iid = c["instance_id"]
    rec = {
        "instance_id": iid,
        "repo": c["repo"],
        "confidence": c.get("confidence"),
        "ts": time.time(),
    }
    wd = None
    t0 = time.time()
    tag = f"[{family[:5]}|{c['repo'].split('/')[-1]}|{iid[-12:]}]"

    def p(msg: str) -> None:
        print(f"{tag} +{int(time.time() - t0):>4}s {msg}", flush=True)

    try:
        p("stage (clone repo)")
        wd = stage(family, c, author_cfg)
        p("author (codex)")
        if not author(wd, author_cfg):
            rec["status"] = "author_failed"
            return rec
        try:
            common.assemble(wd)
        except SystemExit as ex:
            rec["status"] = "no_harness"
            rec["detail"] = str(ex)[:120]
            return rec
        problems = common.validate(wd)
        if problems:
            rec["status"] = "invalid"
            rec["detail"] = problems[:4]
            return rec
        p("verify (docker truth table)")
        res = common.verify(wd)
        attempts = 0
        # Both seed_defect and harness_issue (usually wrong test ids) can be fixed
        # by re-authoring with the diagnostic; the verifier still gates soundness.
        while (
            not res["sound"]
            and res["triage"] in ("seed_defect", "harness_issue")
            and attempts < max_correct
        ):
            p(
                f"correct (codex, {res['triage']}) + re-verify [{attempts + 1}/{max_correct}]"
            )
            correct(wd, family, res["report"], author_cfg)
            try:
                common.assemble(wd)
            except SystemExit:
                break
            if common.validate(wd):
                break
            res = common.verify(wd)
            attempts += 1
        rec["triage"] = res["triage"]
        rec["correct_attempts"] = attempts
        if not res["sound"]:
            p(f"UNSOUND ({res['triage']})")
            rec["status"] = (
                "harness_issue" if res["triage"] == "harness_issue" else "unsound"
            )
            return rec
        p("sound -> audit (codex)")
        av = audit(wd, family, audit_cfg)
        rec["audit"] = {"verdict": av.get("verdict"), "blind_ok": av.get("blind_ok")}
        if not av["pass"]:
            rec["status"] = "audit_rejected"
            rec["detail"] = av.get("rationale", "")[:160]
            return rec
        common.finalize(wd, family)
        rec["status"] = "done"
    except Exception as ex:  # noqa: BLE001 — one instance must not kill the run
        rec["status"] = "error"
        rec["detail"] = repr(ex)[:200]
    finally:
        # Drop the instance's image and workdir so disk use stays bounded.
        common.cleanup_image(iid)
        if wd is not None and not os.environ.get("AUTHOR_KEEP_WORK"):
            shutil.rmtree(wd, ignore_errors=True)
    return rec


def run_family(
    family: str,
    author_cfg: CodexConfig,
    audit_cfg: CodexConfig,
    target: int,
    max_correct: int = 2,
    limit: int | None = None,
    concurrency: int = 1,
    repos: list[str] | None = None,
    ids: list[str] | None = None,
) -> None:
    """Author up to `target` finalized instances, `concurrency` at a time.

    Candidates are claimed least built+in-flight repo first, then highest
    confidence. `repos` and `ids` optionally restrict the candidates."""
    ordering = load_ordering(family)
    done = _done_ids(family)
    remaining = [e for e in ordering if e["instance_id"] not in done]
    if repos:
        remaining = [e for e in remaining if e["repo"] in repos]
    if ids:
        allow = set(ids)
        remaining = [e for e in remaining if e["instance_id"] in allow]

    lock = threading.Lock()
    built: dict[str, int] = {}
    inflight: dict[str, int] = {}
    for p in glob.glob(str(common.OUTPUT / family / "*.json")):
        try:
            built[json.load(open(p))["repo"]] = (
                built.get(json.load(open(p))["repo"], 0) + 1
            )
        except Exception:  # noqa: BLE001
            pass
    state = {"got": sum(built.values()), "attempted": 0}
    stop = threading.Event()

    print(f"[{family}] author: {author_cfg.describe()}")
    print(f"[{family}] audit:  {audit_cfg.describe()}")
    print(
        f"[{family}] target={target} concurrency={concurrency} "
        f"already-built={state['got']} candidates={len(remaining)}"
    )

    def claim() -> dict | None:
        with lock:
            if (
                stop.is_set()
                or state["got"] >= target
                or not remaining
                or (limit is not None and state["attempted"] >= limit)
            ):
                return None
            c = min(
                remaining,
                key=lambda x: (
                    built.get(x["repo"], 0) + inflight.get(x["repo"], 0),
                    -x.get("confidence", 0),
                ),
            )
            remaining.remove(c)
            inflight[c["repo"]] = inflight.get(c["repo"], 0) + 1
            state["attempted"] += 1
            return c

    def worker() -> None:
        while True:
            c = claim()
            if c is None:
                return
            rec = _process_one(family, c, author_cfg, audit_cfg, max_correct)
            with lock:
                inflight[c["repo"]] -= 1
                if rec["status"] == "done":
                    built[c["repo"]] = built.get(c["repo"], 0) + 1
                    state["got"] += 1
                    print(
                        f"[{family}] +1 ({state['got']}/{target})  {c['repo']}  "
                        f"{c['instance_id'][-12:]}  conf={c.get('confidence')}"
                    )
                    if state["got"] >= target:
                        stop.set()
                else:
                    print(
                        f"[{family}] x {rec['status']:14s} {c['repo']}  "
                        f"{c['instance_id'][-12:]}"
                    )
                _log(family, rec)

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        for f in [pool.submit(worker) for _ in range(max(1, concurrency))]:
            f.result()
    print(
        f"[{family}] DONE: built {state['got']}/{target} instances -> {common.OUTPUT / family}"
    )
