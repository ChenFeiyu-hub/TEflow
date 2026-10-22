# Third-party tools and attribution

This repository contains orchestration code only. Tool authors retain authorship of the underlying methods. Databases and third-party packages are installed separately, under their respective licenses. No upstream source, TE library, genome assembly, or annotation is relicensed by this repository's MIT license.

| Component | Intended version | Primary source / citation |
|---|---|---|
| EDTA | 2.3.0 | [Versioned source and integrated components](https://github.com/oushujun/EDTA/tree/v2.3.0); [Ou et al., 2019](https://doi.org/10.1186/s13059-019-1905-y) |
| TEtrimmer | 1.7.2 | [Versioned source](https://github.com/qjiangzhao/TEtrimmer/tree/v1.7.2); [2025 paper](https://www.nature.com/articles/s41467-025-63889-y) |
| RepeatMasker | 4.2.4 | [Official download/release notes](https://www.repeatmasker.org/RepeatMasker/); [source](https://github.com/Dfam-consortium/RepeatMasker) |
| RepeatModeler / RepeatClassifier | 2.0.9 | [Versioned source](https://github.com/Dfam-consortium/RepeatModeler/tree/2.0.9); [Flynn et al., 2020](https://doi.org/10.1073/pnas.1921046117) |
| RMBlast | 2.17.0 | [Official distribution](https://www.repeatmasker.org/RMBlast.html) |
| TRF | 4.10.0 | [Official source](https://github.com/Benson-Genomics-Lab/TRF) |
| dustmasker / BLAST+ | 2.17.0 | [NCBI BLAST source](https://github.com/ncbi/ncbi-cxx-toolkit-public) |
| Snakemake | 9.27.0 | [Documentation](https://snakemake.readthedocs.io/en/stable/); [package](https://pypi.org/project/snakemake/9.27.0/) |
| HELIANO / heliano_cons | 1.3.1 bundle / consensus banner 1.0.2 | [Versioned source](https://github.com/Zhenlisme/heliano/tree/v1.3.1); [published method](https://pmc.ncbi.nlm.nih.gov/articles/PMC11417382/) |
| HiTE | 3.3.3, official container | [Versioned instructions](https://github.com/CSU-KangHu/HiTE/tree/v.3.3.3); [published method](https://www.nature.com/articles/s41467-024-49912-8) |
| DIAMOND | 2.1.11, optional QC | [Official source](https://github.com/bbuchfink/diamond) |
| HMMER hmmscan | 3.4, optional QC | [Official documentation](http://hmmer.org/documentation.html) |
| Apptainer | server installation version | [Official documentation](https://apptainer.org/docs/user/latest/) |
| Pfam | explicit release; pilot example 37.0 | [Official release directory](https://ftp.ebi.ac.uk/pub/databases/Pfam/releases/Pfam37.0/) |
| PfamScan | 1.6, checksum-locked official sources | [EBI archive](https://ftp.ebi.ac.uk/pub/databases/Pfam/Tools/PfamScan.tar.gz); [upstream package recipe](https://raw.githubusercontent.com/bioconda/bioconda-recipes/master/recipes/pfam_scan/meta.yaml) |
| Dfam/FamDB | explicit Dfam 4.0 component files | [FamDB quickstart](https://github.com/Dfam-consortium/FamDB/blob/master/QUICKSTART.md); [RepeatClassifier 2.0.9 database integration](https://github.com/Dfam-consortium/RepeatModeler/blob/2.0.9/RepeatClassifier) |

The intended package constraints were checked against public interfaces/metadata on 2026-09-28. Full Linux environment solving, database configuration, executable compatibility and real-genome runtime remain server acceptance steps. Installed build identifiers, licenses and dependency versions are captured in the generated environment locks, and should be included in any methods supplement.

EDTA already invokes additional published tools, including its LTR discovery/retrieval, TIR, Helitron, SINE, RepeatModeler and classification components. Use the actual installation manifest and EDTA documentation to cite components used by a completed run. This wrapper does not imply that TEtrimmer, HELIANO or HiTE are part of EDTA itself.

TEtrimmer's main README describes releases beyond its available 1.7.2 tag/package. The adapter is intentionally tied to 1.7.2's CSV summary and final-library contract. Tag v1.7.2 resolved to commit `c16fbf669ab29f06befe57f9a7afaf013bc6cacc` during this audit. Upgrading requires new contract tests and a new run ID.

Since wrapper v0.1.1, unchanged TEtrimmer and PfamScan sources are installed from official archives with fixed SHA256 values, while Conda supplies explicit runtime dependencies. BioPerl core replaces the overly broad BioPerl metapackage dependency of the PfamScan Conda recipe. Retain both the Conda explicit lock and `tetrimmer.sources.lock.json`; neither alone specifies the entire environment. This packaging workaround does not change the upstream methods or license terms. See [installation repair](INSTALL_FIX_2026-10-08.md).

Since v0.1.2, the standard BLAST executables and dustmasker in TEtrimmer/masking are supplied by the Bioconda `rmblast` package; no separate `blast` package is requested. The actual `rmblast-2.17.0-hbfc2172_1.conda` file inventory was inspected, matching the [upstream recipe's executable tests](https://raw.githubusercontent.com/bioconda/bioconda-recipes/master/recipes/rmblast/meta.yaml). This avoids both incompatible Entrez Direct constraints and overlapping executable/library paths. Package version and executable provenance should remain part of the run manifest.

RepeatMasker searches with a user-supplied `-lib` can run without species libraries. Our broader discovery/refinement route additionally invokes RepeatClassifier, which uses classification databases. Installing only a working `RepeatMasker -lib` executable therefore does not establish that the whole workflow is ready.
