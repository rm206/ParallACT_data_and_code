#!/usr/bin/env bash
# Instance authoring launcher.
#
#   ./run_authoring.sh <contradictory|complementary> <target> [concurrency]
#   ./run_authoring.sh contradictory 1          # try it: author 1 sound instance
#   ./run_authoring.sh contradictory 5
#   CONCURRENCY=2 ./run_authoring.sh contradictory 35
#
# Inline loop: codex authors -> docker verifies the truth table -> codex corrects
# -> codex audits -> finalize. Needs: codex, docker, python3, git.
#
# Persisted -> ./outputs/ (generated/<family>/<id>.json, ledger_<family>.jsonl).
# Scratch   -> <repo>/.local/author (AUTHOR_SCRATCH; repo clones + verify I/O),
#   deleted as the run proceeds. Resumable: finalized instances in outputs/ are
#   skipped, so rerun the same command to continue.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; cd "$HERE"

FAMILY="${1:?usage: $0 <contradictory|complementary> <target> [concurrency]}"
TARGET="${2:?usage: $0 <family> <target> [concurrency]}"
CONCURRENCY="${3:-${CONCURRENCY:-1}}"
MODEL="${AUTHOR_MODEL:-gpt-5.6-sol}"
REASONING="${AUTHOR_REASONING:-medium}"
CODEX_BIN="${AUTHOR_CODEX:-codex}"   # codex binary (or path) for author + audit

PY="${PYTHON:-python3}"
command -v docker >/dev/null || { echo "FATAL: docker not on PATH" >&2; exit 2; }
docker info >/dev/null 2>&1 || { echo "FATAL: docker daemon not running" >&2; exit 2; }
command -v codex  >/dev/null || { echo "FATAL: codex not on PATH" >&2; exit 2; }
command -v git    >/dev/null || { echo "FATAL: git not on PATH" >&2; exit 2; }

echo "family=$FAMILY target=$TARGET concurrency=$CONCURRENCY"
echo "codex=$CODEX_BIN model=$MODEL reasoning=$REASONING"
echo "scratch=${AUTHOR_SCRATCH:-$(cd "$HERE/.." && pwd)/.local/author}  outputs=$HERE/outputs"

# LIMIT caps attempts this run; AUTHOR_KEEP_WORK=1 keeps per-instance workdirs.
LIMIT_ARG=(); [ -n "${LIMIT:-}" ] && LIMIT_ARG=(--limit "$LIMIT")

exec "$PY" -m "authoring.author_${FAMILY}" \
  --target "$TARGET" --concurrency "$CONCURRENCY" "${LIMIT_ARG[@]}" \
  --author-codex "$CODEX_BIN" --audit-codex "$CODEX_BIN" \
  --model "$MODEL" --reasoning "$REASONING"
