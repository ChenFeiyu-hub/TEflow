# TEflow 1.0 release scope

1.0 is the single-species public interface milestone. It retains the existing discovery tools, scientific parameters, library folding and masking defaults. It is not a certification of best accuracy, multi-species scheduling or days-long hard-limited execution.

Compared with 0.7.0rc1:

- `select` makes an explicit branch/masking choice reviewable and portable without modifying old results.
- Reports add unique E-parent retention and optional genomic union coverage of missing ET parents.
- Branch exports publish completed directories; interrupted directories remain diagnostic artifacts, never completed branch results.
- Plans/previews expose inherited CPU IDs and the chosen pool; separate roots still require operator/scheduler coordination.
- The HiTE wrapper explicitly binds the supplied temporary directory to `/tmp` and sets TMPDIR/TMP/TEMP despite `--cleanenv`, following [Apptainer environment controls](https://apptainer.org/docs/user/latest/environment_and_metadata.html) and [bind mounts](https://apptainer.org/docs/user/latest/bind_paths_and_mounts.html). This does not add a general container-isolation or real-container cancellation guarantee.
- Unknown classification roots fail during canonical library creation, before remapping. Mapping version and biological Unknown policy remain unchanged.
- An unavailable SQLite identity cache falls back to direct file reading with a warning. Metadata/source identity contracts remain intact.
- Historical 0.7 server acceptance is recorded as completed; historical evidence is distinct from current-release CI.

## CPU and memory contracts

The pool uses the first N logical CPU IDs available in its inherited affinity. Independent roots do not coordinate those IDs. Budget headroom alone cannot prevent overlap with another project or unrelated job. `plan`/`run-preview` show this scope. When using multiple roots, start them in disjoint scheduler/taskset CPU sets allowed by your allocation. An illustrative command is `taskset -c 0-31 teflow run --config project-a.json`; choose actual allowed IDs, not a universal fixed range. Affinity is not CPU ownership or isolation from other users.

RepeatMasker branch-mode defaults remain four threads per stage, with explicit stage overrides available. Reserving 32 total threads therefore does not automatically give two RM jobs 16 each. `examples/branch_resources.balanced-32.json` is an opt-in example, not a measured speedup claim. Validate fixed-library outcomes and wall times before adopting a performance default for a host/genome.

Memory reservations and node MemAvailable admission are retained in both serial and branch mode. They are not hard limits or actual-use predictions. Adjust stage requests to evidence; do not bypass admission merely to keep jobs starting. Timeouts remain explicit failures with a reason. Production cgroups, restart adoption and multi-species queues remain future work.

## Compatibility

Distribution name stays **te-annotation-workflow**, import/CLI stay **teflow**, project name is **TEflow**. These serve different namespaces and do not need to match; changing the distribution solely for spelling would create unnecessary migration work. No PyPI availability or publication is assumed. The experimental `teflow-runtime-check` entry remains explicitly experimental and separate from production.

Preserve old source/configuration for old frozen runs. Use a new run ID for new-version computation. Read-only `report` and `select` may inspect completed legacy exports. Do not resume an old run with new code. No source/upload checksum checklist is required. External downloaded software/databases retain their integrity checks.

## Follow-up boundaries

Useful follow-ups are layer-by-layer gene-space audits, fixed-library reference replay and RM resource benchmarks; then optional divergence landscapes and domain evidence after verifying upstream interfaces. Approximate library clustering, automatic best-library selection, inferred-copy/TE-expression GTF interfaces, matched-null-model enrichment and multi-species scheduling require separate contracts and evidence. They are not bundled into 1.0 simply because they avoid adding an external executable.
