#!/usr/bin/env bash
# Incident-specific repair for at_pilot_v01. Never launches genome discovery.
# 2026-10-10 fix1: preserve other builds without freezing the pandas target.
# 2026-10-10 fix2: allow both timezone dependencies required by pandas 2.3.3.
set -euo pipefail
task=${1:?Usage: bash scripts/repair_edta_pandas.sh /home/cfy/te_project [--solve-only|--apply]}
mode=${2:---solve-only}
[[ "$mode" == --solve-only || "$mode" == --apply ]] || { echo "Unknown mode: $mode" >&2; exit 2; }
[[ $(uname -s) == Linux ]] || { echo "Run this repair on the Linux server." >&2; exit 2; }
task=$(realpath "$task")
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
mamba=${MICROMAMBA:-/home/cfy/minimamba/bin/micromamba}
envroot="$task/envs"
oldconfig="$task/at_pilot.local.json"
newconfig="$task/at_pilot_v02.local.json"
newlocks="$task/env-locks/at_pilot_v02"
[[ -x "$mamba" && -f "$oldconfig" && -d "$envroot/locks" ]] || { echo "Missing micromamba, original config, or environment locks." >&2; exit 2; }
[[ -d "$envroot/engine/conda-meta" && -d "$envroot/edta/conda-meta" ]] || { echo "Existing engine and EDTA environments are required." >&2; exit 2; }
if [[ "$mode" == --apply ]]; then
  [[ ! -e "$newconfig" && ! -e "$newlocks" && ! -e "$task/work/at_pilot_v02" && ! -e "$task/results/at_pilot_v02" ]] || {
    echo "v02 config/work/lock paths already exist. Preserve them and inspect the previous repair log." >&2; exit 2;
  }
  command -v pgrep >/dev/null || { echo "pgrep is required to check active tasks." >&2; exit 2; }
  if pgrep -u "$(id -u)" -f 'EDTA[.]pl|TIR-Learner[.]py|[p]ython.*-m teflow (stage|doctor)' >/dev/null; then
    echo "An EDTA/TIR-Learner/teflow task is still running for this user; do not modify its environment." >&2; exit 2
  fi
fi
attempt="$(date -u +%Y%m%dT%H%M%SZ)-$$"
logdir="$task/repair_logs/edta-pandas-$attempt"
mkdir -p "$logdir"
exec > >(tee "$logdir/repair.log") 2>&1
trap 'printf "Repair stopped at line %s. Logs: %s\n" "$LINENO" "$logdir" >&2' ERR
printf 'Repair mode: %s\nLogs: %s\n' "$mode" "$logdir"

# Preserve exact package specifications before changing this existing environment.
cp -p "$oldconfig" "$logdir/at_pilot_v01.original.json"
cp -a "$envroot/locks" "$logdir/original_locks"
"$mamba" list -p "$envroot/edta" --explicit > "$logdir/edta.before.explicit.txt"
"$mamba" run -p "$envroot/engine" python -m pip freeze --all > "$logdir/engine.before.pip.txt"
"$mamba" run -p "$envroot/engine" python - "$envroot/edta" "$oldconfig" <<'PY'
import json, sys
from pathlib import Path
prefix, config = map(Path, sys.argv[1:])
records = [json.loads(p.read_text()) for p in (prefix / 'conda-meta').glob('*.json')]
versions = {r['name']: r['version'] for r in records}
for name, expected in [('edta', '2.3.0'), ('tir-learner', '3.0.7')]:
    if versions.get(name) != expected:
        raise SystemExit(f'Unexpected {name} version: {versions.get(name)}; this repair is for {expected}')
if json.loads(config.read_text())['run_id'] != 'at_pilot_v01':
    raise SystemExit('Original configuration is not at_pilot_v01')
print(json.dumps({k: versions.get(k) for k in ('edta', 'tir-learner', 'pandas', 'python')}))
PY

# Freeze installed includes the package being downgraded. Instead, constrain
# every other installed package explicitly and leave only pandas replaceable.
"$mamba" run -p "$envroot/engine" python - "$envroot/edta" "$logdir/keep-installed-except-pandas.txt" <<'PY'
import json, sys
from pathlib import Path
prefix, target = map(Path, sys.argv[1:])
specs = []
for path in sorted((prefix / 'conda-meta').glob('*.json')):
    record = json.loads(path.read_text())
    if record['name'] == 'pandas':
        continue
    build = record.get('build') or record.get('build_string')
    if not build:
        raise SystemExit('Missing package build: ' + str(path))
    specs.append(f"{record['name']}={record['version']}={build}")
if not specs:
    raise SystemExit('No installed package constraints found')
target.write_text('\n'.join(specs) + '\n')
print('Preserved non-pandas package builds:', len(specs))
PY
install_args=(install -p "$envroot/edta" --strict-channel-priority
              --override-channels -c conda-forge -c bioconda
              --file "$logdir/keep-installed-except-pandas.txt" pandas=2.3.3)
if "$mamba" "${install_args[@]}" --dry-run --json > "$logdir/solve.json"; then
  :
else
  solver_status=$?
  cat "$logdir/solve.json"
  printf 'Solver failed before installation (exit %s). Logs: %s\n' "$solver_status" "$logdir" >&2
  exit "$solver_status"
fi
"$mamba" run -p "$envroot/engine" python - "$logdir/solve.json" <<'PY'
import json, sys
from pathlib import Path
plan = json.loads(Path(sys.argv[1]).read_text())
if plan.get('success') is not True:
    raise SystemExit('Environment solver did not return success; inspect solve.json')
actions = plan.get('actions', {})
changed = {r['name'] for key in ('LINK', 'UNLINK') for r in actions.get(key, [])}
# pandas 2.3.3 declares both pytz and python-tzdata as required dependencies.
unexpected = changed - {'pandas', 'pytz', 'python-tzdata'}
if unexpected:
    raise SystemExit('Unexpected package changes; no installation performed: ' + ', '.join(sorted(unexpected)))
print('Planned changes:', ', '.join(sorted(changed)) or 'already satisfied')
PY
if [[ "$mode" == --solve-only ]]; then
  echo "Solver check passed. No environment/config/workflow change was applied."
  exit 0
fi

"$mamba" "${install_args[@]}" -y
"$mamba" run -p "$envroot/edta" python "$repo/src/teflow/tirlearner_probe.py"
"$mamba" run -p "$envroot/edta" python -c 'import pandas; assert pandas.__version__ == "2.3.3", pandas.__version__'
"$mamba" run -p "$envroot/engine" python -m pip install --no-deps --no-build-isolation --force-reinstall "$repo"
"$mamba" run -p "$envroot/engine" teflow --version

# Keep the v01 config and original lock files unchanged. v02 gets its own snapshot.
mkdir -p "$newlocks"
cp -a "$envroot/locks/." "$newlocks/"
"$mamba" list -p "$envroot/edta" --explicit > "$newlocks/edta.linux-64.explicit.txt"
"$mamba" run -p "$envroot/engine" python -m pip freeze --all > "$newlocks/engine.pip.freeze.txt"
"$mamba" run -p "$envroot/engine" python - "$oldconfig" "$newconfig" <<'PY'
import json, sys
from pathlib import Path
c = json.loads(Path(sys.argv[1]).read_text())
c['run_id'] = 'at_pilot_v02'
c['description'] = 'Fresh pilot after TIR-Learner 3.0.7 / pandas 3.0.6 indexing failure; pandas pinned to 2.3.3. v01 outputs are preserved and not imported.'
with Path(sys.argv[2]).open('x') as out:
    json.dump(c, out, indent=2)
    out.write('\n')
PY
tesorter_db=$(
  "$mamba" run -p "$envroot/edta" python -c \
    'from pathlib import Path; import TEsorter; print(Path(TEsorter.__file__).resolve().parent / "database")'
)
"$mamba" run -p "$envroot/engine" teflow lock-databases \
  --config "$newconfig" \
  --pfam-dir "$task/databases/pfam37" \
  --classification-dir "$task/databases/dfam40" \
  --extra-dir "$envroot/edta/share/EDTA/database" \
  --extra-dir "$tesorter_db" \
  --extra-dir "$newlocks"
"$mamba" run -p "$envroot/engine" teflow validate-inputs \
  --config "$newconfig" --output "$logdir/server_input_audit_v02.json"
"$mamba" run -p "$envroot/engine" bash "$repo/scripts/run_server.sh" "$newconfig" --dry-run
printf '%s\n' "$newconfig" > "$task/at_pilot_v02.dry_run_passed"
printf 'REPAIR AND DRY-RUN PASSED. No genome analysis was launched.\nConfig: %s\nRepository: %s\n' "$newconfig" "$repo"
