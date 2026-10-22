> Historical 0.7 preparation record. Target-server acceptance subsequently passed on 2026-10-22; see [current validation](TEST_STATUS_v1.0.md). Earlier pending statements below are dated, not current release status.

# 0.7.0rc1 validation — 2026-10-20

The machine-readable final local record is `validation/local_v0.7.0rc1.json`. This document separates historical real-data evidence from the new engineering checks. There is no new biological accuracy claim.

## Existing target-server evidence

The 0.6 Arabidopsis run completed at **2026-10-17 22:23:41 Asia/Shanghai**. Its feedback was audited on October 20. Snakemake completed 24/24 tasks; all 22 scientific stage receipts, 23 resource attempts and five branch exports completed. The final resource pool was empty. E, ET, H, I and EH contained 732, 223, 233, 429 and 965 library sequences, respectively.

Actual RepeatMasker command overlaps totalled **1,925.64 seconds (32.09 minutes)**. Paired CPU affinities were disjoint; no recorded pool budget violations were found. This proves observed concurrency on that run, not serial speedup, global CPU exclusivity or cross-species performance.

The old five protein-QC attempts lasted 4.43–5.40 seconds but each had only one parent-process sample. Those values do not measure tool peaks. The 0.7 burst sampler addresses this specific observation gap; it still cannot establish exact memory use or OOM safety.

ET's retained output origins were 76 refined consensuses, 139 original-input fallbacks and eight original low-copy sequences. No automatic winner is chosen. New versus earlier discovery libraries differ, so changes in coverage cannot be attributed to parallel execution or software accuracy. Full raw genomic artifacts were not independently reverified from the compact feedback.

These evidence points are summarized in `validation/server_v0.6_2026-10-20.json`. Original dated 0.6 build documents remain unchanged historical records; their then-pending server status is superseded by this later audit.

## New RC checks

Local verification covers portable and Linux units; the existing seven-branch/generic-genome/candidate-review/import workflows; serial/parallel equivalence and branch-failure isolation; the public CLI; and the new cooperative cancel/resume integration. The latter checks descendant cleanup, preservation of an independent process, preservation of completed receipts, report immutability and diagnostic packaging.

The source, sdist and wheel are built without network downloads. The wheel is exercised outside the checkout, including control and branch concurrency. Source/recipe payload comparison is direct; no source/upload checksum acceptance is required. Final counts, commands and actual pass/fail are in the machine-readable record.

These use a 160 bp fixture and fake TE tools, not real EDTA runs. They establish wrapper contracts, not biological detection quality. Target-server RC acceptance and GitHub Actions remain **pending** until actually executed. The earlier systemd dev2 B2 passed 9/9; strict B3 remains **not proven**. Production hard memory limits and controller-crash adoption are not advertised.

## Final local results

| Check | Result |
|---|---|
| Windows units | 165 total: 141 passed, 24 environment/platform skips |
| Linux installed-package units | 165 total: 164 passed, one environment skip |
| Existing and new source scheduler regressions | Eight workflows passed; includes seven-branch, CLI, cancellation and 4-CPU parallel fixture |
| Installed wheel outside checkout | CLI, cancellation/resume, 8-CPU parallelism and metadata passed |
| Frozen source server-acceptance entry | Control and 8-CPU parallel fixtures passed locally |
| 0.6 feedback report compatibility | 23 attempts and all five sparse QC records identified; retained sequence origins matched |
| Distribution | Wheel/sdist payload roundtrip passed; final wheel matches the tested wheel |
