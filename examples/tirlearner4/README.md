# TAIR10 hAT review sites

`hat_watchlist.tsv` contains 59 distinct raw hAT intervals from the completed experimental TAIR10 v3/v4 comparison of 2026-11-07: 5 shared, 52 v3-only and 2 v4-only. It contains coordinates and descriptive overlap evidence, not sequences or labels of biological truth.

Coordinates are BED-style, zero-based, end-exclusive. `alias` is the experimental normalized sequence ID (`s000001` … `s000005`); `chrom` is the original nuclear chromosome ID. Use this table only with that experiment's genome and checkpoint files. `site_id` uniquely identifies a row; aliases repeat across sites on the same chromosome.

Eleven rows are prioritized because they had a v3 final DTA hit and no v4 final RepeatMasker hit. All remaining rows remain comparison controls, not negatives. Final whole-library differences cannot be assigned solely to TIR-Learner because other discovery components also varied.

Run the read-only `scripts/audit_tir_checkpoints.py` with existing intermediate files as described in `docs/SERVER_TIR4_v1.1_zh.md`. Missing checkpoint evidence is reported as unavailable. The table is a targeted diagnostic sample, not a sensitivity/precision benchmark.
