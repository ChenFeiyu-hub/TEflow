# Validation status: 0.5.0.dev1 / 2026-10-17

This development candidate preserves the scientific 0.4.0 workflow and adds an experimental, separate runtime acceptance package. All new real-system tests use finite synthetic processes; no whole-genome analysis was launched.

## Observed local results

| Check | Result | Scope |
|---|---|---|
| Windows unit suite, Python 3.12.14 | 125 discovered; 113 passed, 12 platform/optional skips | Portable contracts plus 22 new runtime evidence/ownership cases |
| Linux unit suite, Python 3.11.17 | 125 discovered; 124 passed, 1 optional skip | Linux process/lock/shell behavior included; optional real-micromamba solver test skipped |
| B2 real user services, local WSL | Seven of seven passed | Normal child; child OOM despite parent exit 0; group OOM; non-OOM SIGKILL; timeout; cancel; reattach and ownership refusal |
| Public CLI lifecycle from source | Passed | Real Snakemake 9.27.0, deterministic mock upstream tools |
| Wheel / sdist → wheel payloads | Identical member bytes | Both packages include the experimental runtime namespace and entry point |
| Installed wheel outside checkout | Passed | Public CLI lifecycle, matching scientific/runtime source digests, entry-point help and all seven B2 cases |
| Real logout on target server | Pending | Linger and actual zero-session continuity must be verified separately |
| Target-server B2 | Pending | Local WSL success is not server acceptance |
| Remote GitHub Actions | Pending | Workflow configured; no remote run claimed |

The source B2 test ran sequential 128 MiB services on one allowed CPU, with swap disabled. Both OOM fixtures reached the recorded 134,217,728-byte cgroup peak. The normal and reattach fixtures peaked at 53,665,792 bytes. All seven attempts confirmed cleanup, including known worker/child identities. These are small acceptance measurements, not memory estimates for EDTA or other TE tools.

Distribution checks used setuptools' existing PEP 517 backend and an isolated virtual environment sharing the already tested scheduler dependencies. No dependency download or full upstream installation was performed. Local `twine check` was not run because twine is not installed; CI includes that check. [Compact runtime results](validation/runtime_local_v0.5.0.dev1.json) omit local filesystem paths and raw host/session information.

The child OOM fixture intentionally has a successful wrapper exit. Positive kernel OOM evidence still produces `OOM_CONFIRMED`. The separate SIGKILL control remains `CHILD_SIGNAL` with zero observed OOM kills. Reattachment uses a fresh interpreter and persisted identity; it does not test a transactional batch-coordinator crash because that coordinator is not implemented.

The new unit tests also reject missing output receipts, false success while a parent is still running, PID reuse, host/worker identity changes, unknown session counts and excessive sampling gaps. No test treats missing metrics as zero. A failed fixture does not become a successful analysis result.

## Existing server evidence

The previous B1 server test verified user-service creation, parent/child cgroup membership, 256 MiB memory and zero-swap limits, one-CPU affinity, a 32 MiB touched child allocation and cleanup. It did not induce OOM or prove survival after all SSH sessions close. The server reported Linger=no; PSI and some CPU cgroup files were unavailable. Logs are therefore written explicitly and optional metrics remain nullable.

The previous Arabidopsis E/ET/H/I/EH results and selected-boundary reproducibility are unchanged; see [0.4.0 validation](TEST_STATUS_v0.4.0.md). They do not certify the new runtime backend. R/RE and HELIANO official-consensus real-genome validation remain separate optional work.

## Scope still open

No shared resource ledger, multi-species admission queue, branch concurrency, automatic retry, production cgroup integration, coordinator crash recovery, host reboot recovery or days-long memory profile has been validated or claimed. The existing `teflow run` remains on the established serialized path. [RUNTIME_CONTRACT](RUNTIME_CONTRACT.md) defines the next gates; [server instructions](RUNTIME_ACCEPTANCE_zh.md) provide B2/B3 commands.
