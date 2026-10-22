# 0.3.1 test and evidence status — 2026-10-16

This is the current supplement; older TEST_STATUS documents describe their own release dates and stages.

- Windows: 90 tests, 78 passed, 12 platform/optional skips. Linux: 90 tests, 89 passed, one optional real-micromamba skip. No failures. Thirteen tests target boundary-review behavior.
- Real Snakemake generic genome-only integration passed with synthetic upstream tools, optional annotation absent and promoter analysis disabled. This is scheduler/interface validation, not a biological benchmark.
- Four selected Arabidopsis groups, 15 locus records, 203,158 bp including flanks; real BLASTn 2.17.0+, MAFFT 7.526 and dustmasker 1.0.0, all single-thread. Sixteen command receipts exited zero. 125 primary HSPs plus 157 DUST-disabled HSPs were verified against frozen DNA; all four self-core controls were complete. Optional short-group MSA: seven sequences, 1,229 columns, all ungapped sequences unchanged.
- H0000134 comparisons mainly support terminals, with 0–12.5% reference interior paired coverage unchanged by disabling DUST. H0000139 interiors remain sparsely matched. These observations do not confirm complete-copy homology or reject all candidates as non-TE; no decisions or genomic masks were modified.
- Frozen 0.3.0 source: all 130 listed file hashes unchanged. See validation/tests_v0.3.1.json for fingerprints, versions and limits. Source archive excludes private environments, reference genomes and bulk results.

No new whole-genome run, no new truth-set accuracy benchmark, no automatic library splitting/merging or TE acceptance thresholds. Source code for the new audit is platform-neutral; external production tools were exercised on Linux/WSL. The server's prior BLAST build reported 2.17.1+ and is not claimed byte-equivalent to the local 2.17.0+ build.
