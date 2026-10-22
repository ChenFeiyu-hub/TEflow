> Historical/version-specific record. For a new 0.4.0 installation start with [INSTALL](INSTALL.md); for an existing run see [UPGRADING](UPGRADING.md).

# 服务器执行手册

> 历史入口：0.2 新运行请使用 [SERVER_HANDOFF_v0.2_zh.md](SERVER_HANDOFF_v0.2_zh.md)。下文保留旧基线部署说明，不直接用于迁移现有 v03。

适用：Linux 普通终端或单节点 Slurm。首轮推荐一个物种、32 个核、同一时间一个高 I/O 步骤。先拟南芥，再衣藻。本地无需安装完整 EDTA 环境。

## 1. 复制代码与四份原始输入

将本项目文件夹／源码压缩包复制到服务器，例如 `/scratch/your_account/te_project/te-annotation-workflow`。下面的 `/scratch/your_account` 是占位路径，请换成服务器真实可写位置，不含空格。检查 `df -h`、`free -h` 和站点限制后决定 `MEM_MB`；脚本不会假设您的服务器内存大小。

```text
te_project/
  te-annotation-workflow/
  inputs/
    arabidopsis/TAIR10.fa
    arabidopsis/Araport11.gtf
    chlamydomonas/CreinhardtiiCC_4532_707_v6.0.fa
    chlamydomonas/CreinhardtiiCC_4532_707_v6.1.gene_exons.gff3
  envs/                  安装后生成
  databases/             安装后生成
  work/ results/         运行后生成
```

优先使用已经在服务器保存的完全相同版本文件，不必来回传输。比对本次本地交付的 `real_input_audit.json` 中 SHA256，不能仅凭文件名判断一致。不需要重新下载 RNA-seq 数据、JASPAR、DAP-seq 或 ChIP-seq；它们不参与本次 TE 发现。

## 2. 环境安装

若真实 EDTA 运行在 `TIR-Learner3/app/check_TIR_TSD.py` 的 `family = x[0]` 报 `KeyError: 0`，先看 [2026-10-10 pandas 兼容性修复](TIR_PANDAS_FIX_2026-10-10.md)。v0.1.3 固定 pandas 2.3.3 并增加运行时探针；这不是缺少 TIR 的证据，不应使用 `--force 1` 跳过。已经冻结的旧运行需要保留，修复环境后使用新 run_id。

若遇到 `tetrimmer -> pfam_scan -> perl-bioperl -> perl-bio-samtools` 与 RMBlast 的 zlib 冲突，先更新到 v0.1.1，并阅读 [2026-10-08 安装修复说明](INSTALL_FIX_2026-10-08.md)。这是环境配方问题，与 TASK_ROOT 是否以 `/` 结尾无关。

若日志是 `blast=2.17.0` 与 `rmblast=2.17.0` 的 `entrez-direct` 冲突，请更新到 **v0.1.2**，见 [第二轮修复说明](INSTALL_FIX_v0.1.2_2026-10-08.md)。TEtrimmer 和 masking 都由 RMBlast 包提供 `blastn`、`makeblastdb`、`blastdbcmd`、`dustmasker` 等程序，不再单独安装 `blast` 包。不要仅为了这些可执行文件额外加入普通 BLAST 包。

服务器准备 micromamba、curl、gzip、tar、bash。若已有 micromamba，把路径放入 PATH；若没有，按 [micromamba 官方安装说明](https://mamba.readthedocs.io/en/latest/installation/micromamba-installation.html) 安装 Linux 对应架构版本。不要把 Windows/WSL 的已安装环境直接搬上服务器。

```bash
TASK_ROOT=/scratch/your_account/te_project
TE_REPO="$TASK_ROOT/te-annotation-workflow"
TE_ENV="$TASK_ROOT/envs"
cd "$TE_REPO"
export MICROMAMBA=/absolute/path/to/micromamba
# 以下可先仅检查求解；大型环境求解也建议在服务器做：
bash scripts/bootstrap_server.sh "$TE_ENV" --solve-only
# 正式安装：
bash scripts/bootstrap_server.sh "$TE_ENV"
```

没有 `--solve-only` 时才安装，脚本不会覆盖已有环境。安装日志在 `envs/install_logs/<UTC时间-PID>/`，每个环境的实际 build 锁在 `envs/locks`。`--only tetrimmer` 可单独检查或安装 TEtrimmer；其他可选值为 `engine`、`edta`、`masking`。目前这些 YAML 是版本约束，不是已经在您的服务器求解通过的精确锁文件；真正可复现的锁以安装后输出为准。若失败，请先回传安装日志，不要自行执行无记录的大范围升级。

Snakemake 使用 Python 3.11；TEtrimmer 1.7.2 单独使用 Python 3.10。此版 README 上出现的 1.7.4 不等于已发布的 Bioconda／Git 标签，本封装只验收 1.7.2 接口。

v0.1.1 中 TEtrimmer 环境 YAML 安装运行依赖，随后脚本从官方归档安装未修改的 TEtrimmer 1.7.2 和 PfamScan 1.6；两个归档均校验固定 SHA256。BioPerl 使用核心模块包，避免完整总包拉入历史 samtools/zlib 约束。不是绕过依赖检查；不要再在该环境执行 `micromamba install tetrimmer pfam_scan`，否则会重新引入同一总包依赖。源文件、启动器和散列记录在 `share/teflow-vendor/sources.lock.json`，并由工作流冻结机制核对。

`--solve-only` 只验证 Conda 运行依赖，不安装/导入源码，不检查 pip 内的 Snakemake 或数据库。官方 TEtrimmer 源码归档约 139 MB（十进制，包含演示媒体）；安装时仅保留运行代码和许可，完整归档留在 `envs/source_cache`。服务器无法访问 GitHub/EBI 时，可离线传入已校验的同名归档。见安装修复说明。

## 3. 数据库配置：先明确，后冻结

需要两类实际运行数据库：Pfam（TEtrimmer）与 Dfam/FamDB 分类资源（上游 RepeatClassifier）。它们与用户已下载的 motif 数据库不同。首轮不需要庞大的 Dfam 全量未整理 HMM 库，也不默认加入付费 RepBase。

Pfam 示例固定 37.0，用 TEtrimmer 环境里的 hmmpress 建索引：

```bash
"$MICROMAMBA" run -p "$TE_ENV/tetrimmer" bash scripts/fetch_pfam.sh "$TASK_ROOT/databases/pfam37" 37.0
```

该脚本不会在已有 Pfam 数据上覆盖写。记录 HMM、dat 和四个 hmmpress 索引散列。

RepeatMasker 4.2.4／RepeatModeler 2.0.9 采用 Dfam 4.0 对应的 FamDB 格式。根据 [FamDB 官方安装指南](https://github.com/Dfam-consortium/FamDB/blob/master/QUICKSTART.md)，先准备 root 与完整 curated consensus 组件；在安装环境中运行 `famdb.py info`，确认数据库版本、组件与实际数据目录。不要混用 3.9 的分区号和 4.0 组件名称。必要的蛋白分类库由对应 FamDB／RepeatClassifier 路径解析，后续小型探针会检查它是否能正常加载。

Bioconda 不同 build 的安装目录可能不同，因此本版不猜测 `share/RepeatMasker-*` 路径、不自动改写第三方配置。可在各环境定位程序后，按所装版本的 `configure` 帮助完成 RepeatMasker／RepeatModeler 的 RMBlast、FamDB 路径配置。EDTA 与 TEtrimmer 是两个隔离环境，**两个环境内的 RepeatClassifier 都要检查**；独立 masking 环境用于统一 `-lib` 回贴。可以指向同一冻结的 FamDB 数据目录。

把实际工具自带数据库也纳入锁：EDTA 的 `database/`、所用 TEsorter 数据目录，以及独立 FamDB 数据目录。工具安装缓存、临时日志和可再生成缓存不要混在冻结数据库目录中。未冻结的人工数据库不进入正式运行。

## 4. 生成配置和安装检查

```bash
# 根据您实际分到的内存设定；下面只是填写方式，不能照抄成实测需求。
MEM_MB=65536
"$MICROMAMBA" run -p "$TE_ENV/engine" teflow init-server \
  --root "$TASK_ROOT" --env-root "$TE_ENV" --data-root "$TASK_ROOT/inputs" \
  --sample arabidopsis --threads 32 --mem-mb "$MEM_MB" \
  --run-id at_pilot_v01 --micromamba "$MICROMAMBA" \
  --output "$TASK_ROOT/at_pilot.local.json"
```

检查 JSON 的输入路径、排除 ID、工具命令、资源预算。`init-server` 不覆盖旧文件。若 64 GiB 不在实际分配内或不足，请换成合适预算；首轮不是内存性能承诺。

在新配置首次冻结前准备 TE-Aid 蛋白库。它独立于 Pfam 和 FamDB；从已安装 RepeatMasker 的本地 RepeatPeps.lib 复制，不在基因组运行中联网获取：

```bash
"$MICROMAMBA" run -p "$TE_ENV/engine" python scripts/prepare_teaid_database.py \
  --config "$TASK_ROOT/at_pilot.local.json" \
  --output "$TASK_ROOT/teaid_install.$(date -u +%Y%m%dT%H%M%SZ)"
```

准备工具会实际建库、读取索引并检索一条库内蛋白。`lock-databases` 会自动纳入这套实际运行路径上的资产；既有冻结运行不得直接沿用，应创建新 run_id。

先运行独立的安装检查，用小探针预热并核对分类后端：

```bash
"$MICROMAMBA" run -p "$TE_ENV/engine" teflow doctor \
  --config "$TASK_ROOT/at_pilot.local.json" \
  --output "$TASK_ROOT/installation_check" --dependencies
```

它会查版本／CLI、调用 EDTA 的依赖检查（其中有极小的 RMBlast 测试），并在 EDTA、TEtrimmer 两个环境测试合成序列的 RepeatClassifier，包含 TEtrimmer 实际使用的无描述标题与 Dummy 格式。不会启动真实基因组的 EDTA。doctor 是安装可用性检查，不是生物学准确率测试。任何失败先保留日志并反馈。

若旧版 doctor 仅 `repeatmasker` 一项报退出码 1，先看 `repeatmasker.version.log`。截至 v0.1.2 的已发布包错误地使用了 `RepeatMasker -version`；RepeatMasker 的正确版本入口是 `RepeatMasker -v`，成功退出码仍必须是 0，不能放宽为接受错误码 1。当前工作目录已修正此参数，并让合成接口拒绝错误拼写。服务器可先执行 `micromamba run -p /实际/envs/masking RepeatMasker -v` 核对；将 `src/teflow/stages.py` 中仅 RepeatMasker 那一项改为 `["-v"]`，然后在 engine 环境执行 `python -m pip install --no-deps --force-reinstall /实际/te-annotation-workflow`，使非 editable 安装的 teflow 同步更新。保留旧检查记录，在新输出目录重新运行 doctor；这不需要重建第三方环境或重新下载数据库。

再将**真实的数据库路径**登记到配置；以下大写变量需替换为您实际定位的路径：

```bash
"$MICROMAMBA" run -p "$TE_ENV/engine" teflow lock-databases \
  --config "$TASK_ROOT/at_pilot.local.json" \
  --pfam-dir "$TASK_ROOT/databases/pfam37" \
  --classification-dir "$FAMDB_DATA_DIR" \
  --extra-dir "$EDTA_DATABASE_DIR" \
  --extra-dir "$TESORTER_DATABASE_DIR" \
  --extra-dir "$TE_ENV/locks"
```

不同环境如果实际使用不同分类库，可重复 `--classification-dir`。已经嵌入 Conda 包中的软件 build 元数据会自动记录，但大型数据库资产仍应显式登记。锁文件不是安装器：它只记录当前文件，不会将程序自动指向该目录。

## 5. Dry-run 与首个生产运行

```bash
"$MICROMAMBA" run -p "$TE_ENV/engine" teflow validate-inputs \
  --config "$TASK_ROOT/at_pilot.local.json" --output "$TASK_ROOT/server_input_audit.json"
"$MICROMAMBA" run -p "$TE_ENV/engine" bash scripts/run_server.sh \
  "$TASK_ROOT/at_pilot.local.json" --dry-run
```

Dry-run 会冻结内容、核对数据库并运行安装探针，然后仅打印 Snakemake DAG，不运行基因组注释。首次冻结后不要再编辑输入、配置或环境。需要调整时创建新配置／run_id。

普通终端使用 tmux／screen 保持连接，再执行：

```bash
"$MICROMAMBA" run -p "$TE_ENV/engine" bash scripts/run_server.sh "$TASK_ROOT/at_pilot.local.json"
```

Slurm 使用单个节点分配；按站点规定填写时限和分区：

```bash
"$MICROMAMBA" run -p "$TE_ENV/engine" bash scripts/submit_slurm.sh \
  "$TASK_ROOT/at_pilot.local.json" 2-00:00:00 YOUR_PARTITION
```

提交脚本从同一配置读取 CPU／内存，不再使用第二套资源数字。该方式在一个作业内调度，便于初版故障诊断；不把每个规则拆成 Slurm job。48 小时仅是调用示例，不是实际耗时估计。若站点需要 account/QOS，请在 sbatch 参数中补充。

失败后检查 `failed.json` 与日志；修复若不改变冻结内容，可在确认无残留进程后：

```bash
"$MICROMAMBA" run -p "$TE_ENV/engine" bash scripts/run_server.sh "$TASK_ROOT/at_pilot.local.json" --resume
```

Slurm 续跑使用 `bash scripts/submit_slurm.sh CONFIG TIME_LIMIT YOUR_PARTITION --resume`，仍在 engine 环境调用；若无指定分区则第三个位置传空字符串 `""`。不要删除所有工作目录后声称“断点续跑”。

## 6. 回传什么

运行完成或中途失败都可执行：

```bash
"$MICROMAMBA" run -p "$TE_ENV/engine" teflow pack-feedback \
  --config "$TASK_ROOT/at_pilot.local.json" --output "$TASK_ROOT/at_pilot_feedback.tar.gz"
```

优先回传这个小包，外加 `installation_check/doctor.json`、安装失败日志（若有）、Slurm 的 job 日志／峰值 RSS／耗时。小包包含配置、来源、阶段状态、摘要、错误文件和日志；超大日志只保留末尾并登记截断，不带基因组、数据库和大型比对文件。

之后若需要人工审查特定家族，再按报告挑选 TEtrimmer 的 proof_curation/MSA/PDF 等材料。首次无需同步整个巨大的 EDTA 工作目录。

拟南芥通过初次审计后，为衣藻运行新的 `init-server --sample chlamydomonas --run-id cr_pilot_v01` 配置，复用已经检查并冻结的同版本数据库。不要直接改动已经冻结的拟南芥配置。
