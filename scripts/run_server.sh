#!/usr/bin/env bash
# Compatibility entry. All launch policy lives in teflow.launcher.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
export TEFLOW_REPOSITORY="$repo"
if [[ -d "$repo/src" ]]; then
  export PYTHONPATH="$repo/src${PYTHONPATH:+:$PYTHONPATH}"
fi
config=${1:?Usage: bash scripts/run_server.sh CONFIG [--dry-run | --resume] [--target-stage STAGE]}
shift
if [[ ${1:-} == run ]]; then shift; fi
exec python -m teflow run --config "$config" "$@"
