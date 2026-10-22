# 0.6 validation record — 2026-10-17

This is an engineering package, with serial default and opt-in single-species concurrency. Local Windows/Linux evidence and earlier target-server evidence are separate. The target server has not yet accepted 0.6 and no new real-genome TE discovery was run for this release.

## Local test status

Final test counts and distribution results are recorded in `validation/local_v0.6.json`.

| Check | Result |
|---|---|
| Windows units | 155 total; 136 passed, 19 platform/environment skips |
| Linux units | 155 total; 154 passed, 1 optional environment skip |
| Actual Snakemake regression | Legacy, seven-branch, generic-genome, candidate wrapper, reviewed import and public CLI passed |
| Parallel fixture | 8-CPU source/server-wrapper and 4-CPU CI-sized runs passed; separate installed-wheel 8-CPU run passed |
| Installed package | Public CLI lifecycle, parallel/failure fixture, init/fork resource options and runtime help passed outside the source import path |
| Distribution roundtrip | Wheel rebuilt from sdist has identical member payloads; package metadata/version checked; no network downloads used |

The fixtures cover resource reservation/cleanup, serial/parallel output equivalence, branch failure isolation and independent evaluation preserving old files. They use simulated upstream tools, not an EDTA/HiTE accuracy benchmark. Final packaging rechecks payload equality after documentation updates. Remote GitHub Actions has not been run.

The baseline golden contract contains 312 legal branch/QC configurations. It freezes graph and tool membership, not every possible upstream argument or biological outcome. The local identity-cache regression reads a 1,048,577-byte unchanged file once across two calls with the in-memory cache cleared; a same-size edit invalidates the persistent cache and is read again. This demonstrates the cache boundary, not a genome-wide performance speedup.

## Existing Arabidopsis output audit

The new parser was exercised on all five supplied native uniform-RepeatMasker `.out` files, paired with the corresponding library files from the supplied E/ET, H/I and final EH review bundles. Total: **138,742 fragments**. No source file was modified; no RepeatMasker command was launched.

| Branch | Fragments | Length-consistent, in bounds | Out of bounds | Other length disagreement |
|---|---:|---:|---:|---:|
| E | 38,023 | 36,550 | 505 | 968 |
| ET | 24,282 | 23,773 | 76 | 433 |
| H | 11,239 | 10,898 | 153 | 188 |
| I | 22,612 | 21,679 | 205 | 728 |
| EH | 42,586 | 40,867 | 593 | 1,126 |

There are **4,975 diagnostic rows** in these file combinations. In particular, a real reverse-strand row contains `(-2) 1346 876` in its consensus fields. A strict nonnegative-remaining parser would reject such existing data. 0.6 retains the original tokens, records diagnostics and omits unverified GFF3 Target attributes. “Length-consistent” does not prove biological completeness or correctness of a consensus boundary.

No unknown classification roots were encountered in these fragment files. HiTE has 442 root-only mappings; these are retained under their known broad roots without invented superfamily codes. Classification correction changes category summaries, not the original sequence library, genomic hit intervals or primary mask membership.

The audit is not independent verification that all historical file-producer relationships are correct. The complete server `audit-results` report using files in the original run remains the next check. Individual discrepancy causes require matched producer evidence/raw alignments. Do not rerun annotation or discard these hits based on this summary alone. See `validation/arabidopsis_existing_v0.6.json` for machine-readable counts.

## Target-server evidence carried forward

- Earlier five-branch Arabidopsis computation and selected-candidate boundary review completed under their original versions.
- `0.5.0.dev2` B2: nine bounded server cases passed, including success, child/group OOM, ordinary signal, timeout, cancellation, reattachment and high-virtual-memory controls.
- Strict B3: **not proven**. The user observed lingering logind sessions in `closing` state, while linger was enabled. This does not justify terminating unrelated account processes. 0.6 reports detailed states; it does not rewrite the previous verdict.
- 0.6 server single-species acceptance: **pending**. The command is in [SERVER_v0.6_zh.md](SERVER_v0.6_zh.md).
- New real-genome parallel run, multi-species scheduler, production cgroup memory enforcement, multi-day logout survival, cross-species accuracy and remote GitHub CI: **not claimed**.

## Next acceptance

Run the small server wrapper first, then `audit-results` and `reevaluate` on the original Arabidopsis exports. The next real workload should measure independent remapping branches with explicit budgets; it should not automatically restart all completed discovery work. Use those measurements to choose future resource profiles and whether to integrate the already-tested systemd primitives into the production backend.
