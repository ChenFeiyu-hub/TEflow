# Selected-locus boundary review, 0.3.1

This optional layer compares explicitly selected loci. It is a wrapper around published alignment tools, not a TE discovery or copy-pairing algorithm. The annotation DAG, EDTA/TEtrimmer/HELIANO/HiTE behavior, catalog decisions and masking decisions are unchanged. It does not depend on pCRE, expression data or motif lengths.

## Inputs and contracts

`boundary-prepare --genome genome.fa --loci selected.tsv --output new_review` accepts optional `--annotation genes.gtf`, `--tools tools.json`, `--flank 500`, `--terminal 100`, `--msa-group group_id`, `--evidence previous_receipt.json`, and `--dust-sensitivity`.

The TSV must contain `locus_id, group_id, seqid, start, end, strand, role, reason` (tabs, header required). Coordinates are **zero-based, half-open** on the supplied assembly; `strand` specifies FASTA orientation. Each group needs exactly one `reference` and at least one `candidate` or `control`. Roles and selection reasons are declarations, not truth labels. IDs use letters/numbers, underscores, dots and hyphens. Distinct locus IDs may refer to overlapping intervals: overlap and group membership must not be confused with independent copies.

Limits: 100 records, 100 kb core per record, 5 Mb total extracted sequence; flanks 0–10 kb. Numeric group directories prevent IDs becoming filesystem paths. Flanks truncate at contig boundaries, and available lengths determine oriented core coordinates. Sequence comes from the **unmasked reference**, uppercased; it is not a cleaned or masked library consensus. Optional annotation is descriptive. Absence of annotation is `not_provided`, never zero CDS risk. CDS positions in `cds_oriented.tsv` are offsets within the oriented extracted sequence.

Preparation records source hashes, selection TSV, frozen extracted sequences, annotation summaries, source-code identity and tool argv lists. Prepared evidence is portable without original genome files; `boundary-plan` and `boundary-run` verify frozen extracts and implementation hashes. Original input paths are provenance, not paths silently rebound after relocation. Do not edit a prepared manifest to change tools: prepare a new review.

Tool JSON example:

```json
{
  "blastn": {"command": ["blastn"], "expected_version": null},
  "mafft": {"command": ["mafft"], "expected_version": null},
  "dustmasker": {"command": ["dustmasker"], "expected_version": null}
}
```

Commands can instead be argv lists beginning with `micromamba run -p PREFIX`. No shell command strings. `expected_version`, when non-null, must occur in the version probe output. Executed versions, resolved command-file hashes and micromamba package metadata hashes are recorded. `null` accepts and records the installed version; it does not assert cross-build equivalence. Existing environments can be used, or an isolated environment created from `envs/boundary.yml`. The small local validation used BLAST 2.17.0+ and MAFFT 7.526; the prior server terminal search reported BLAST 2.17.1+ from another build.

## Execution and interpretation

`boundary-plan --review new_review --threads 1` is read-only. `boundary-run --review new_review --threads 1 --timeout 3600` executes, with 1–8 threads permitted and a per-command timeout. Output directory must not exist; failed attempts remain for inspection. No implicit restart. `boundary-pack --review new_review --output feedback.tar.gz` verifies and packs outputs without original genome or databases.

For each group, BLASTn compares the reference plus flanks against all selected loci plus flanks, including itself. Protocol: `-task blastn -word_size 11 -evalue 1e-5 -dust yes -soft_masking true`; target limit equals the number of selected subjects; no explicit HSP limit or identity cutoff. This is a small selected-subject search, not a whole-genome census. Different search spaces change E-values; a previous terminal-probe hit need not reappear identically. Self-reference core coverage is reported separately as a positive execution control. Incomplete self hits require inspection, not automatic biological interpretation.

Optional `--dust-sensitivity` adds `-dust no` as a **separate** diagnostic. Results are not combined into an acceptance score. Search output is not guaranteed to be a strict superset of the DUST-enabled run. If configured, dustmasker uses window 64, level 20, linker 1 on each extracted sequence and exports verified softmasked FASTA and composition/mask counts.

MAFFT is opt-in for named groups of <=20 core sequences, each <=5 kb: `--thread 1 --localpair --maxiterate 1000`. stdout FASTA and stderr diagnostics are separated. IDs, equal alignment lengths and exact ungapped sequences are verified. No automatic direction correction. A forced multiple alignment does not establish full-length homology; long candidate intervals use local BLAST HSPs instead.

## Outputs

| File | Meaning |
|---|---|
| `loci.tsv`, `genes.tsv`, `cds_oriented.tsv` | Frozen coordinate/sequence context, optional descriptive CDS overlaps |
| `groupNNN/subjects.fa`, `cores.fa`, `reference.fa` | Declared-orientation reference DNA and core offsets |
| `alignments/*.blast.tsv` | Raw 16-column BLAST output, including aligned DNA strings |
| `verified_hsps.tsv` | Every HSP checked against frozen DNA; coordinates remain BLAST 1-based inclusive here |
| `pair_summary.tsv` | Same/opposite orientation, query/subject paired-base coverage, self controls; primary/sensitivity modes separate |
| `region_pairs.tsv` | Paired bases between 5F, 5I, internal, 3I and 3F; potentially cross-region matches preserved |
| `coverage_runs.tsv` | Zero-based half-open unions of paired bases in oriented FASTA coordinates |
| `sequence_complexity.tsv` | Core base composition and optional DUST coverage |
| `*.msa.fa` | Optional short-core alignment, never an automatic TE decision |
| `request.json`, logs/command receipts, `complete.json` or `failed.json` | Parameters, version probes, tool hashes, exit status, immutable file hashes |

Primary coverage counts actual paired columns, including mismatches but excluding unpaired gaps. Overlapping HSPs count once. Query and subject fractions have their own denominators; each internal fraction excludes the inner 100 bp at each end by default. For short sequences the two terminal widths are reduced symmetrically; an empty interior has an empty fraction. **100 bp is a reporting partition, not a minimum Helitron-end length or a TE acceptance threshold.** Terminal/side coverage is available as a region-pair matrix. Cross-locus coverage does not imply one collinear chain, conserved internal order, a complete insertion, or an independent locus. The longest single HSP measure helps distinguish local evidence from unions of fragments.

All aligned DNA, coordinates, lengths, identity percentages, mismatches and gap openings are checked. No automatic HSP chaining, endpoint pairing, hairpin/TSD calling, family reassignment, library cropping, catalog acceptance, masking inclusion or genome reannotation occurs. Weak internal homology can arise in heterogeneous elements; it does not prove a candidate is non-TE. Missing protein hits or CDS overlaps likewise cannot decide validity alone.

## Sources

BLAST options and masking behavior: [NCBI BLAST command-line manual](https://www.ncbi.nlm.nih.gov/books/NBK279684/). Short-set alignment command: [official MAFFT manual](https://mafft.cbrc.jp/alignment/software/manual/manual.html). Upstream licenses remain those of the original tools; no third-party executable or genome is bundled in the source package.
