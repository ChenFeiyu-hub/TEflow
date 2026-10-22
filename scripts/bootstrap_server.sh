#!/usr/bin/env bash
# Deliberately server-only and opt-in. No genome computation occurs here.
set -euo pipefail
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
prefix=${1:?Usage: bash scripts/bootstrap_server.sh /absolute/env-root [--solve-only] [--only engine|edta|tetrimmer|masking|heliano|qc]}
shift
mode=install
names=(engine edta tetrimmer masking)
while (( $# )); do
  case "$1" in
    --solve-only) mode=--solve-only; shift ;;
    --only)
      [[ $# -ge 2 ]] || { echo "--only requires an environment name" >&2; exit 2; }
      case "$2" in engine|edta|tetrimmer|masking|heliano|qc) names=("$2") ;; *) echo "Unknown environment: $2" >&2; exit 2 ;; esac
      shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
mamba=${MICROMAMBA:-micromamba}
[[ $(uname -s) == Linux ]] || { echo "Linux server required" >&2; exit 2; }
[[ "$prefix" == /* && "$prefix" != *" "* ]] || { echo "Use an absolute prefix without spaces" >&2; exit 2; }
command -v "$mamba" >/dev/null || { echo "MICROMAMBA executable not found: $mamba" >&2; exit 2; }
prefix=${prefix%/}
[[ -n "$prefix" ]] || { echo "Do not use / as an environment root" >&2; exit 2; }
attempt="$(date -u +%Y%m%dT%H%M%SZ)-$$"
logdir="$prefix/install_logs/$attempt"
mkdir -p "$logdir" "$prefix/locks"
printf '%s\n' "Installation/solver logs: $logdir"
for name in "${names[@]}"; do
  args=(create -y --strict-channel-priority --override-channels -c conda-forge)
  [[ "$name" != heliano ]] || args=(create -y --strict-channel-priority --override-channels -c zhenlisme -c conda-forge)
  [[ "$name" == engine ]] || args+=(-c bioconda)
  target="$prefix/$name"
  if [[ "$mode" == --solve-only ]]; then
    args+=(--dry-run)
    # Solve a fresh target even when an older environment already exists.
    target="$prefix/.solve-only-$attempt/$name"
  elif [[ -d "$prefix/$name/conda-meta" ]]; then
    echo "Environment already exists: $prefix/$name; preserve it and select a new env root." >&2
    exit 2
  fi
  "$mamba" "${args[@]}" -p "$target" -f "$repo/envs/$name.yml" 2>&1 | tee "$logdir/$name.log"
  if [[ "$mode" == install ]]; then
    if [[ "$name" == tetrimmer ]]; then
      "$mamba" run -p "$prefix/tetrimmer" python "$repo/scripts/install_tetrimmer_sources.py" \
        --prefix "$prefix/tetrimmer" --cache "$prefix/source_cache" 2>&1 | tee "$logdir/tetrimmer.sources.log"
      cp "$prefix/tetrimmer/share/teflow-vendor/sources.lock.json" "$prefix/locks/tetrimmer.sources.lock.json"
    fi
    if [[ "$name" == engine ]]; then
      "$mamba" run -p "$prefix/engine" python -m pip install --no-deps "$repo" 2>&1 | tee "$logdir/engine.workflow.log"
      "$mamba" run -p "$prefix/engine" python -m pip freeze --all > "$prefix/locks/engine.pip.freeze.txt"
    fi
    "$mamba" list -p "$prefix/$name" --explicit > "$prefix/locks/$name.linux-64.explicit.txt"
  fi
done
if [[ "$mode" == install ]]; then
  printf '%s\n' "Selected environments installed. Configure and lock databases before production; see docs/INSTALL.md."
else
  printf '%s\n' "Selected Conda runtime specs solved only. Sources, pip packages, databases, and tool execution were NOT tested."
fi
