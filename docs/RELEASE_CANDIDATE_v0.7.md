> Historical 0.7 preparation record. Target-server acceptance subsequently passed on 2026-10-22; see [current validation](TEST_STATUS_v1.0.md). Earlier pending statements below are dated, not current release status.

# 0.7 release candidate contract

Version: **0.7.0rc1**. This is a local release candidate for single-species TE annotation, pending bounded target-server acceptance and remote CI. General genome annotation remains the primary scope. Expression/pCRE data are optional downstream consumers.

## Frozen scope

Published tool versions, branch membership, scientific parameters, exact/RC same-class library folding, mask policy and export coordinate rules are unchanged from 0.6. E, ET, H, I and EH remain separate outputs. No automatic consensus library or best branch is introduced. Multi-species orchestration, production cgroups, controller crash adoption and strict logout proof are deferred.

## Run lifecycle

```text
run-preview (read only)
    -> run: controller lock -> preflight/freeze/probes -> supervised Snakemake
          -> succeeded / dry_run_passed / failed
          -> cancelling -> cancelled / cleanup_unresolved
```

Every admitted attempt has its own ID, request path, scheduler log and durable launch receipt. Preflight failures now leave receipts too. The controller is one per work root; independent projects should use separate work roots. The scheduler inherits this one lock descriptor explicitly, so a supervisor crash cannot permit a second launch while the old scheduler lives. A targeted success is not full-run completion. `status` distinguishes launcher state from artifact status and treats a dead supervisor as interrupted rather than running.

`cancel --config` checks protocol, configuration, run ID, host, boot identity and process start ticks, then writes only the active attempt's request file. It never signals a disk-stored PID. The live supervisor sends one interrupt to its own unreaped scheduler child. Leased workers and external command waits notice the same request; each command runner terminates only the process group that it started. Existing completed results are retained.

Cancellation is asynchronous and cooperative. A Python-only stage or input scan can finish before acknowledging it. The scheduler may take time to exit. After scheduler exit, the supervisor allows up to 30 seconds for leases to disappear; remaining leases produce `cleanup_unresolved`, never clean success. No forced arbitrary-process kill or automatic lease removal is performed. Abrupt SIGKILL, host failure or a tool escaping its process group requires manual review; adoption is not implemented. A shared Unix account is not a security boundary.

`run --resume` starts a new control attempt, while the interrupted stage is reused only under existing immutable input/config/source rules. Old cancel files cannot cancel a new attempt. Changed source versions require a new run ID. `fork-config` imports no results; users must see the preview before authorizing a new expensive run. Existing `import-stage` remains an explicit advanced operation, not an upgrade default.

## Observation

Every external command triggers a sample and a ten-second burst at 250 ms intervals, followed by the configured `poll_seconds` (default 10). A final stage sample is added. The monitor wakes cheaply between samples; it scans `/proc` only when sampling. Counts, descendant-observation counts, maximum gaps and errors are persisted.

RSS is a sampled sum over the worker and live descendants; shared pages may be counted more than once, peaks and detached descendants may be missed. `parent_only` and legacy `initial_only` are explicit. Faster sampling improves short-job coverage but is not exact accounting, a memory limit or an OOM guarantee. Reservations, admission headroom and CPU affinity semantics remain unchanged. No observed number automatically lowers a future request.

## Reporting

`report` writes Markdown, structured JSON, stage TSV and runtime TSV into a new directory outside the original run. It reads receipts, summaries and metrics without genome/TE tool execution or a new freeze. Coverage is descriptive; TEtrimmer fallback/low-copy originals are distinguished from refined consensuses. Source metadata changes invalidate summary reads. A running report remains a snapshot, not an atomic database transaction.

`runtime-summary` reads 0.6 and 0.7 metrics. Sampled stage interval overlap is not actual command overlap or speedup; the independent 0.6 server audit separately measured command overlaps. `logs` bounds output to the last requested lines within 128 KiB per log. Feedback includes launch receipts, preview, cancellation and scheduler logs, with explicit truncation for large files.

## Promotion criteria

1. Local portable/Linux units, all prior synthetic scheduler workflows, scoped cancellation/resume, unchanged output preservation and installed-package tests pass.
2. A source ZIP, sdist and wheel carry the intended source/recipe payload. No manual development/upload SHA-256 step.
3. Run `scripts/accept_release_candidate.py` on the target server. It uses only tiny synthetic data and fake tools.
4. Review the read-only report from the completed 0.6 run on that server. No rerun is needed to inspect old results.
5. Run GitHub CI on the actual pushed commit, review public metadata/authors and only then tag a release candidate or final release. Local checks do not stand in for remote CI.

Final 0.7.0 is not claimed by this package. The known unproven strict B3/logout result remains unchanged and does not block this narrower local supervisor contract.
