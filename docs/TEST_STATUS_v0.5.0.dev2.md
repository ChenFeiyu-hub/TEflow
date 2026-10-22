# Validation status: 0.5.0.dev2 / 2026-10-17

dev1 target-server feedback showed four allocation-dependent B2 failures, with blank exception strings and approximately 35 MiB cgroup peaks. The other three cases passed. The login query incorrectly returned no properties, and no B3 heartbeat was launched. The target account then explicitly reported Linger=yes. These observations supersede any assumption that local dev1 success certified the target host.

dev2 fixes repeated loginctl property queries, missing-property semantics, diagnostic exception types, virtual-address headroom and persisted logout-attempt selection. Fixed cgroup memory/swap limits remain unchanged. The resource ledger and production batch backend remain unimplemented.

| Local check | Observed result |
|---|---|
| Windows units | 138 discovered: 125 passed, 13 platform/optional skips |
| Linux units | 138 discovered: 137 passed, 1 optional micromamba skip |
| Real local B2 | 9/9 passed, all cleanup confirmed; 128 MiB per sequential user service |
| Virtual-address regression | Old fixed ceiling produces MemoryError; incremental ceiling permits 32 MiB allocation |
| Login properties | Repeated-property command reads actual local state; zero versus missing properties covered by fixtures |
| Heartbeat + identity file + cancellation | Real service and two heartbeat samples; startup linger gate mocked for this fixture only; no host settings changed and no full logout claimed |
| Wheel / sdist roundtrip | Same member bytes; installed namespace and source digests verified |
| Installed wheel outside checkout | Public CLI lifecycle and all 9 real local B2 cases passed |

The installed check uses an isolated venv with the existing tested Snakemake dependencies; no upstream TE installation is repeated. Local twine is unavailable and no local twine result is claimed. Compact, path-free evidence is recorded in [runtime_local_v0.5.0.dev2.json](validation/runtime_local_v0.5.0.dev2.json).

Local unit regression reserves 384 MiB of inaccessible, untouched virtual space: the old absolute 256 MiB RLIMIT_AS causes `MemoryError` on a 32 MiB allocation, while a finite 256 MiB additional budget succeeds. This proves the failure mechanism locally; the original server log lacks the type/VmSize needed for direct historical attribution. New server diagnostics are still required.

The B2 suite adds success/OOM tests with the same virtual baseline. A local B3 heartbeat check can validate property reads and cleanup while logged in; it cannot certify actual full SSH logout. Target-server dev2 B2/B3 and remote GitHub CI remain pending. The new guide is [RUNTIME_ACCEPTANCE_dev2_zh.md](RUNTIME_ACCEPTANCE_dev2_zh.md).
