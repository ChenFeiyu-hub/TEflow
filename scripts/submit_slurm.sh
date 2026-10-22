#!/usr/bin/env bash
# One node allocation; Snakemake serializes heavy steps inside it. No executor plugin needed.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
export TEFLOW_REPOSITORY="$repo"
export PYTHONPATH="$repo/src${PYTHONPATH:+:$PYTHONPATH}"
config=$(realpath "${1:?Usage: bash scripts/submit_slurm.sh CONFIG TIME_LIMIT [PARTITION] [--resume]}")
time_limit=${2:?Supply the site-permitted time limit, e.g. 2-00:00:00}
partition=${3:-}
runmode=${4:-run}
[[ "$runmode" == run || "$runmode" == --resume ]] || { echo "Unknown run mode" >&2; exit 2; }
cores=$(python -m teflow settings --config "$config" --key threads)
mem=$(python -m teflow settings --config "$config" --key mem_mb)
runroot=$(python -m teflow settings --config "$config" --key run_root)
mkdir -p "$runroot/scheduler_logs"
args=(--job-name=teflow --nodes=1 --ntasks=1 --cpus-per-task="$cores" --mem="${mem}M" --time="$time_limit" --output="$runroot/scheduler_logs/%j.log" --export=ALL)
[[ -z "$partition" ]] || args+=(--partition="$partition")
# Arguments are passed to sbatch directly; no shell-built --wrap command.
sbatch "${args[@]}" "$repo/scripts/run_server.sh" "$config" "$runmode"
