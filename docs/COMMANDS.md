# Command interface v2 (1.0.0)

The installed console entry `teflow` and `python -m teflow` are equivalent. JSON is the default for structured results; scheduler logs stream during `run`. `--help` is authoritative for arguments.

| Task | Command | Effects |
|---|---|---|
| Inspect supported branches | `teflow capabilities` | Read only; reports validation scope, not accuracy |
| Locate bundled recipes | `teflow assets [--path workflow/Snakefile]` | Read only; one path or JSON inventory |
| Create generic project | `teflow init --root ROOT --genome FASTA --sample-id ID --run-id RUN` | New configuration only; refuses existing config/run directories |
| Inspect dependency graph | `teflow plan --config CONFIG` | Read only; no tool invocation |
| Preview work/reuse scope | `teflow run-preview --config CONFIG [--target-stage STAGE]` | Metadata-only; a fork imports no outputs; actual reuse is verified by run |
| Audit input only | `teflow validate-inputs --config CONFIG --output AUDIT` | Input reads and audit report |
| Audit input and installation | `teflow check --config CONFIG` | Attempts in `work/RUN/checks/`; no freeze or genome discovery |
| Weaker version check | `teflow check --config CONFIG --versions-only` | Does not establish dependency acceptance |
| Check scheduler DAG | `teflow run --config CONFIG --dry-run` | Freeze, probes, scheduler dry-run |
| Execute | `teflow run --config CONFIG` | Freeze, probes and production DAG |
| Resume | `teflow run --config CONFIG --resume` | Same immutable run; no forced unlock or changed settings |
| Limit requested target | Add `--target-stage export_heliano` | Target and its dependencies; disabled targets rejected |
| Inspect completed outputs | `teflow status --config CONFIG` | Receipt existence/metadata and runtime observations; no full content scan |
| Request cancellation | `teflow cancel --config CONFIG` | One live supervised attempt; no saved PID signals; wait for cancelled and empty leases |
| Inspect log tails | `teflow logs --config CONFIG [--stage STAGE] [--sample ID] [--lines 40]` | Latest scheduler or stage logs, at most 128 KiB per file |
| Inspect resource evidence | `teflow runtime-summary --config CONFIG` | Sample counts, quality, peak sampled RSS and observed stage overlap |
| Choose a downstream delivery | `teflow select --config CONFIG --branch BRANCH --policy te_primary --output NEW_DIRECTORY [--mode copy]` | Explicit choice; verified complete branch only; no upstream runs or source mutation |
| Write run report | `teflow report --config CONFIG --output NEW_DIRECTORY` | Markdown/JSON/TSV snapshot; outside original run, no external tools |
| Package diagnostics | `teflow pack-feedback --config CONFIG --output FILE.tar.gz` | Bounded feedback archive; refuses overwrite |
| Prepare an upgrade | `teflow fork-config --config OLD --output NEW --run-id NEW_RUN` | Preserves settings, rebinds known wrapper paths, writes provenance sidecar |
| Enable branch concurrency | Add `--parallel-branches --jobs 2 --io-slots 2` to init/fork-config | One species only; stage requests, distinct CPU IDs, memory observation |
| Inspect runtime leases | `teflow runtime-status --config CONFIG` | Read owner identity, reservations and sampled RSS |
| Reconcile dead leases | `teflow runtime-reconcile --config CONFIG` | Remove only proven dead/quiescent records; no process signals |
| Audit raw existing results | `teflow audit-results --config OLD --output NEW.json` | Vocabulary and consensus-coordinate diagnostics; no tools |
| Reevaluate existing exports | `teflow reevaluate --config OLD --output NEW_DIRECTORY` | Independent genome-wide evaluation; no original mutation or genome annotation |

`--dry-run` and `--resume` are mutually exclusive. Receipts in `work/RUN/launches/ID.json` record preflight through terminal status; `launches/ID/scheduler.log` is persisted and streamed. A supervisor keeps the controller lock while Snakemake runs. Normal success exits 0; scheduler/cleanup failure exits 1; configuration/preflight errors normally exit 2; completed cooperative cancellation exits 130. Stage receipts and overall artifact status remain separate from a successful targeted run. `cancel` returning 0 means request submitted, not cleanup complete. Absence of an error in log tails is not proof of success.

Cancellation is cooperative. External commands notice the attempt request and clean their own groups; pure Python stages/large input scans may finish before cancellation is acknowledged. Do not kill processes by username/name or clear pool files. A crashed launcher, changed-host record or pre-0.7 run requires inspection; `cancel` will refuse it. `runtime-reconcile` never signals processes or clears stage locks. There is no automatic restart/adoption or hard cancellation deadline.

Legacy `init-server`, `migrate-config`, `freeze`, `doctor`, `stage`, `targets`, `import-stage`, `unlock-stage`, `settings` and the review commands remain available. `migrate-config` selects a preset and may reset branch/QC/evaluation settings; use `fork-config` to preserve a customized configuration. Commands do not implicitly download databases, install missing tools, launch a background process or migrate frozen runs.

Current target names include `export_edta`, `export_edta_tetrimmer`, `export_heliano`, `export_hite`, `export_edta_plus_heliano`, and final `export`. Only names in `plan.dependencies` are valid for a configuration. A targeted run can be complete for that branch while overall `status` remains incomplete until final export.

Core JSON configuration schemas remain 1/2. CLI `capabilities.interface_version=2` identifies this command-contract generation; it is not an export-table or configuration schema version. Existing advanced Python module functions are internal, not a promised stable SDK.
