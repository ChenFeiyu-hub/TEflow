#!/usr/bin/env bash
# Bounded candidate QC; intentionally independent of run_server.sh/Snakemake.
set -Eeuo pipefail
trap 'code=$?; printf "Candidate review stopped at line %s (exit %s). Preserve the review directory and logs.\n" "$LINENO" "$code" >&2; exit "$code"' ERR
if (( $# < 3 || $# > 4 )); then
  printf 'Usage: bash scripts/run_candidate_review.sh OLD_CONFIG NEW_REVIEW_DIR FAMILY_IDS [THREADS]\n' >&2
  exit 2
fi
CONFIG="$1"
REVIEW="$2"
FAMILIES="$3"
THREADS="${4:-8}"
TEFLOW_REPOSITORY="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
export TEFLOW_REPOSITORY
export PYTHONPATH="$TEFLOW_REPOSITORY/src${PYTHONPATH:+:$PYTHONPATH}"
PYTHON_BIN="${PYTHON_BIN:-python}"
SAMPLE_ID="${TEFLOW_REVIEW_SAMPLE:-arabidopsis_TAIR10}"
BRANCH="${TEFLOW_REVIEW_BRANCH:-edta_plus_heliano}"
if [[ -e "$REVIEW" ]]; then
  printf 'Review directory already exists: %s\nUse a new directory; do not remove prior evidence.\n' "$REVIEW" >&2
  exit 2
fi
"$PYTHON_BIN" -m teflow review-prepare --config "$CONFIG" --sample "$SAMPLE_ID" --branch "$BRANCH" \
  --families "$FAMILIES" --output "$REVIEW" --max-loci 10 --flank 500
"$PYTHON_BIN" -m teflow review-plan --review "$REVIEW" --threads "$THREADS" > "$REVIEW/protein_plan.json"
"$PYTHON_BIN" -m teflow review-run --review "$REVIEW" --threads "$THREADS" --timeout 21600
"$PYTHON_BIN" -m teflow review-pack --review "$REVIEW" --output "${REVIEW}.feedback.tar.gz"
printf 'CANDIDATE_REVIEW_COMPLETED\nReview: %s\nFeedback: %s.feedback.tar.gz\n' "$REVIEW" "$REVIEW"
