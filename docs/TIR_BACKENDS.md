# EDTA TIR backends — 1.1.0rc1

New projects select **TIR-Learner 4.08 on CPU**. TIR-Learner 3.0.7 remains an explicit fallback. This is a version-policy choice supported by successful TAIR10 execution, not a claim that either version is biological truth.

## Installation and selection

EDTA 2.3.0 stays in `envs/edta`, with its existing v3/pandas dependencies. v4 lives in `envs/tirlearner4-cpu`. The default bootstrap installs both. `bootstrap_server.sh ENV_ROOT --tir-learner v3` installs the legacy baseline only; `--only tirlearner4-cpu` installs just the additional CPU environment. Existing environments are never overwritten.

The CPU recipe pins `tir-learner=4.08`, Python 3.11 and a CPU PyTorch build. Transitive packages are resolved and recorded in the explicit environment lock; the recipe is not an assertion that every fresh solve reproduces the tested server build. `teflow check` executes the installed CNN on artificial input and verifies CPU tensors, shape and finite output. It does not evaluate sensitivity or precision. The upstream v4.08 CLI prints an inconsistent `v1.0` banner, so the adapter checks Conda package metadata rather than trusting that banner.

```bash
# New projects: v4-cpu is already the default.
teflow init --root /data/te_project --genome /data/genome.fa \
  --sample-id my_species --run-id run_v4 --profile edta \
  --tir-learner v4-cpu --tir-env /data/te_project/envs/tirlearner4-cpu

# Change an existing project by making a new configuration/run.
teflow fork-config --config /data/te_project/old.local.json \
  --output /data/te_project/run_v4.local.json --run-id run_v4 \
  --tir-learner v4-cpu --tir-env /data/te_project/envs/tirlearner4-cpu

# Explicit fallback; no automatic retry with another algorithm.
teflow fork-config --config /data/te_project/run_v4.local.json \
  --output /data/te_project/run_v3.local.json --run-id run_v3 --tir-learner v3
```

`init-server` accepts the same options. `fork-config` and `migrate-config` preserve the prior selection unless `--tir-learner` is specified. Old configurations without `tools.edta.tir_learner` continue to mean v3; loading them does not insert a new default or change their scientific identity. `--tir-env` on a fork/migration requires `--tir-learner v4-cpu` explicitly. `plan`, doctor and EDTA completion details display the selection.

## Isolation and reproducibility

The EDTA tool command remains the declared `micromamba run -p EDTA_ENV EDTA.pl`. For v4, TEflow constructs an effective command through the packaged `run_edta.py` adapter. That adapter locates the actual EDTA Perl source using the installed package inventory, then creates a private `TIR-Learner` shim under the current working directory. This avoids the EDTA raw-dispatcher symlink problem without editing installed files.

Only that shim dispatches into v4. It uses the absolute v4 executable, clears GPU visibility and inherited Python path settings, and forwards EDTA arguments unchanged. EDTA's Perl, RepeatMasker, RepeatModeler, BLAST and TEsorter stay in the EDTA environment. Child processes stay inside the workflow-owned process group, CPU affinity and monitoring context. No GPU adapter, detached helper, system-wide symlink or automatic v3 fallback is introduced.

Selected backend, prefix and version participate in stage identity. The existing internal freeze includes v4 package metadata, source files and model. A v3 EDTA result cannot be imported as v4 merely because its genome matches. A new run is required when changing versions. There is no manual source/upload SHA-256 step.

## Evidence and open audit

The prior experiment completed both full TAIR10 EDTA runs and uniform RepeatMasker, with an actual v4 CPU discovery call. Its total genomic hit union was essentially unchanged, but type and location differences were material. This supports execution compatibility, not cross-species accuracy.

The hAT review found a concrete upstream rule needing clarification: v4.08's TSD motif table assigns a `TA` check to DTA. In the supplied TAIR10 results, 6/57 v3 hAT records and 7/7 v4 hAT records have reported TSDs beginning with `TA`. This is a diagnostic clue, not a validated causal attribution. See the [dated upstream audit](UPSTREAM_TIR4_AUDIT_2026-11-08.md). v4 remains the chosen default; the wrapper does not patch that rule or tune thresholds to reproduce v3 counts.

Successful production v4 stages retain `tir_audit.json`, `tir_native_sites.tsv`, native FASTA/extended annotation and actual bridge-call receipts. The raw 15-column annotation is not advertised as standard GFF3. Six integer CNN scores are retained in their upstream scale, with no calibration claim. Duplicate native sites are reported, not silently removed. Standard final EDTA exports remain separately checked.

For existing intermediate files, use `scripts/audit_tir_checkpoints.py`. It reads the four documented pre/post checkpoints, excludes TSD lengths and restores chunk offsets according to v4.08's formatter. It reports exact/overlapping intervals and an explicitly descriptive 80% reciprocal-overlap count. Missing, oversized or malformed files remain unavailable, not zero calls. Pre/post differences cannot distinguish CNN rejection from TIR/TSD filtering because the stored post-checkpoints contain only passers.

## Extension contract

The backend registry is in `tir_backend.py`; process dispatch is in `edta_entry.py`; native output contracts are in `tir_audit.py`; optional checkpoint inspection is in `tir_checkpoints.py`. Scheduler and branch resource policies are unchanged. A future backend needs a new explicit version/recipe, command and output contract, CPU-model probe, and tests for failure propagation and historical-config preservation. Never infer a new algorithm from the ambient PATH or automatically reinterpret an old frozen run.

See [server handoff](SERVER_TIR4_v1.1_zh.md) and [validation status](TEST_STATUS_v1.1.md).
