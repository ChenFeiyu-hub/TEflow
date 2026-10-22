# Validation status: 0.4.0 / 2026-10-16

## Engineering verification

| Check | Observed result | Scope |
|---|---|---|
| Windows unit suite | 103 discovered; 91 passed, 12 platform skips | Portable parsing, evidence, configuration, packaging lookup and launcher contracts |
| Linux unit suite | 103 discovered; 102 passed, 1 optional skip | Adds process/lock, shell and timeout contracts; optional real-micromamba test not run |
| Public CLI lifecycle from source | Pass | Actual Snakemake 9.27.0 with deterministic synthetic upstream tools |
| Existing multi-branch integration | Pass | Migration, seven configured branches, independent exports, coordinate/QC/evaluation contracts, immutable resume and legacy shell compatibility |
| Wheel installed outside checkout | Pass | Isolated virtual environment; runtime code/recipes resolved from site-packages, not `PYTHONPATH` or a source override |
| sdist → wheel → installed lifecycle | Pass | Confirms source-distribution asset inclusion and matching runtime fingerprints |
| Release source inventory | Checked during packaging | Source hashes and bounded source bundle; no real genomes/databases |

The public CLI fixture checks generic genome-only initialization, read-only planning, input/dependency checks without freeze, dry-run without discovery, target-stage execution, final exports, completed-stage reuse with `--resume`, status, feedback packaging, disabled-target rejection, and refusal after output tampering. It also imports the TEtrimmer/TE-Aid wrappers using isolated Python (`-I -S`, initially no teflow installed on its import path) and verifies the HiTE probe bind path using a stubbed container exec. No real container is launched. Additional unit cases check failed-probe/failed-exec propagation, preserved scientific settings during configuration forks, and Slurm budgets.

The tests use a real scheduler and mocked discovery tools. No EDTA/TEtrimmer/HELIANO/HiTE whole-genome analysis was launched for 0.4.0. No tool dependency upgrade or new biological selection algorithm is introduced. Local Linux validation uses the existing Snakemake installation in a dedicated environment; the wheel test uses a separate venv sharing that tested scheduler dependency set, not a fresh download of all external tools.

The source release includes `scripts/release_manifest.py` to refresh/verify the inventory after intentional changes. Wheels contain the same runtime Python and recipe content as the checkout. File paths and distribution archive timestamps can differ; content identity is checked, not equality of wheel archive hashes across separate builds.

GitHub Actions is configured for Windows/Linux units, scheduler fixtures, build/metadata checks and installed-wheel validation. **Remote CI has not run in this delivery, and nothing has been published to GitHub/PyPI.** Local distributions were built with setuptools' PEP 517 backend and pip; no local `twine check` result is claimed.

## Existing real-data evidence, retained separately

The Arabidopsis v022 E, ET, H, I and EH branches completed in the recorded server environment. H uses native HELIANO representatives with EDTA-assisted cleanup. Conditional R/RE and HELIANO official consensus lack real-genome validation in this project. [HELIANO_STATUS](HELIANO_STATUS_2026-10-16.md) gives the measured H/EH results and limitations.

The independent 0.3.1 selected-locus boundary review reproduced between local and server runs: 16 commands completed; 18 scientific outputs were byte-identical; five tables were recomputed from raw data. This is reproducibility evidence for those cases, not biological truth or an estimate of global accuracy. Earlier version-specific test reports describe those versions only.

The remaining engineering acceptance is a small public-CLI fixture run in the user's server environment and remote CI after pushing the chosen repository. Neither requires rerunning the completed Arabidopsis discovery analyses. Broader species benchmarks remain a separate validation task, not a prerequisite for packaging this transparent orchestration framework.
