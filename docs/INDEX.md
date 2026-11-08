# Documentation index

Current 1.1.0rc1 instructions:

- [Install](INSTALL.md), [commands](COMMANDS.md), [upgrade](UPGRADING.md)
- [Results and explicit delivery choices](RESULTS_GUIDE.md)
- [TIR v4 CPU default and v3 backup](TIR_BACKENDS.md), [上游规则审计 / 中文](UPSTREAM_TIR4_AUDIT_2026-11-08.md)
- [服务器解压、有限封装验收与已有中间结果审计](SERVER_TIR4_v1.1_zh.md)
- [Current validation](TEST_STATUS_v1.1.md)
- [2026-11-08 服务器封装验收通过与 hAT 检查点复核 / 中文](TIR4_SERVER_REVIEW_2026-11-08_zh.md)
- [Extension contracts](EXTENDING.md), [GitHub release process](GITHUB_RELEASE.md), [upstream licenses/citations](THIRD_PARTY.md)

Future work (not implemented production capabilities; the earlier plan's “1.1” label has been superseded by this TIR packaging milestone):

- [多来源 TE 注释依赖与不确定性：首轮研究推进方案 / 中文](research/FIRST_ROUND_2026-11-08_zh.md)
- [Earlier multi-species engineering plan / 中文](MULTISPECIES_PLAN_v1.1_zh.md)
- [Five-species input formats and preparation / 中文](MULTISPECIES_INPUTS_zh.md), [editable input template](../examples/multispecies/inputs.template.json)

Historical evidence and implementation contracts:

- [1.0 changes and boundaries](RELEASE_v1.0.md), [external-review decisions / 中文](EXTERNAL_REVIEW_RESPONSE_v1.0_zh.md), [1.0 validation](TEST_STATUS_v1.0.md), [1.0 server handoff](SERVER_v1.0_zh.md).
- [0.6 single-species design](SINGLE_SPECIES_v0.6.md), [0.7 supervisor contract](RELEASE_CANDIDATE_v0.7.md): retained underlying designs; 1.0 changes take precedence where specified.
- `PROTOCOL_v0.1.md`, `PROTOCOL_v0.2.md`, `PROTOCOL_v0.3.md`: scientific scope as introduced; later corrections are recorded in versioned documents.
- `TEST_STATUS_*`, `validation/`: dated tests, not interchangeable certification. The completed 0.7 target-server acceptance is recorded in `validation/server_v0.7_2026-10-22.json`.
- `RUNTIME_CONTRACT.md`, `RUNTIME_ACCEPTANCE*`: experimental systemd fixtures and earlier batch planning; these are not production hard-memory enforcement.
- `INSTALLATION.md`, `INSTALL_FIX*`, `REPAIR_*`, `TIR_PANDAS*`, `TETRIMMER_RECOVERY*`, `TEAID_RECOVERY*`, `HITE_RECHECK*`: previous installations and incident recovery.
- Older `SERVER_*` / `DELIVERY_*`: dated handoffs; do not use them as a current upgrade checklist.
- `HELIANO_STATUS_2026-10-16.md`, `BOUNDARY_REVIEW_v0.3.1.md`: real-data evidence from earlier runs; current 0.6 coverage numbers are in the results guide.

Historical checksum commands remain in those records. New source/upload/feedback handling requires no SHA-256 step. External downloaded tools/databases retain integrity checks.
