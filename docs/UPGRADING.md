# Upgrade without replacing a frozen run

1.0.0 adds explicit delivery choices, lineage reporting, completed branch publication, affinity visibility and cache/container safeguards on top of the 0.7 supervisor. Discovery parameters, branch dependencies and exact/RC same-class library merging remain unchanged. Frozen runs still require their original source. Use new run IDs for new computation; use `report` or `reevaluate` to examine completed exports without a new freeze.

## Existing completed Arabidopsis run

Keep v022 production outputs, the 0.3.0 candidate review and the 0.3.1 boundary review with their original sources/configurations. Their results do not need recomputation for the GitHub engineering release. Installation smoke tests and the small synthetic fixture are the appropriate next acceptance, not another full EDTA run.

For the existing server, preserve the completed 0.6 run and use a separate extracted candidate directory with the already installed engine:

```bash
TASK_ROOT=/home/cfy/te_project
TE_ENV="$TASK_ROOT/envs"
TE_REPO="$TASK_ROOT/TEflow-1.0.0"
export MICROMAMBA=/home/cfy/minimamba/bin/micromamba
cd "$TE_REPO"
export TEFLOW_REPOSITORY="$TE_REPO"
export PYTHONPATH="$TE_REPO/src"
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow --version
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow capabilities
# Small synthetic input + real Snakemake + mocked upstream tools; no genome annotation.
"$MICROMAMBA" run -p "$TE_ENV/engine" python scripts/accept_release.py --root "$TASK_ROOT"
```

Do not set `PYTHONPATH` to the new source while trying to resume old runs. Use the original version's `scripts/run_server.sh`, which explicitly selects that version. A source path override is an advanced option; an installed wheel normally needs neither environment variable. `teflow assets` shows which recipes are active.

## A future new run with the same settings

```bash
python -m teflow fork-config \
  --config "$TASK_ROOT/at_compare_v022.local.json" \
  --output "$TASK_ROOT/at_next.local.json" --run-id at_next
python -m teflow plan --config "$TASK_ROOT/at_next.local.json"
```

This preserves all branch parameters, input/database paths and hashes, upstream tool versions, resource budgets, QC and optional evaluation settings. Only recognized wrapper script paths are rebound, and Bash is made explicit for the TEtrimmer shell wrapper. Custom adapters are retained. A `.fork.json` sidecar records changes and source hash. It copies no completed analysis and does not run tools.

Review the new plan and perform `check` before the first `run --dry-run`. Stage import remains explicit and validates compatibility; not every old stage can be imported into every new version. Do not edit receipts to force import. The new read-only `audit-results` and independent `reevaluate` commands accept old config paths without attempting to resume old production stages. They need the relevant existing source/export files.

Add `--parallel-branches --jobs 2 --io-slots 2` to init/fork-config to opt into one-species branch scheduling. Optional `--stage-resources FILE.json` overrides resource requests; `--all-interspersed` requests an additional Unknown-inclusive FASTA. Existing settings are retained unless one of these options explicitly changes them. See [server commands](SERVER_v1.0_zh.md).

## Version policy

- Patch releases fix behavior within declared contracts; frozen runs still require exact original source.
- Minor releases add commands/features and may add explicit migrations; defaults must be documented.
- Configuration schema changes require a versioned migration and tests rejecting incompatible inputs.
- Tool upgrades require separate dependency/adapter validation, small execution tests and a recorded genome validation scope before a claim of production validation.

Maintainers preserve `run_manifest`, receipt integrity, raw alignment provenance and per-branch exports across upgrades. “CLI compatible” does not mean an old source fingerprint is interchangeable with a new one.
