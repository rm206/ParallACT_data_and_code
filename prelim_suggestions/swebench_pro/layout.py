"""Filesystem layout for the prelim stage.

Kept, under $PRELIM_OUTPUTS (default prelim_suggestions/outputs/):
    rows/<instance_id>.json              one dataset row (re-downloadable)
    candidates.jsonl                     the pinned draw (grows with --target)
    assessments/<model_slug>/<id>.json   one completed exploration
    ordering_{contradictory,complementary}.jsonl
    logs/

Scratch, under $PRELIM_TMP (default <repo>/.local/prelim), deleted as the run
proceeds; the agent only reads here:
    mirrors/<repo_slug>.git              bare mirror per repo
    checkouts/<instance_id>/             working tree at base_commit
"""

from __future__ import annotations

import os
from pathlib import Path

# <repo>/prelim_suggestions/swebench_pro
BASE = Path(__file__).resolve().parent
# <repo>/prelim_suggestions
PKG_ROOT = BASE.parent

OUTPUTS = Path(os.environ.get("PRELIM_OUTPUTS", PKG_ROOT / "outputs")).resolve()
ROWS_DIR = OUTPUTS / "rows"
CANDIDATES = OUTPUTS / "candidates.jsonl"
ASSESS_DIR = OUTPUTS / "assessments"
LOGS_DIR = OUTPUTS / "logs"
PROMPTS_DIR = PKG_ROOT / "prompts"

TMP_ROOT = Path(
    os.environ.get("PRELIM_TMP", PKG_ROOT.parent / ".local" / "prelim")
).resolve()
MIRRORS_DIR = TMP_ROOT / "mirrors"
CHECKOUTS_DIR = TMP_ROOT / "checkouts"


def model_slug(model: str) -> str:
    """Filesystem-safe folder name for a model id (assessments/<slug>)."""
    return model.replace("/", "__").strip()


def repo_slug(repo: str) -> str:
    """Filesystem-safe name for an "owner/name" repo id."""
    return repo.replace("/", "__").strip()


def assess_dir(model: str) -> Path:
    return ASSESS_DIR / model_slug(model)


def ordering_path(family: str) -> Path:
    return OUTPUTS / f"ordering_{family}.jsonl"


def ensure_persistent_dirs() -> None:
    for d in (ROWS_DIR, ASSESS_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def ensure_tmp_dirs() -> None:
    for d in (MIRRORS_DIR, CHECKOUTS_DIR):
        d.mkdir(parents=True, exist_ok=True)
