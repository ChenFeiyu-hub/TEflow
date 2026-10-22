> Historical/version-specific record. For a new 0.4.0 installation start with [INSTALL](INSTALL.md); for an existing run see [UPGRADING](UPGRADING.md).

# 0.2 服务器交接：先安装验收，再分支运行

本页针对已有 `/home/cfy/te_project`、EDTA 2.3.0、TEtrimmer 1.7.2 与共享数据库的服务器。保留旧仓库、`at_pilot_v03.local.json` 和全部旧输出。0.2 使用新目录、新配置、新 run ID；本地测试没有替服务器完成 HELIANO/HiTE/干净 TEtrimmer 的全基因组验收。

## 1. 解包和版本核对

把发布的 tar.gz 与 SHA256SUMS 文件上传到 `$TASK_ROOT/releases/`。解包顶层目录名固定为 `te-annotation-workflow-v0.2`；若该目录已有内容，先检查，不覆盖。

```bash
set -euo pipefail
TASK_ROOT=/home/cfy/te_project
TE_ENV="$TASK_ROOT/envs"
export MICROMAMBA=/home/cfy/minimamba/bin/micromamba
cd "$TASK_ROOT/releases"
# 本命令只校验已上传的 tar.gz；也上传 zip 时可一并核验。
grep 'te-annotation-workflow-v0.2.tar.gz$' SHA256SUMS-v0.2.txt | sha256sum -c -
test ! -e "$TASK_ROOT/te-annotation-workflow-v0.2"
tar -xzf te-annotation-workflow-v0.2.tar.gz -C "$TASK_ROOT"
TE_REPO="$TASK_ROOT/te-annotation-workflow-v0.2"
export TEFLOW_REPOSITORY="$TE_REPO"
export PYTHONPATH="$TE_REPO/src${PYTHONPATH:+:$PYTHONPATH}"
cd "$TE_REPO"
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow --version
```

应输出 `0.2`。不需要为了切换 wrapper 去升级现有 EDTA、TEtrimmer 或 masking 环境；`python -m teflow` 和启动器使用这里指定的源码，避免旧 `teflow` 入口混用。

## 2. 只准备新增依赖

HELIANO 配方已经通过本地 Linux dry-run：169 个包，计划下载约 590 MB；QC 配方 19 个包，约 38 MB。这只说明求解成功。HELIANO 依赖较旧 Python/R 的固定组合，首次下载旧 channel 元数据可能较慢，使用独立环境。

```bash
bash scripts/bootstrap_server.sh "$TE_ENV" --solve-only --only heliano
bash scripts/bootstrap_server.sh "$TE_ENV" --only heliano
# 本交接建议启用宿主蛋白 QC；不启用时可以跳过这两行及后面的 --protein-qc。
bash scripts/bootstrap_server.sh "$TE_ENV" --solve-only --only qc
bash scripts/bootstrap_server.sh "$TE_ENV" --only qc

# 服务器须已有 Apptainer；此脚本不会安装 Docker 守护进程或修改 Conda。
apptainer --version
bash scripts/install_hite_container.sh "$TASK_ROOT/containers/hite-3.3.3.sif"
```

安装器拒绝覆盖已有环境或 SIF/partial 下载。已装好某项时不要重复调用安装；检查对应日志和锁文件。HiTE 镜像下载量以容器实际大小为准，本地没有拉取该大型镜像。镜像按上游 `run ... python /HiTE/main.py` 入口调用；若服务器无 Apptainer，由服务器管理员按其集群规范安装。不能用 `--force` 掩盖入口失败。

环境 build 锁在 `$TE_ENV/locks/`；HiTE 散列为 `.sif.sha256`。应保存这些文件。原有 Pfam、Dfam、RepeatPeps 继续复用，无需再次 all 下载。

## 3. 新建比较配置

```bash
OLD_CONFIG="$TASK_ROOT/at_pilot_v03.local.json"
CONFIG="$TASK_ROOT/at_compare_v02.local.json"
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow migrate-config \
  --config "$OLD_CONFIG" --output "$CONFIG" --run-id at_compare_v02 \
  --env-root "$TE_ENV" --micromamba "$MICROMAMBA" \
  --profile arabidopsis-compare \
  --hite-image "$TASK_ROOT/containers/hite-3.3.3.sif" --protein-qc
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow plan --config "$CONFIG"
```

迁移保留已核验的数据库路径/散列和现有工具命令。核数与内存保留旧配置；本轮建议仍为 32 线程、131072 MB，每次一个重 I/O 作业。不在已有 frozen 运行中修改预算。

首次 freeze 前可以登记以下可选项；没有这些文件也可先完成五分支工程试跑：

- `samples[0].reference_te`：TAIR10 对应 TE 坐标 GFF3/GTF。默认 feature 为 `transposable_element`/`repeat_region`，类属性为 `Classification`；不同格式必须在 `evaluation` 显式设置。Araport11 gene GTF 不能冒充完整 TE 参考。
- `samples[0].promoters_bed`：pCRE 已冻结 BED6，原始 seqid、唯一 gene ID、strand。没有它时仅产生 provisional gene-boundary 窗口。
- `samples[0].reference_library`：真正需要比较的已登记参考共识 FASTA；同时启用 `branches.reference_only.enabled` 和 `branches.reference_plus_edta.enabled`，否则保持关闭。
- `qc.te_proteins`：可选核验过的 RepeatPeps.lib 路径；宿主与 TE 蛋白命中都只是标记。现有例子的 SHA256 为 `6b662d40bcb8c59e9c759d8ca6a07358368cf7c3c36807e8d27fef1001d480d2`，请用服务器真实存在的路径登记。
- `qc.pfam=true` 并添加 `tools.hmmscan={"command":["/home/cfy/minimamba/bin/micromamba","run","-p","/home/cfy/te_project/envs/qc","hmmscan"],"expected_version":"3.4"}` 可启用每库六框域证据；Pfam 路径/索引仍复用现有锁。

先核对新 JSON，再 freeze。之后要增减这些输入需新 run ID。使用 `--protein-qc` 时宿主蛋白从已验收 CDS 翻译；若翻译失败，应查看 CDS 来源，不把失败候选悄悄删除来继续。

```bash
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow validate-inputs \
  --config "$CONFIG" --output "$TASK_ROOT/at_compare_v02.input_audit.json"
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow freeze --config "$CONFIG"
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow doctor \
  --config "$CONFIG" --dependencies --output "$TASK_ROOT/work/at_compare_v02/doctor"
```

doctor 包括已有分类后端、TIR-Learner pandas、TE-Aid，以及 HELIANO/HiTE 小型依赖操作；这不是全基因组发现。首次失败可修复安装后重试，但若已 freeze 后软件散列改变，应生成新的配置/run ID，保留失败证据。doctor 的每次尝试各自归档，失败不会锁住 canonical 成功回执。

## 4. 导入已完成的 EDTA 与公共 RM

```bash
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow import-stage \
  --config "$CONFIG" --source-config "$OLD_CONFIG" \
  --sample arabidopsis_TAIR10 --name edta
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow import-stage \
  --config "$CONFIG" --source-config "$OLD_CONFIG" \
  --sample arabidopsis_TAIR10 --name rm_edta
"$MICROMAMBA" run -p "$TE_ENV/engine" bash "$TE_REPO/scripts/run_server.sh" "$CONFIG" --dry-run
```

只复制通过完整性和兼容性校验的完成产物，原始目录不变。线程、相关命令、数据库、prepared 基因组/CDS 或旧结果不一致都会拒绝导入；这时保留错误反馈，不能手动改哈希绕过。拒绝导入不表示 EDTA 生物学结果一定错误，可能只是不能证明版本间兼容。失败的旧 TEtrimmer 不导入。若 v03 没有已完成的 EDTA/RM，选择实际保存完整回执的旧配置；不要随意填写文件路径充当回执。

## 5. 正式分支执行

以下一次只选择一个目标启动，上一任务结束后再执行下一目标；不同启动器之间不共享 Snakemake 的资源限额。建议顺序是导出 E → 干净 ET → H → HiTE → E+H → 总比较。每次启动器重新执行 doctor，确认依赖仍可用。

```bash
# 先检查能否从已导入的结果导出 E 及共享轨道。
"$MICROMAMBA" run -p "$TE_ENV/engine" bash "$TE_REPO/scripts/run_server.sh" "$CONFIG" --target-stage export_edta

# 后台运行 ET；nohup 保证退出终端后仍继续。
RUN_LOG="$TASK_ROOT/at_compare_v02.ET.$(date -u +%Y%m%dT%H%M%SZ).log"
nohup "$MICROMAMBA" run -p "$TE_ENV/engine" bash "$TE_REPO/scripts/run_server.sh" \
  "$CONFIG" --target-stage export_edta_tetrimmer > "$RUN_LOG" 2>&1 < /dev/null &
printf '%s\n' "PID=$! LOG=$RUN_LOG"
```

在启动较长分支前，可以用相同入口先检查该目标的 DAG：

```bash
"$MICROMAMBA" run -p "$TE_ENV/engine" bash "$TE_REPO/scripts/run_server.sh" \
  "$CONFIG" --dry-run --target-stage export_heliano
```

ET 结束并通过审核后，复用后台命令，把目标依次换成 `export_heliano`、`export_hite`、`export_edta_plus_heliano`，并给日志不同名称。条件参考分支启用时补跑 `export_reference_only`、`export_reference_plus_edta`。各目标完成后运行无 target 的启动器生成总比较：

```bash
"$MICROMAMBA" run -p "$TE_ENV/engine" bash "$TE_REPO/scripts/run_server.sh" "$CONFIG"
```

无 target 也可从一开始调度整个流程；它仍按一个重 I/O 任务运行，但本轮首次验收更适合逐分支收集反馈。HELIANO 默认原生片段模式；不要在当前 frozen 配置中切到官方共识模式。HiTE 的 `-T 0` 子程序受 Linux CPU affinity 约束；内存最好由调度系统限制。

## 6. 状态、重试与反馈

```bash
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow status --config "$CONFIG"
# 查看失败证据并确认无残留进程后，才显式重试对应目标：
"$MICROMAMBA" run -p "$TE_ENV/engine" bash "$TE_REPO/scripts/run_server.sh" \
  "$CONFIG" --resume --target-stage export_heliano
# 仅在 status 提示残留锁且 owner 已结束时使用；活进程/异地主机锁会拒绝：
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow unlock-stage \
  --config "$CONFIG" --sample arabidopsis_TAIR10 --name heliano
```

Snakemake 自己的调度锁与 stage `.lock` 不同。若只有 Snakemake 的失效锁，先确认该 run 无活跃调度器，再由 engine 使用同一 Snakefile/config 执行 `snakemake --unlock`；不要通配符删除工作目录。TEtrimmer 的错误证据仍会严格阻断，不能因为有最终 FASTA 就认定成功。

```bash
FEEDBACK="$TASK_ROOT/at_compare_v02.feedback.$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow pack-feedback \
  --config "$CONFIG" --output "$FEEDBACK"
```

请回传该反馈包、对应启动日志，以及 `$TE_ENV/locks/heliano.linux-64.explicit.txt`、`qc.linux-64.explicit.txt` 和 HiTE `.sif.sha256`。不需要回传整个环境或基因组。重点核对每条路线终态、原生/回贴差异、MITE 类别、嵌套清理、宿主蛋白标记和启动子机会变化；完成计算不等于已经选定优胜分支。
