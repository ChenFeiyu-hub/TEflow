# Maintainer extension contract

This project orchestrates published tools. Add features at existing boundaries; do not couple the core to expression data, pCRE labels or motif prediction. The following contract is documented for internal development; arbitrary third-party plugin loading is not implemented.

| Boundary | Current modules | Required contract |
|---|---|---|
| User commands | `cli.py`, `project_cli.py`, `review_cli.py`, `boundary_cli.py` | Explicit inputs, structured output, actionable failures; no hidden installs or launches |
| Recipe lookup | `assets.py`, build hook in `setup.py` | Same recipe bytes in source, sdist and wheel; missing/invalid overrides fail |
| Workflow graph | `registry.py`, `branches.py`, `workflow/Snakefile` | Register branch, parents, tools, stage names and exports; reject missing parents |
| Single-species resources | `resources.py`, `resource_pool.py` | Keep TE policy outside the generic lease/observation pool; preserve ownership, independent CPU IDs and explicit reservation accounting |
| Run control and summaries | `control.py`, `launcher.py`, `reporting.py` | Attempt-scoped cooperative stop, durable final states, no stale-PID signals; reports never dispatch or choose libraries |
| Tool adapters | `adapters/`, `stages.py` | Version-specific argv, expected raw files, parsed canonical outputs, audit evidence |
| Execution and caches | `runtime.py`, `launcher.py` | Freeze input/tool/recipe/database hashes; completed outputs verified; process cleanup and resource budgets |
| Experimental runtime backend | Separate `teflow_runtime` package | Generic argv/resources/attempt identity only; no TE or pCRE imports; explicit acceptance status; not yet connected to production commands |
| Data formats and QC | `formats.py`, `library_qc.py`, `evaluation.py` | Sequence identity, coordinates, classifications and provenance; evidence flags are not automatic biological rejection |
| Optional reviews | `candidate_review.py`, boundary modules | Separate output directory; explicit selected inputs; no mutation of old libraries/annotation |

## New branch or tool version

1. Record the publication/source, upstream version, license and exact installation/image identity in `docs/THIRD_PARTY.md` and an environment recipe or explicit container configuration.
2. Register the branch in `registry.py`, including parents, prefix and required tools, then provide stage/tool mapping and resource kind. Add strict parameter validation and vocabulary coverage in `classification.py`; do not accept arbitrary shell text as parameters. Expose validation maturity in `capabilities`. A registry entry alone does not implement an adapter or install dependencies.
3. Implement a bounded adapter returning canonical outputs and an audit record. A tool exit of zero with a missing/invalid expected artifact is failure. A legitimate zero-candidate result has an explicit completion receipt and valid empty-output semantics.
4. Preserve representative ID mappings and source lineage. Keep structural native loci separate from RepeatMasker homology fragments. BED uses 0-based half-open intervals; GFF3 uses 1-based closed intervals. Normalize seqids only through the recorded mapping.
5. Register every output needed downstream, including raw alignment files, in integrity receipts. Assembly remains full-length exact/RC alias folding within the same class; alternative clustering or approximate merging requires a new explicit protocol.
6. Add meaningful tests for malformed output, valid zero results, reverse-strand/coordinate roundtrip, retry/cache refusal after changes, and the actual scheduler DAG using a deterministic mock tool. Test installation probes with a tiny real input before expensive validation.
7. Report separately: interface tests, small real-tool execution, real-genome completion, and biological accuracy evidence. One species or selected-candidate review cannot establish general precision/recall.

## Changes to data contracts

Configuration schemas 1/2 remain accepted; unknown fields are rejected. Add a schema version when changing field meaning. Version table/file semantics explicitly before introducing breaking changes; a new column must not silently change coordinate or evidence meaning. `capabilities.interface_version` versions the new CLI metadata contract only. Do not treat undocumented Python internals as a stable third-party SDK.

## Package and CI requirements

The root `workflow/`, `scripts/`, `envs/` are canonical. The build hook copies them into the wheel's `teflow/_assets/`; never maintain a second manually edited copy. Run `tests/integration_cli.py --installed` in a separate environment, with `PYTHONPATH` and `TEFLOW_REPOSITORY` unset and outside the checkout, to detect accidental source dependencies. Check source/sdist/wheel payload equality directly; there is no mandatory SHA-256 release gate.

Source bootstrap/recovery scripts remain available for their documented situations. New features should use the unified command interface; historical emergency repair scripts are not general upgrade hooks. Avoid silently modifying shared Conda environments, databases or completed analysis to repair an installation.

Build customization follows [setuptools' command extension contract](https://setuptools.pypa.io/en/latest/userguide/extension.html); source inclusion uses [Python packaging's source-distribution guidance](https://packaging.python.org/en/latest/guides/using-manifest-in/).
