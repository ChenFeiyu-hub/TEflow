# Choosing and delivering results

TEflow 1.0 provides separate annotations. Select a branch and masking policy for your use case; coverage is not a quality ranking. E (EDTA) is a practical starting baseline for genome annotation. ET is a refinement/curation comparison and must not be assumed to retain all E families. H is a Helitron supplement; EH is an experimental E+H library. I is a comparison route with bundled homology resources/models. No branch is universally best.

| Purpose | File under `results/<run>/<sample>/<branch>/` | Meaning |
|---|---|---|
| Gene annotation input | `genome.softmasked.fa` | Classified TE + tandem repeats + DUST; Unknown excluded |
| Unknown-inclusive input | `genome.softmasked.all_interspersed.fa` | Same layers plus Unknown; requires `--all-interspersed` when configuring the run |
| Classified TE intervals | `te.mask.bed` | 0-based half-open interval union |
| Unknown intervals | `repeat_unknown.bed` | Kept separately, not evidence of non-TE |
| Fragment annotation | `te_fragments.gff3`, `mask_sources.tsv` | Homology fragments, not full-length insertions/copy counts |
| Reusable reference library | `library.fa`, `family_provenance.tsv` | Preserve both; register the FASTA in a new reference-only run |
| Retained ET lineage | `parents.tsv`, library QC tables | Distinguish refined consensuses, fallback originals and low-copy originals |
| E structural candidates | `edta/native/intact.gff3` | Upstream structural evidence, separate from homology fragments |
| H structural candidates | `heliano/native_sites.tsv` | Original sequence IDs; 1-based closed coordinates; schema JSON accompanies new exports |

Use the target gene-prediction tool's documented handling of lowercase bases. Unknown-inclusive masking is a sensitivity choice, not an automatic upgrade. CDS overlap is an audit signal: a gene annotation can include TE genes or captured fragments. Do not interpret every overlap as erroneous masking. Layer counts overlap; only interval unions give total masked bp.

## One explicitly selected delivery

After a branch export is complete:

```bash
teflow select --config /data/project/run.local.json --branch edta \
  --policy te_primary --output /data/deliverables/run-edta \
  --reason "EDTA baseline selected for this genome annotation"
```

The new directory contains a consistently named softmasked FASTA, BED, library, fragment GFF3 and provenance, plus `selection.json` and `SELECTION.md`. It never runs discovery, replaces old results, or selects a biological winner. A complete selected branch may be delivered even if a separate optional branch failed. Existing output directories are refused.

Default relative symlinks depend on the source results remaining available. Add `--mode copy` for a portable delivery or Windows without symlink privileges; this copies the selected genome and may require substantial disk space. The policy is always explicit. Requesting an inclusive FASTA that was not generated fails rather than substituting another policy. Source validation uses completed-stage existence/metadata checks, not a fresh whole-genome checksum audit. `source_manifest.json` describes the original branch, not the smaller delivery folder.

## ET retention and the Arabidopsis example

The completed 0.6 TAIR10 run had 732 E entries. ET retained 223 entries from **215 unique E parents**: 76 refined consensuses, 139 original-input fallbacks and eight low-copy originals. Thus **517** E parents had no retained descendant. Counts of ET sequences cannot substitute for counts of unique input parents.

`teflow report` now reads provenance, the retained parent map and E's `mask_sources.tsv`. It reports the number of missing parents, the union of classified-TE E hits attributed to those parents, and the part exclusive of retained-parent E hits. These are E-annotation lineage summaries, **not** E-minus-ET genomic coverage or false-negative estimates. Missing files produce unknown/null coverage, never zero. The compact historical feedback cannot independently supply all genomic coverage inputs.

TAIR10 classified-TE coverage: E 15,016,254 bp; ET 5,335,368; H 3,502,355; I 13,589,107; EH 16,409,707, on 119,146,348 selected bp. EH−E net coverage is 1,393,453 bp; EH-only union is 1,397,240 bp and E-only union 3,787 bp. The earlier 1.24 Mb statement belongs to an earlier run, not this run or a different definition of the same result.

These data support describing completed outputs. They do not establish accuracy rankings, full insertion catalogs, or cross-species validation. Keep the chosen library and its tool/database provenance for subsequent annotation; even a fixed-library rerun needs verification of parameters, coordinate sets and producer versions.

## Interrupted exports and disk use

New branch exports are built in hidden `.branch.partial-*` sibling directories and renamed into place only after the branch manifest is written. Failure leaves the partial directory for diagnosis; replacement preserves an old directory as `.branch.previous-*`. Sample-level comparison still uses a final manifest plus stage completion as its completion contract. Hidden partial/previous directories are excluded from that manifest. Readers should require the relevant completed stage, as `select` does.

No automatic deletion/compaction is provided. Input copies, upstream scratch, `.align` files and extra masked FASTAs can dominate disk use; reflink is filesystem-dependent. Plan free space explicitly and retain the original work/results while selections use links. Never delete registered artifacts to make room for a running or resumable project.
