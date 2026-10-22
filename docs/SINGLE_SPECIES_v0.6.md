# TEflow 0.6: single-species execution and output contract

0.6 finishes the existing single-genome workflow and introduces opt-in concurrency between its library branches. It is a general TE/genome annotation component. pCRE is an optional downstream consumer. No discovery tool, sequence clustering rule, reference database, automatic winner or biological filtering threshold is added.

## Scope and implementation boundaries

| Boundary | Module | Contract |
|---|---|---|
| Branch topology, prefixes, tool probes | `registry.py`, `branches.py` | Explicit enabled parents; existing E/ET/H/I/EH/R/RE dependencies retained |
| Scientific adapters | `stages.py`, `adapters/`, `v2stages.py` | Typed outputs, coordinate/ID checks, provenance; successful exit alone is insufficient |
| Resource policy | `resources.py` | Stage/kind requests translated into one Snakemake DAG |
| Generic local leases | `resource_pool.py` | No branch/tool names; atomic CPU/memory/I/O reservations, process identity, observation and explicit reconciliation |
| Command process lifecycle | `runtime.run` | Owned process groups, return status, timeout/signal cleanup, command receipts |
| Experimental hard-limit backend | `teflow_runtime/` | Separate bounded systemd acceptance; not a production execution backend |

The constructor contract for the local lease pool is `(pool, output, budget, request, policy, labels)`. Labels are opaque metadata. Future workflow changes should extend registry/policy/adapters, not insert TE knowledge into the pool. A future systemd implementation must satisfy the same ownership, quiescence and admission contracts before replacing observation. Schema 3, species queues, restart adoption and Slurm batch management are deferred.

## Branch parallelism

Serial remains default. `init` or `fork-config --parallel-branches --jobs 2 --io-slots 2` explicitly enables branch mode for exactly one sample. Resource totals are **per project work_root**, not per Unix account or host. A controller lock prevents a second TEflow controller using that work_root. It does not reserve resources against unrelated jobs or other project roots; operators must choose budgets that leave room for them.

```json
{
  "mode": "branches",
  "max_jobs": 2,
  "io_slots": 2,
  "keep_going": true,
  "memory_headroom_mb": 4096,
  "poll_seconds": 10,
  "admission_timeout_seconds": 600,
  "stages": {
    "repeatmasker": {"threads": 8, "mem_mb": 32768, "io": 1}
  }
}
```

This object goes in `execution.scheduling`; `--stage-resources` accepts only its `stages` object. Keys can be kinds (`repeatmasker`, `qc`, `export`, `assembly`, `prepared`, `tracks`, `edta`, `tetrimmer`, `heliano`, `hite`) or enabled concrete stage names. Concrete names override kind defaults. Unknown keys and requests exceeding the pool are rejected before launch. RepeatMasker-bearing stages require at least four threads. Requested threads cannot be silently scaled by Snakemake.

Discovery/refinement defaults still request the entire global CPU/memory budget. This deliberately allows concurrent uniform remapping and lighter stages without assuming EDTA or HiTE memory needs. Only an explicit measured override permits expensive discovery stages to overlap. RM defaults to four threads and `total_mem_mb / max_jobs`; `-pa` remains `threads // 4`. Assembly/QC/export resource estimates are admission requests, not measured needs.

Snakemake owns dependencies and readiness. The pool assigns distinct concrete CPU IDs and enforces matching reservations. Every stage receives a private TMPDIR under `<work>/<run>/<sample>/.runtime/<stage>/<attempt>/tmp`. Requests are shared across all subprocesses of that stage. Upstream tools can create many threads, but descendants inherit the stage's CPU affinity. A program deliberately resetting affinity or daemonizing outside its process group is outside this observation backend's containment guarantee.

`--keep-going` lets unaffected branches finish; failed prerequisites leave dependent stages blocked. Final comparison cannot report success with a missing branch. No automatic retries, resource escalation, force-unlocking or resubmission occurs. `--resume` applies to the same frozen inputs and parameters after a reviewed transient failure. Interrupted scientific work directories retain their existing semantics; only runtime observations get a fresh attempt directory.

## Memory, ownership and failure semantics

Memory has three separate meanings:

1. `mem_mb` requests: scheduler/pool reservations whose sum must fit the configured budget.
2. `/proc/meminfo` MemAvailable: a node observation used to pause new starts if free capacity cannot cover headroom, the new request and unobserved reserved growth of active jobs.
3. Sampled process-tree RSS: stage worker plus current descendants. Shared pages can be counted repeatedly and brief peaks can be missed. This is **not** cgroup memory.current or a hard memory limit.

For local admission/RSS comparisons the retained `mem_mb` convention uses 1,048,576 bytes per unit (MiB). Snakemake uses the configured integers as scheduling tokens; its human-readable decimal display is not a kernel memory limit. Telemetry preserves raw byte counts. Large genomes need explicit requests for preparation, tracks and export as well as discovery; the small-genome light-stage defaults are not measured guarantees.

Missing observations remain unknown. The gate times out with a recorded reason and starts no analysis; it neither kills external work nor suspends running tools. There is no OOM classification based solely on exit 137. Sample files report measured RSS, sampling type, peak, elapsed time, process count and monitor errors. A monitor error does not make an otherwise valid biological output invalid, but is explicitly recorded as incomplete telemetry. No `oom_score_adj` changes are made.

Pool leases record host/boot/PID/start ticks and owned command PGIDs. Normal command failure and cancellation clean the owned process group before releasing resources. A worker lost during dispatch leaves a conservative unresolved-spawn record. `runtime-reconcile` never sends a signal; it only removes leases with a proven dead owner and no live recorded command groups. An ambiguous dispatch needs manual process review. TTL expiry or dead controller PID alone never authorizes killing/replacing a task. OS controller-lock release is separate from worker quiescence.

The file-lock pool is for a **single Linux host on a local filesystem with reliable flock/atomic rename**. It is not a distributed scheduler. Production hard memory limits, automatic adoption after controller loss and account-wide logout survival are not certified in 0.6. The earlier B2 server fixtures passed; strict B3 zero-session evidence remains unproven because closing sessions persist. `login-status` now reports those states separately without relabeling the old test.

## Classification and coordinates

Mapping version `0.3` explicitly matches aliases with delimiter boundaries instead of arbitrary substrings. RM labels such as DNA/MULE-MuDR, DNA/CMC-EnSpm, DNA/Kolobok, DNA/Sola-*, DNA/P and DNA/Merlin are summarized with the appropriate TIR group. DNA/Crypton and DNA/Maverick remain distinct. Raw labels are never replaced, sequences are never reclassified, and novel subfamilies under a known root receive `root_only` with no guessed superfamily code. Unknown roots fail validation; biological Unknown remains a valid separate tier. `classification_uncertain` retains upstream `?` evidence. Wicker-compatible codes are vocabulary summaries, not sequence evidence.

`mask_sources.tsv` retains its existing first twelve columns and appends `rep_start`, `rep_end`, `rep_left`, inferred `consensus_length`, actual `library_length`, `consensus_coordinate_status` and original `rep_tokens`. Genome coordinates remain 0-based half-open. Consensus coordinates are 1-based inclusive, oriented to the consensus sequence; strand records direction. `.out` is the ProcessRepeats-adjudicated artifact, so negative remaining lengths and discrepancies are retained as `out_of_bounds`/`length_mismatch`. Only `verified` rows receive GFF3 Target coordinates. Even a verified row is a fragment, not proof of a full-length insertion.

The official [RepeatMasker help](https://raw.githubusercontent.com/Dfam-consortium/RepeatMasker/master/repeatmasker.help) describes `.out` columns, postprocessing and optional original outputs. The precise cause of each observed discrepancy is not inferred from this documentation. Matching producer files and alignments require separate review.

For verified GFF3 targets, column 7 carries the genomic orientation and Target uses the forward consensus strand. A reverse hit therefore uses `-` in column 7 and `+` in Target, following the [GFF3 strand convention](https://github.com/The-Sequence-Ontology/Specifications/blob/master/gff3.md). A double minus would describe direct relative alignment. Gap strings are not fabricated from `.out` summaries.

HiTE takes `--plant 1` only for `sample.taxon_group=plant`; `metazoa`, `fungi`, `other` use 0. A missing legacy field defaults to plant, recorded as such. This flag does not establish validation in every taxonomic group.

## Masking and coverage

Default `genome.softmasked.fa` and `repeat.mask.bed` remain classified TE + tandem repeats + DUST, excluding Unknown and other non-TE tracks. `exports.softmask_policies=["te_primary","all_interspersed"]` adds `genome.softmasked.all_interspersed.fa`, including Unknown as well. The separate inclusive BED is inexpensive and always exported. The policy name does not mean only interspersed elements: the exact contributing layers are recorded in qc.json. RNA/satellite/non-TE hits remain separate.

`coverage_layers.tsv` reports interval unions for TE, Unknown, non-TE, tandem, low complexity, TE∪Unknown, primary mask and inclusive mask. Layer counts must never be added to obtain union coverage. `*_fraction_of_genome` uses total selected sequence length. `*_bp_per_acgt_bp` is a ratio with the nonambiguous-base denominator; its numerator still includes all covered positions and it is not a fraction of ACGT positions masked. Zero denominators are null.

`reevaluate` creates a fresh directory outside old runs, records source file sizes/timestamps and original receipt identities, and recomputes genome-wide class inventories, class totals, layer unions and pairwise differences. It does not copy genomes, generate masks or rerun annotation. It omits promoter/reference reevaluation explicitly. `audit-results` reads raw `.out` plus the corresponding library to report vocabulary/coordinate issues. Neither command modifies old libraries or receipts.

## Performance and release handling

The public launcher freezes/checks before dispatch. Snakefile parsing only checks frozen config/source identity; directly invoking Snakemake bypasses launch preflight and is for tests/advanced use. Internal content identities retain existing resume/provenance contracts. Large-file identities use an optional shared SQLite cache keyed by absolute path, device, inode, size, mtime and ctime. This avoids repeat reads of unchanged bytes; it is not an adversarial tamper guarantee. The first observation of a changed/uncached file still reads it. Source/upload acceptance no longer requires checksum commands or sidecars. Download installers retain pinned integrity checks.

Staging uses an independent-inode reflink where Linux/filesystem support it, with full-copy fallback. It never uses hard links for mutable upstream inputs. Normal status only checks artifact existence/metadata and reports runtime evidence. It does not repeatedly read large FASTA/alignment contents.
