# 1.1.0rc1 validation — 2026-11-08

This candidate makes v4 CPU the new-project default and retains v3 as an explicit backup. It keeps the single-species scheduler and separate library/export policies. Biological accuracy, execution compatibility and packaging acceptance are different evidence levels.

Server evidence added later on 2026-11-08: **bounded packaging acceptance passed**. See the [detailed feedback review / 中文](TIR4_SERVER_REVIEW_2026-11-08_zh.md) and [machine-readable server record](validation/server_tir4_v1.1_2026-11-08.json). The already delivered rc1 archives and their local-test records are unchanged snapshots; this supplement records subsequent server evidence.

## Completed experimental TAIR10 comparison

The supplied full-test feedback of 2026-11-07 completed EDTA 2.3.0 and uniform RepeatMasker 4.2.4 for v3 and v4. The experiment's actual v4 CPU discovery call was recorded. It used five nuclear chromosomes (119,146,348 bp) and 27,295 CDS records. This was the experimental bridge, not the newly packaged production adapter.

| Observation | v3 | v4 |
|---|---:|---:|
| Raw TIR records | 581 | 679 |
| Unique raw coordinate/type combinations | 581 | 671 |
| Cleaned TIR candidates | 377 | 428 |
| Raw hAT records | 57 | 7 |
| Cleaned hAT candidates | 51 | 6 |
| Final RepeatMasker hit union, bp | 16,404,077 | 16,406,725 |
| Classified-TE union, bp | 15,399,619 | 15,510,241 |
| TIR-stage elapsed time, seconds | 898 | 61 |

These are one-run observations, not an accuracy or controlled speed benchmark. Non-TIR components also differed; whole-library changes cannot be attributed solely to TIR-Learner. In particular, hAT loss is not proof that v3 overannotated or that v4 is wrong. The [upstream rule audit](UPSTREAM_TIR4_AUDIT_2026-11-08.md) records a specific TSD-pattern question and the planned checkpoint inspection.

## Current production adapter

The native parser independently read all 679 supplied v4 records, retained six scores and found 8 extra duplicate site records. Every reported class was among the highest-scoring labels. This local re-read did not include the server's whole genome; the earlier experiment had its own sequence-span check. New production stages require that check and actual successful v4 call receipts.

Local validation results are recorded in [local_v1.1.0rc1.json](validation/local_v1.1.0rc1.json). Tests cover new defaults and explicit fallback, legacy-config preservation, CPU/Python isolation, package identity, missing models, subprocess failure propagation, raw coordinate/score contracts, stale-success rejection and bounded checkpoint reads. Scheduler fixtures use real Snakemake and synthetic upstream executables; they do not execute EDTA/TIR-Learner or certify biological performance.

| Local check | Result |
|---|---|
| Windows / Python 3.12.14 units | 198 total: 169 passed, 29 platform/environment skips |
| Linux / Python 3.12.14 source units | 198 total: 197 passed, one environment skip |
| Linux installed-wheel units | 198 total: 197 passed, one environment skip |
| Source and installed-wheel lifecycle | Both passed actual Snakemake 9.27.0 CLI, cancellation/resume and four-CPU branch-concurrency fixtures |
| Distribution contents | Installed wheel payload compared byte-for-byte with the final source files and bundled recipes; experiments, genome data and feedback excluded |

The Python 3.12 test environment is separate from the server's Python 3.11 tool environments. An attempted local Python 3.14 scheduler setup could not build a dependency; scheduler tests were therefore run with isolated Python 3.12. This did not modify the server recipes or dependency versions. GitHub CI is recorded per commit in [Actions](https://github.com/ChenFeiyu-hub/TEflow/actions/workflows/ci.yml); the historical local record does not certify a remote run. The GitHub source adds the subsequent server evidence to the unchanged delivered rc1 snapshot. The version remains a release candidate, with no new stable tag implied.

## Remaining acceptance and limits

- The [bounded target-server handoff](SERVER_TIR4_v1.1_zh.md) passed on 2026-11-08: 16 dependency/model checks and the historical 679-record sequence-span audit. This is not a new full-genome run through the production adapter.
- The four existing checkpoints were read successfully for all 59 hAT sites. All 52 v3-only sites have exact initial GRF candidates and no overlapping post-CNN records. CNN versus structural-filter attribution remains unresolved; the absent candidates' scores were not stored in this feedback.
- No upstream biological filter was changed, retrained or tuned to recover v3 counts. No automatic union, best-library choice or algorithm fallback is introduced.
- No GPU support, new hard-memory enforcement, multi-species queue or cross-species accuracy certification. Earlier systemd B2 evidence and unproven strict B3 remain separate from this release.
- A future upstream fix/version needs a separately identified backend and comparative validation; it must not be hidden under the same 4.08 label.
