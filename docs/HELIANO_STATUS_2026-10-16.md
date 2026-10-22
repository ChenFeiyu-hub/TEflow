> Historical run-specific evidence. The later 0.6 run has different E/EH coverage; see [RESULTS_GUIDE](RESULTS_GUIDE.md).

# HELIANO: current Arabidopsis evidence and software role

The `at_compare_v022` H and EH branches completed. This is evidence of operational success in the tested environment, not an estimate of biological accuracy. H uses EDTA-assisted non-HLE nested cleanup; it is not an independent whole-TE baseline. The tested HELIANO mode is `native_representatives`. The implemented `official_consensus` option remains off and lacks a real-genome validation in this project.

## Observed outputs

| Item | Result |
|---|---:|
| H representative sequences | 233 |
| H representatives with RepeatMasker hits | 231 |
| H homology fragments | 11,239 |
| H TE interval union | 3,347,967 bp |
| H coverage outside E | 1,292,699 bp |
| E TE interval union | 16,096,921 bp |
| EH TE interval union | 17,328,265 bp |
| EH gained intervals relative to E | 1,235,499 bp |
| E intervals absent from EH | 4,155 bp |
| H representatives with host-protein QC flags | 77 |

The selected nuclear genome is 119,146,348 bp, excluding Mt/Pt. “Gained intervals” is directional set difference; the net EH−E size increase is 1,231,344 bp. These are aligned coverage values, not confirmed TE truth or family counts. The 233 entries must not be described as 233 verified TE families or 233 full-length insertions. Host-protein flags trigger review and are not proof of contamination, especially for possible gene capture.

All 233 native coordinate/strand reconstructions were checked. The EDTA-assisted mask was reproduced, including 125,676 masked positions; 153 candidates were affected, 19 had more than half their sequence masked. This can remove useful terminal evidence in some representatives.

## What detailed review resolved

Protein and terminal/boundary reviews focused on selected large-contribution or ambiguous candidates. H0139 encloses multiple gene/CDS regions; expanded protein evidence overlaps much of their CDS. Removing those segments would not automatically establish a reliable residual TE. H0134 has repeated terminal patterns but weak interior homology among the selected loci; its low-complexity/AT-rich composition matters. The selected candidate loci were retrieved through terminal evidence, so their repeated terminal patterns are not an independent validation.

The v0.3.1 four-group, 15-locus boundary analysis reproduced between local and server runs: 16 commands completed, and 18 scientific outputs were byte-identical despite the recorded BLAST build difference. Five summary tables were independently regenerated from the raw outputs. This validates the selected analysis' reproducibility, not the biological truth of the candidates. Weak interior homology also does not prove a non-TE origin, because cargo diversity and gene capture remain possible.

Evidence sources: `five_branch_summary.tsv` and `E_EH_regional_comparison.tsv` from the v022 final review; the received `at_v022_boundary_v031.20261015T192819Z.258328.feedback.tar.gz` (SHA256 `8d517cda4a32488db1c6febf7771acdc59f3900f5b4a641ad1a3eb8fb3517b77`); the independent server reproduction audit. The release does not bundle private genomes or full real-data evidence archives.

## Engineering decision

Retain HELIANO as an optional supplementary branch, with its own library, native sites, QC and uniform RepeatMasker export. Retain E+H as an explicit comparison/assembly output, using the same exact/RC same-class rule. No automatic “best branch” selection is introduced. Current candidate uncertainty does not block the engineering release; additional biological adjudication can proceed independently when needed. These selected reviews cannot estimate HELIANO's global false-positive rate.
