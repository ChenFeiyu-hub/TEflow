# Installation and first project (1.0.0)

Existing installations can use a separate source directory and their current engine: follow [the 1.0 server handoff](SERVER_v1.0_zh.md). No tool/database reinstall or old genome rerun is required for the bounded engineering acceptance. Source/upload checksum validation is not a required step; download installers retain their checks.

Production uses Linux. Windows supports input auditing, configuration and portable tests. Python >=3.10 is required for the wrapper; the tested engine uses Python 3.11 and Snakemake 9.27.0. Upstream software, genomes, databases and containers are installed separately and are not included in the Python package.

## New installation

Use an unpacked release or a Git checkout. Keep the installation and work paths free of whitespace and shell metacharacters because several upstream tools invoke shell commands internally.

```bash
export MICROMAMBA=/absolute/path/to/micromamba
TASK_ROOT=/absolute/path/to/te_project
TE_ENV="$TASK_ROOT/envs"
TE_REPO=/absolute/path/to/TEflow-1.0.0
cd "$TE_REPO"

# Solves only; it does not test pip dependencies or run the tools.
bash scripts/bootstrap_server.sh "$TE_ENV" --solve-only
# Installs the baseline engine, EDTA, TEtrimmer and masking environments.
bash scripts/bootstrap_server.sh "$TE_ENV"
```

The installer refuses to overwrite existing environments. Existing verified installations should follow [UPGRADING.md](UPGRADING.md); they do not need a fresh tool installation. Installation logs and explicit package lists are saved under the environment root. HELIANO and protein QC are optional: add `--only heliano` or `--only qc` to the solve/install calls only when enabling those features. HiTE additionally requires Apptainer and the verified SIF described in [HITE_RECHECK_v0.2.1_zh.md](HITE_RECHECK_v0.2.1_zh.md).

For wrapper-only installation into an existing compatible Python environment:

```bash
python -m pip install '.[engine]'
# Alternatively install the supplied wheel; the wheel includes workflow recipes.
python -m teflow --version
python -m teflow capabilities
```

Do not assume a PyPI release exists: use the supplied local wheel or source checkout. `engine` installs the scheduler on Linux, not EDTA/TEtrimmer/RepeatMasker. The source bootstrap script remains the environment provisioning entry; the wheel supports runtime commands without a source checkout.

## Configure a genome

```bash
teflow() { "$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow "$@"; }
teflow init --root "$TASK_ROOT" --env-root "$TE_ENV" \
  --micromamba "$MICROMAMBA" --sample-id my_plant --run-id my_plant_01 \
  --genome "$TASK_ROOT/inputs/genome.fa" --threads 32 --mem-mb 131072
CONFIG="$TASK_ROOT/my_plant_01.local.json"
teflow plan --config "$CONFIG"
```

The default is `baseline`: E and EDTA→TEtrimmer. `--profile edta` runs E alone. Gene annotation is optional: supply `--annotation genes.gff3`/GTF to derive CDS, or `--cds transcripts.cds.fa`; add `--protein-qc` for host-protein evidence. An annotation must provide the expected CDS/transcript structure, not just gene spans. Exclude organellar sequences with repeated `--exclude-seqid` arguments matching exact FASTA IDs. No exclusions are guessed for arbitrary genomes. Promoter analysis is off by default.

Advanced branches are explicit, for example `--branch edta --branch heliano --branch edta_plus_heliano`. Parent branches must be included. The five-branch `arabidopsis-compare` preset requires `--sample-id arabidopsis_TAIR10`. Reference branches require `--reference-library`. Runtime validation beyond Arabidopsis is pending; an accepted generic configuration does not establish accuracy for that species.

## Configure and lock databases

Before freezing, configure the actual RepeatMasker/RepeatModeler classification databases in each enabled tool environment. TEtrimmer additionally needs the Pfam HMM plus four pressed indexes and a local TE-Aid RepeatPeps protein database. These are distinct assets. Their roles and previous setup are documented in [database setup](SERVER_HANDOFF_zh.md) and [TE-Aid installation](TETRIMMER_RECOVERY_2026-10-12.md). Do not download all Dfam partitions merely to satisfy this workflow; select the applicable installed classification data.

```bash
# New installations only: supply verified local RepeatPeps, then create its indexes.
TEAID_SETUP=$(teflow assets --path scripts/prepare_teaid_database.py)
"$MICROMAMBA" run -p "$TE_ENV/engine" python "$TEAID_SETUP" \
  --config "$CONFIG" --repeatpeps /actual/path/RepeatPeps.lib \
  --output "$TASK_ROOT/install_logs/teaid_01"

# Repeat --classification-dir if isolated environments use different data directories.
teflow lock-databases --config "$CONFIG" \
  --pfam-dir /actual/path/pfam \
  --classification-dir /actual/path/RepeatMasker/Libraries/famdb
```

The paths above are placeholders for actual installed files. For an E-only run, skip TE-Aid and `--pfam-dir`. A copied old configuration already retains its database inventory; re-lock only when intentionally changing inputs before a new freeze. Never run database installation against an active frozen environment.

## Accept and run

```bash
teflow check --config "$CONFIG"
teflow run --config "$CONFIG" --dry-run
teflow run --config "$CONFIG"
teflow status --config "$CONFIG"
```

`check` audits inputs and runs bounded installation probes. It writes separate attempt reports but does not freeze the run. `run --dry-run` freezes inputs, software and recipes, repeats dependency checks and asks Snakemake to check the DAG. It is not a read-only command and can take minutes, but does not perform genome discovery. Use `plan` for a read-only graph inspection. A dry-run success is not biological validation.

Use `--target-stage export_edta` to stop at E's exported results. Use `--resume` after an interruption with unchanged inputs/settings/software. Live or unverified stage locks are not removed automatically. To run in the background:

```bash
RUN_LOG="$TASK_ROOT/my_plant_01.$(date -u +%Y%m%dT%H%M%SZ).log"
nohup "$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow run \
  --config "$CONFIG" > "$RUN_LOG" 2>&1 < /dev/null &
printf 'PID=%s LOG=%s\n' "$!" "$RUN_LOG"
```

The launcher defaults to serial execution, caps threaded libraries and checks Slurm CPU/memory allocations when present. Explicit single-species branch concurrency adds stage requests, CPU leases and memory observation; see [the 0.6 contract](SINGLE_SPECIES_v0.6.md). `mem_mb` is a scheduling/admission budget, not a hard limit. `scripts/run_server.sh CONFIG ...` remains compatible; the simple legacy Slurm entry is not a multi-species batch manager.

## Inspect and report

Each branch exports its own TE library, annotations and softmasked genome under `results/RUN/SAMPLE/`. Raw evidence and receipts stay under `work/RUN/SAMPLE/`. No branch is automatically declared the winner. See [RESULTS_GUIDE.md](RESULTS_GUIDE.md), [COMMANDS.md](COMMANDS.md) and the historical [protocol](PROTOCOL_v0.3.md).

```bash
teflow pack-feedback --config "$CONFIG" --output "$TASK_ROOT/feedback_01.tar.gz"
```

Feedback excludes genomes, full alignments and database contents, but can contain local paths, IDs and log excerpts. Inspect it before sharing. Candidate/boundary review commands are optional independent analyses, not mandatory installation steps.
