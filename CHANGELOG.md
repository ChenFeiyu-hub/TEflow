# Changelog

## 1.0.0 — 2026-10-22

- First single-species public interface release; keeps 0.7 discovery parameters, merge rules and masking defaults.
- Add explicit branch/policy selection, delivery provenance and missing-parent ET lineage/coverage reporting.
- Publish branch exports from staged directories; retain failed/previous directories and exclude them from final manifests.
- Show inherited CPU affinity and pool scope; document coordination between work roots.
- Validate class vocabulary before remapping; explicitly bind/set HiTE temporary directories across cleanenv; tolerate unavailable optional identity caches by direct reading.
- Fix single-CPU test assumptions; extend source/installed-wheel fixtures for selection, fault handling and lineage reporting.
- Update actual historical server evidence, results guide, upgrade/acceptance commands and confirmed Feiyu Chen citation metadata.
- Does not add hard memory enforcement, multi-species scheduling, automatic best-library selection or new accuracy claims.

# 0.7.0rc1 — 2026-10-20, release candidate

- Supervise Snakemake and persist preflight, dispatch, success/failure/cancellation and unresolved-cleanup outcomes. Store and stream the scheduler log. Stage completion and launch completion remain distinct.
- Add `run-preview`, `cancel`, `logs`, `runtime-summary` and read-only Markdown/JSON/TSV `report`. A request file targets one verified live launcher attempt; no process from a saved PID is signalled. Workers clean up their own external command groups. Resume is explicit and unchanged-source only.
- Sample immediately after command spawn and every 250 ms during the first ten seconds of each command, then at the configured interval. Record sample counts, descendant coverage, gaps and monitor errors. Observations remain approximate and never change resource budgets automatically.
- Include launch/control evidence in feedback, preserve old-run report compatibility and expose TEtrimmer retained origins and scientific limitations without selecting a winning branch.
- Record the completed 0.6 five-branch Arabidopsis server run separately from new RC checks. Add cancellation/resume/foreign-process isolation fixture and bounded RC server acceptance. No TE algorithms, discovery parameters, mask defaults or merge rules changed.

# 0.6.0 — 2026-10-17, single-species engineering package

- Focus on one species; retain serial default and add explicit branch concurrency, per-stage CPU/memory/I/O requests, an exclusive local controller, distinct CPU leases, private scratch directories, sampled process-tree RSS and a node-memory admission gate. Independent branches continue after a failure; the complete-run target still fails. Memory enforcement is observe-only; production cgroups and multi-species scheduling are deferred.
- Use declarative branch/probe registration while preserving 312 pre-change graph/tool configurations in a golden contract. Avoid moving working adapters only for architectural symmetry.
- Version classification mapping at 0.3. Correct RM-style TIR aliases including MULE-MuDR and CMC-EnSpm in class summaries; retain raw classifications and report root-only mappings. Discovery, libraries, genome intervals and default mask membership are unchanged.
- Append strand-normalized consensus coordinates, original coordinate tokens, actual library length and diagnostic status. Actual `.out` evidence includes negative remaining lengths and library-length disagreements; retain these, omit unverified GFF3 Target attributes and never infer full-length insertions from them.
- Add sample taxon_group for HiTE --plant (legacy default plant), coverage_layers.tsv with interval unions, and explicit additional Unknown-inclusive softmasked FASTA/BED.
- Add offline reevaluate and read-only audit-results; original runs remain untouched. Old export-column prefixes remain stable; new columns are appended.
- Freeze once in the public launcher; DAG parsing uses the light config/source check. Cache large-file identities by filesystem metadata, use safe reflink/copy staging, and make status metadata-only. Internal provenance remains compatible; there is no manual development/upload checksum gate or feedback .sha256 sidecar. Download verification remains.
- Distinguish closing logind sessions from active/online sessions in login-status. Preserve the historical strict B3 result and the separate experimental runtime package.
- Include source, wheel/sdist support, a bounded single-species server acceptance command and updated docs. New real-genome parallel execution and remote GitHub CI remain pending.

# 0.5.0.dev2 — runtime acceptance repair, unreleased

- Query loginctl properties with repeated `-p` arguments, preserving explicit empty Sessions and distinguishing unreadable state from disabled linger. Add read-only `login-status`.
- Budget finite extra virtual address space above measured VmSize instead of a fixed total ceiling; keep the 128 MiB cgroup limit, zero swap, finite allocations and inherited rlimits. Add large-virtual-baseline success/OOM controls.
- Preserve exception class, traceback and process memory diagnostics so an empty `MemoryError` message cannot hide the failure type.
- Save a successful logout attempt's identity with `--attempt-file`; verify the receipt on reconnect, and reject a missing handle with an actionable message.
- Retain dev1 evidence and frozen artifacts. Local pass is not target-server acceptance, and no TE analysis behavior or production batch integration is changed.

# 0.5.0.dev1 — unreleased development candidate

- Add the independent `teflow_runtime` experimental package and `teflow-runtime-check` entry point, plus a source-checkout acceptance command requiring no reinstall.
- Exercise real, bounded Linux user services: successful child, child OOM hidden by a successful parent, group OOM, ordinary SIGKILL, timeout, cancellation, cleanup, persisted-handle reattachment and ownership refusal.
- Check actual cgroup memory/swap limits and CPU affinity before payload allocation; preserve file logs, kernel counters and service identity outside the worker resource group. Logout proof requires a continuous observed zero-session interval, not merely a linger setting.
- Prepare the dedicated GitHub repository, repository URLs, LF normalization, explicit development status and separate runtime/data ignore rules. CI verifies the committed source inventory instead of regenerating it during validation.
- Existing TE discovery, library assembly, scientific parameters and production execution remain unchanged. No multi-species scheduler, automatic retry, production memory enforcement or public release is claimed.

# 0.4.0 — 2026-10-16

- Add generic `init`, combined `check`, native `run`, settings-preserving `fork-config`, `capabilities` and `assets` commands; retain legacy CLI/shell entry points.
- Bundle runtime recipes in wheels and sdists, resolve assets explicitly, and hash Python/recipes consistently across source and installed package.
- Preserve freeze/probe/cache semantics, Slurm budget checks and heavy-I/O serialization; add launch receipts and explicit Bash wrapper invocation independent of executable file bits.
- Separate Conda environment prefixes from wrapped interpreter arguments for dependency/TE-Aid probes.
- Add installation, upgrade, command and maintainer contracts, HELIANO evidence status, contribution/issue/PR guidance and distribution CI.
- Scientific discovery parameters, library merge policy, QC decisions and optional pCRE behavior are unchanged. Prior frozen runs require their original source; no genome rerun was launched for this release.

# 0.3.1 — 2026-10-16

- Add a bounded, independent selected-locus boundary review. Freeze reference DNA, coordinates, explicit selection reasons and optional gene/CDS context; call published BLASTn and optional short-core MAFFT and DUST.
- Validate all reported alignment bases and coordinates, union only paired columns, separate orientations and core/internal/flank comparisons, and expose self controls. Optional DUST-disabled sensitivity remains a separate output, never an automatic acceptance rule.
- Preserve immutable review inputs, command/exit receipts, binary/package hashes, failure records and compact portable feedback. No TE discovery, inferred insertion count, family merging or annotation DAG changes.
- Validate four Arabidopsis comparison groups (15 locus records) on real BLAST/MAFFT/DUST tools. The selected candidates do not provide broad internal homology supporting full-length copies; this is evidence assessment, not a biological accuracy benchmark.

# 0.3.0 — 2026-10-16

- Position the core as a general TE/genome annotation workflow. New configs disable optional promoter analysis; init-server defaults to baseline. Legacy missing-field behavior is preserved.
- Register requested RepeatMasker alignment artifacts and verify legacy auxiliary origins without rewriting old receipts or repeating analyses.
- Add independent candidate evidence preparation, exact raw-alignment verification, final/raw family linkage, native/fragment flanks and GTF/GFF3 gene/transcript context.
- Add bounded expanded DIAMOND QC with coordinates, frames and validated BTOP, plus separate reviewed catalog/masking-library exports. No automated host-overlap filtering or genome-mask replacement.
- Provide compact review packaging, source verification, a generic genome config and a server handoff for the 11-case Arabidopsis review. See docs/TEST_STATUS_v0.3.md for actual test and biological validation limits.

# 0.2.2 — 2026-10-15

- Isolate each TE-Aid subprocess cwd under its own output directory, including Linux fork workers. Verify the pinned TEtrimmer 1.7.2 source hashes; preserve installed files, biological arguments, stdout/stderr and return-code handling.
- Add a single-case, checksum-pinned recovery of `at_compare_v021`. Independently reproduce the affected 4,829-bp consensus from its 12-sequence proof alignment, re-audit all 756 input families and 252 retained sequences, and import verified E/RM/ET products into a new run without repeating discovery.
- Keep the original failed run and error record intact. New receipts explicitly distinguish the actual original producer from the future isolated command and label the accepted cleanup warning. This recovery does not certify unavailable ORF table headers or establish biological accuracy; all other errors remain blocking.
- Preserve an unchanged prepared scheduler marker during successive imports, avoiding unnecessary rescheduling of already imported upstream stages.
- Add Linux concurrency/fork tests and a real-Snakemake recovery fixture whose TEtrimmer command fails if recomputation is attempted. See docs/TEAID_RECOVERY_v0.2.2_zh.md for evidence, limits and server commands.

# 0.2.1 — 2026-10-14

- Recognize the exact official Zenodo HiTE image by size and SHA256, recording release label 3.3.3 separately from its CLI version 3.3.2. Do not treat arbitrary 3.3.2 images as equivalent.
- Check the case-sensitive `Ninja` clustering executable used by HiTE, and exercise its real interface on three short aligned sequences. Do not substitute the unrelated `ninja` build tool.
- Preserve dependency-probe error details inside doctor.json and emit actual configured CLI version plus image identity in HiTE library provenance.
- Add a guarded new-run preparation script that preserves old configurations, frozen manifests, databases, environments and branch options; rebind the HiTE wrapper/probe to the new repository.
- This is an acceptance/provenance repair. It does not change TE discovery parameters or establish full-genome HiTE validity. See docs/HITE_RECHECK_v0.2.1_zh.md for measured tests and remaining server checks.

# 0.2 — 2026-10-13

- Add explicit schema-2 branches: EDTA, EDTA→TEtrimmer, HELIANO, HiTE, E+H, and conditional reference-only/reference+EDTA routes. Each branch can export independently; incomplete comparisons cannot acquire a final receipt.
- Audit HELIANO 1.3.1 native 1-based coordinates by sequence round-trip. Default to native sequence models; retain optional official consensus with explicit 50-bp boundary caveat. Clean nested EDTA non-HLE hits using position-preserving N masks and separate before/after hashes.
- Run HiTE 3.3.3 from a separately hashed Apptainer image; validate confident-library output and logs, preserve separate raw retry attempts, and exclude low-confidence entries from the public mapping library.
- Add shared sequence/protein/domain QC, exact/RC alias assembly with multiple parents, correct MITE classification, regional reference agreement, branch discordance and per-promoter valid-window counts.
- Separate disposable Snakemake markers from authoritative receipts; archive all doctor attempts, clean process groups on TERM/HUP/INT/timeout, constrain Linux CPU affinity, and refuse unresolved orphan resumes.
- Import only verified completed EDTA/RM stages into new runs. Add scoped stale-lock review, plan/status commands, conditional dependency installation and a versioned server handoff.
- Add regression and real-Snakemake synthetic integration coverage. Real HELIANO/HiTE/clean TEtrimmer whole-genome acceptance remains pending; this release makes no comparative biological accuracy claim.

# 0.1.4 — 2026-10-12

- Validate TEtrimmer 1.7.2 original-sequence fallback by parent identity, exact sequence and full-copy evidence; report actual retained length separately from attempted extension length.
- Retain strict failure on full or truncated nonempty error evidence; emit audit and lineage tables before quarantine.
- Prepare, test and lock the TE-Aid RepeatPeps protein database offline before production; add a real BLAST preflight.
- Launch code explicitly from the selected versioned repository; include audit and import provenance in feedback bundles.
- Provide restricted v02 -> v03 recovery with verified EDTA/RM artifact copies, fresh TEtrimmer and immutable original results.
- Add compact architecture review and current validation documents.

# Changes

## 0.1.3 — 2026-10-10

Repair fix2: the server solved the downgrade successfully but the transaction guard omitted `python-tzdata`, an explicit dependency of the selected pandas 2.3.3 build. Allow it alongside pandas and pytz. Add a regression fixture reduced from the actual successful server plan; unrelated package changes remain blocked. No environment rebuild is required.

Repair script correction (fix1, same day): `--freeze-installed` also freezes the requested pandas downgrade target. Replace it with an explicit plain-text constraint file containing every installed non-pandas package's version/build; retain the transaction guard. Surface solver JSON errors in the repair log. A real micromamba dry-run regression against tiny offline metadata reproduces the original failure and verifies that the corrected request only replaces pandas. The original release archives remain unchanged; distribute the corrected script separately.

The first Arabidopsis server pilot reached TIR-Learner 3.0.7 and failed at its positional `Series[0]` access with pandas 3.0.6. Pin `tir-learner=3.0.7` and `pandas=2.3.3` in the EDTA recipe. Add a synthetic pandas row-indexing check to production doctor so working CLI/dependency probes cannot hide this specific incompatibility. Include the previously applied RepeatMasker `-v` doctor correction.

Provide a bounded server repair script with solver-only mode, a transaction guard, configuration/package-spec backups, separate v02 environment-lock snapshots, and a fresh `at_pilot_v02` dry-run. Preserve v01 configuration, locks and outputs; do not change TIR-Learner source, bypass failed TIR discovery, or migrate incomplete cached products across environments. Full-genome validation after repair remains pending.

## 0.1.2 — 2026-10-08

Remove redundant `blast=2.17.0` requirements from the TEtrimmer and masking environments. The published RMBlast 2.17.0 package supplies the required standard BLAST executables and dustmasker; co-installing the separate BLAST 2.17.0 package has incompatible Entrez Direct constraints and overlapping files. Add installed BLAST/RMBlast CLI probes to the TEtrimmer source installer.

Verified the actual RMBlast package file inventory and successful full Conda runtime dry runs for TEtrimmer and masking on local Linux x86_64. See the dated v0.1.2 installation note for exact scope and solver evidence. Database setup, installed execution and real-genome validation remain pending server acceptance.

## 0.1.1 — 2026-10-08

Fix the TEtrimmer runtime recipe: replace the Bioconda TEtrimmer/PfamScan dependency metapackages with explicit runtime dependencies, BioPerl core, and checksum-verified unchanged TEtrimmer 1.7.2 / PfamScan 1.6 source installation. Preserve RepeatModeler 2.0.9, RepeatMasker 4.2.4, and RMBlast 2.17.0. Include seaborn and Pillow, which are imported by the upstream source.

Add single-environment bootstrap selection, per-attempt logs, fresh dry-run targets, source-file provenance checks, and installer safety/regression tests. Source installation checks Perl imports and actual CLI entry points. Full runtime solving/installation and genome execution remain server acceptance steps; see the dated installation note.

## 0.1.0 — 2026-09-28

Initial server-pilot implementation: isolated environment recipes, read-only genome/annotation audits, conservative host CDS extraction, Snakemake scheduling, EDTA and TEtrimmer adapters, controlled RepeatMasker branches, TRF/dust tracks, original-coordinate exports, fingerprinted stage receipts, and bounded feedback archives.

Local verification covers software contracts and synthetic orchestration. Real-genome annotation, environment installation acceptance, independent biological evaluation and selection of a pCRE mask are pending server execution.
