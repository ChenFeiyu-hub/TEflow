# 1.0 validation — 2026-10-22

1.0 retains the scientific protocol and adds engineering safeguards and delivery interfaces. Evidence is recorded separately for the current release, historical real-genome runs and host-specific acceptance. A passing fixture does not establish biological accuracy.

## Historical target-server evidence

- The 0.6 TAIR10 run completed 22 scientific stages, 23 runtime attempts and five exported branches. Real RepeatMasker overlap was observed; it is not a speedup benchmark. See [the sanitized record](validation/server_v0.6_2026-10-20.json).
- The 0.7 supervisor passed the target-server bounded acceptance on 2026-10-22: cancellation/resume, owned-child cleanup, preservation of unrelated processes, serial/parallel scientific equivalence, disjoint pool affinities, failure propagation and empty final leases. See [the sanitized record](validation/server_v0.7_2026-10-22.json). These use real Snakemake and mock upstream tools.
- The brief host-protein QC commands in the 0.6 feedback did execute DIAMOND successfully. Their old parent-only telemetry did not capture tool peaks. Duration alone is not evidence that QC was skipped.

## Current release checks

The fixed source snapshot and installed package passed the following local checks. Machine-readable evidence is in [local_v1.0.0.json](validation/local_v1.0.0.json).

| Check | Observed result |
|---|---|
| Windows units | 174 total: 148 passed, 26 platform/environment skips |
| Linux source and installed units | Each 174 total: 173 passed, one environment skip |
| Actual single-CPU resource tests | 11 total: 10 passed, one two-CPU test skipped |
| Source scheduler regressions | Eight passed: baseline, seven-branch, generic genome, candidate wrapper, reviewed import, CLI, parallel and control |
| Installed wheel outside checkout | CLI, cancellation/resume, four-CPU parallelism, lineage report and explicit selection passed |
| Export fault handling | Injected incomplete export never published; failed replacement preserved previous complete output; retry passed |
| Source release acceptance entry | Delivery units, control and parallel fixtures passed locally |
| Distribution | Wheel/sdist payload roundtrip equal; metadata validated; final wheel equal to tested wheel |

The earlier exploratory integration run against editable source was invalidated when source changed during execution; the freeze guard rejected it. It is superseded by the fixed-snapshot results above, not counted as a passing run.

Inspect [GitHub Actions](https://github.com/ChenFeiyu-hub/TEflow/actions) for the exact uploaded commit. The local results above do not imply that remote CI passed.

## Limits retained

- The 1.0 target-server smoke is a separate requested follow-up; no new real-genome run is required for packaging.
- No production cgroup hard-memory enforcement or controller-crash adoption. Experimental systemd B2 passed previously; strict B3/logout remains unproven.
- HiTE temporary-directory arguments are tested; a real-container cancellation/scratch smoke is separate future evidence.
- Large raw alignment/export tables were not included in compact feedback. New missing-parent genomic coverage must be calculated from the full server tables; missing inputs are reported as unknown.
- One Arabidopsis run is not cross-species validation. Coverage, gene overlap and library sizes do not rank biological accuracy.
