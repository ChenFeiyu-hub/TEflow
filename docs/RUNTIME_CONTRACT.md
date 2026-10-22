# Runtime boundary and validation gates

Status: **experimental, 0.5.0.dev2**, 2026-10-17. The implementation currently provides bounded acceptance fixtures. It does not replace `teflow.runtime`, schedule multiple genomes, reserve host resources, or constrain existing `teflow run` jobs with cgroups.

## Separation from biological workflows

`teflow_runtime` imports no TE discovery, library, pCRE or annotation modules. Its current inputs are an argv vector, working directory, resource limits and a persisted attempt handle. It emits structured evidence and an outcome. The future workflow adapter must convert a ready DAG stage to a generic job specification and validate biological artifacts after the backend completes. A process exit of zero cannot replace the existing output receipts.

The runtime package carries a separate source digest in each handle. Scientific configuration/source freezing remains unchanged. No old run is reopened with altered hashes; acceptance writes to `runtime_acceptance/`, outside analysis output directories. The development candidate is separate from the frozen 0.4.0 distribution.

## Implemented acceptance contract

Each attempt gets a unique unit name, description, directory and boot identity. Submission records intent before calling systemd. A submitted or uncertain attempt cannot be submitted again. Reattachment uses the persisted handle; stopping checks the host, boot, unit name, transient property, description and recorded InvocationID. PID checks additionally use process start ticks. Identity mismatch fails closed, without sending a signal. This is task-ownership protection, not a security boundary against another process with the same Unix account.

The worker independently checks its cgroup membership, actual memory/swap limits, CPU affinity, OOM policy and source digest before allocating test memory. B2 uses one CPU and 128 MiB per sequential service, swap disabled, with a finite touched allocation of at most 192 MiB and a short service timeout. A second virtual-address ceiling allows at most 256 MiB above the child's measured pre-allocation VmSize and preserves stricter inherited soft/hard limits. The external observer is outside the test cgroup. Parent and child stdout/stderr go to files because a readable user journal is not assumed.

dev1 used a fixed 256 MiB total address ceiling, which can reject allocation even when resident memory is low. dev2 records VmSize/RSS and limits, adds a normal/OOM pair with a 384 MiB inaccessible, untouched virtual reservation, and reports exception types/tracebacks. This tests an interpreter with a large virtual baseline without raising the 128 MiB physical cgroup limit. Server dev1 feedback fits this failure mechanism but lacked exception type and VmSize; exact server attribution still requires the revised evidence.

An observed `memory.events:oom_kill > 0` or systemd `Result=oom-kill` is affirmative OOM evidence. Exit 137 or SIGKILL alone is insufficient. Missing counters/PSI remain unknown. `memory.peak` is the kernel cgroup peak when available, distinct from sampled RSS. CPUAffinity restricts allowed CPU IDs; it provides neither exclusive cores nor a CPU-time quota. Tests do not claim those unavailable capabilities.

Failure classification preserves OOM and timeout evidence before later cleanup. Expected fixture failures count as a successful **acceptance test**, never a successful analysis. Every B2 case checks cleanup; uncertain cleanup stops the suite. No service is selected by process name or a broad wildcard, no automatic high-memory retry occurs, and no login/session setting is changed by the software.

## Logout acceptance

B3 requires `Linger=yes` before launch, but does not treat that as proof. A bounded heartbeat records its boot/PID/start identity and login-session count every five seconds. Passing requires a known logged-in starting sample, at least 60 continuous seconds with zero sessions, no unknown samples or sampling gaps over 15 seconds within that interval, and the same live worker after reconnecting. The practical instruction is to remain logged out for at least 90 seconds. A different open session under the same account prevents this proof; the script never closes it for the user.

Property queries use repeated `-p` arguments, supported by loginctl v252; empty command output is unknown, while explicit `Sessions=` is zero. `LOGIN_STATE_UNAVAILABLE` is separate from an observed `Linger=no`. `logout-start --attempt-file` persists the successful invocation identity for checking after reconnecting, without a manually substituted example path. It refuses to overwrite an existing receipt.

Reattachment to a live service is implemented. A production coordinator database, crash recovery during lease transactions, cross-host reconciliation and a full interruption matrix are **not implemented**. A host reboot is explicitly outside the current continuation guarantee.

## Next implementation gates

| Gate | Work and acceptance needed |
|---|---|
| Host acceptance | B2 on the target server; B3 across an actual full logout. Keep a nonpersistent/session-bound fallback explicitly labelled if linger is unavailable. |
| Resource ledger | Atomic reservations of CPU IDs, memory budget and I/O slots in a local coordinator database; no release on missing heartbeat alone; recover by reconciling owned services. Test competing coordinators, stale leases and controller crashes. |
| Generic batch planner | Species manifest → stage DAG → ready job specs. Admit only within configured host budgets and live available-memory headroom; treat missing measurements conservatively. Keep large EDTA jobs and heavy I/O admission configurable. |
| Branch adapter | Share one ledger across species and library branches; declare dependency/resource requests per stage without embedding the science in the scheduler. Preserve independent outputs and immutable attempt IDs. |
| End-to-end execution | Concurrent tiny synthetic workflows, cancellation, OOM of one branch, reconciliation after controller loss, and a small real-server workload. Only then enable an opt-in production backend. |

Larger cross-species benchmarks and biological accuracy assessment remain separate from these engineering gates. The runtime is intended for general genome annotation and TE research; no expression-data prerequisite is introduced.

## Reference behavior

The OOM policies follow [systemd v252 service documentation](https://github.com/systemd/systemd/blob/v252/man/systemd.service.xml), with kernel counters/group semantics from [cgroup v2 documentation](https://docs.kernel.org/admin-guide/cgroup-v2.html). Logout configuration follows [loginctl v252](https://github.com/systemd/systemd/blob/v252/man/loginctl.xml). Implemented checks read back observed behavior rather than assuming a version string guarantees it.
