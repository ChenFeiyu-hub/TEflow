# TEflow 0.6 服务器交接：先验收，再评估旧结果

本轮不需要下载新数据库，也不需要重跑 EDTA、TEtrimmer、HELIANO 或 HiTE。先解压新源码，用已有 engine 运行短小的模拟验收，再对 `at_compare_v022` 做只读核对和独立重新评估。新源码与旧运行分开保存；本说明没有源码、上传包或反馈包的 SHA-256 校验步骤。外部工具和数据库的下载完整性检查仍保留。

## 1. 上传与选择源码

将 `TEflow-0.6.0-source.zip` 上传到 `/home/cfy/te_project/uploads/`。下面使用已有 engine，**不重装共享 Conda 环境**。第一段使用子 shell，即使失败也不会退出登录会话。

```bash
(
set -euo pipefail
TASK_ROOT=/home/cfy/te_project
MICROMAMBA=/home/cfy/minimamba/bin/micromamba
TE_ENV="$TASK_ROOT/envs"
TE_REPO="$TASK_ROOT/TEflow-0.6.0"
test -s "$TASK_ROOT/uploads/TEflow-0.6.0-source.zip"
if [[ -e "$TE_REPO" ]]; then
  printf '%s\n' '目标目录已存在；请保留它，勿覆盖正在验收或运行的源码。'
  exit 1
fi
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m zipfile -e \
  "$TASK_ROOT/uploads/TEflow-0.6.0-source.zip" "$TASK_ROOT"
export PYTHONPATH="$TE_REPO/src"
export TEFLOW_REPOSITORY="$TE_REPO"
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow --version
"$MICROMAMBA" run -p "$TE_ENV/engine" python -c \
  'import teflow; assert teflow.__version__ == "0.6.0"; print(teflow.__file__)'
)
```

后续各段在同一个终端执行前，设置这些变量与函数。重新登录后也可原样执行：

```bash
TASK_ROOT=/home/cfy/te_project
TE_ENV="$TASK_ROOT/envs"
TE_REPO="$TASK_ROOT/TEflow-0.6.0"
export MICROMAMBA=/home/cfy/minimamba/bin/micromamba
export PYTHONPATH="$TE_REPO/src"
export TEFLOW_REPOSITORY="$TE_REPO"
teflow06() { "$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow "$@"; }
teflow06 --version
```

旧任务继续使用其原来的源码目录和启动方式。不要在新 PYTHONPATH 下对旧冻结运行执行 `run --resume`。下面的旧结果审计/重新评估不执行生产阶段，不要求迁移旧冻结指纹。

## 2. 执行 0.6 有界验收

```bash
"$MICROMAMBA" run -p "$TE_ENV/engine" python \
  "$TE_REPO/scripts/accept_single_species.py" --root "$TASK_ROOT" --threads 8
```

脚本只使用 160 bp 合成序列和模拟工具，通过真实 Snakemake 分别执行串行、并行、故障注入。最多同时两个阶段，CPU 池 8 线程、内存申报池 4096 MB；真实占用由小型 Python 进程决定，无硬内存限额。通常是分钟级，不是基因组分析。它不依赖登录会话清零，也不重复旧 B2 的 OOM 测试。

成功结尾应为 `SINGLE_SPECIES_ACCEPTANCE_PASSED`，并给出准确的 output 和 feedback 路径。把该 `.feedback.tar.gz` 回传即可。失败也会打包诊断，保留目录，不删除锁、工作目录或旧安装。日志中的故障注入分支报错是预期测试内容；以最外层验收结果和 `validation.json` 为准，不能把中间某个模拟工具失败单独当成验收失败。

验证点包括：实际并行发生、CPU 分配互不重叠、临时目录独立、串行/并行导出一致、一个分支失败后独立分支完成、最终结果仍准确报告失败、租约释放、旧结果重新评估不改写源文件。

## 3. 只读核对已有拟南芥结果

确认旧配置路径。如果服务器保存的文件名不同，只修改 `OLD_CONFIG`，不要修改配置内容。

```bash
(
set -euo pipefail
OLD_CONFIG="$TASK_ROOT/at_compare_v022.local.json"
test -s "$OLD_CONFIG" || { printf '%s\n' '请将 OLD_CONFIG 指向已有 v022 配置；不需要新建生产配置。'; exit 1; }
REVIEW_ROOT="$TASK_ROOT/reviews/v06.$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$REVIEW_ROOT"
teflow06 audit-results --config "$OLD_CONFIG" --output "$REVIEW_ROOT/raw_audit.json"
teflow06 reevaluate --config "$OLD_CONFIG" --output "$REVIEW_ROOT/reevaluated"
tar -czf "$REVIEW_ROOT.feedback.tar.gz" \
  -C "$(dirname "$REVIEW_ROOT")" "$(basename "$REVIEW_ROOT")"
printf 'REVIEW_ROOT=%s\n' "$REVIEW_ROOT"
printf '%s\n' "$REVIEW_ROOT.feedback.tar.gz"
)
```

这两条命令不会调用 TE 工具，不读取全基因组 FASTA 进行新分析，不修改旧库或注释。`audit-results` 读 `.out`、库 FASTA 与 prepared manifest；`reevaluate` 读已有分支导出，生成新的分类表、全基因组分类覆盖、分层覆盖和分支差异。重新评估不重写软掩蔽 FASTA，也不重做启动子/参考库评估。

发现 `out_of_bounds`、`length_mismatch` 或 `root_only` 应作为复核信息回传。已有真实文件中确实存在这些情况；不代表要重跑 RepeatMasker，也不能直接宣布原来的基因组掩蔽区间错误。`audit_complete` 表示审计完成，不等于每条共识坐标已验证。

上面的代码在两条命令都成功后自动打包新评估目录，不需要另做 checksum。若中断，保留失败信息；重新执行会生成新的时间戳目录，不覆盖旧评估。

## 4. 准备未来新运行的单物种并行配置

本段只是配置和 dry-run，**不是要求重跑已有拟南芥分析**。两项前置反馈通过后，才需要决定下一次真实小规模并行验收使用新物种还是显式导入兼容的旧阶段。不会自动导入 E/ET/H/I/EH，更不会修改旧 receipt 来强行复用。

```bash
OLD_CONFIG="$TASK_ROOT/at_compare_v022.local.json"
CONFIG="$TASK_ROOT/at_v06_parallel.local.json"
teflow06 fork-config --config "$OLD_CONFIG" \
  --output "$CONFIG" --run-id at_v06_parallel \
  --parallel-branches --jobs 2 --io-slots 2 \
  --threads 32 --mem-mb 131072 --memory-headroom-mb 8192 \
  --all-interspersed
teflow06 plan --config "$CONFIG"
```

这里 EDTA/TEtrimmer/HELIANO/HiTE 仍按整个预算申报，所以不会默认让多个高内存发现任务一起启动。独立 RM 分支可在依赖完成后并行，每个默认 4 线程、65536 MB 申报；这是保守的调度值，不是预测内存需求。服务器 503 GiB 总内存不是本任务可独占资源，仍须为同账号或其他账号的计算保留余量。

如需显式改为每个 RM 8 线程、32768 MB，可在新的配置生成前用 `--stage-resources` 指向以下 JSON 文件；不要修改已冻结运行：

```json
{"repeatmasker": {"threads": 8, "mem_mb": 32768, "io": 1}}
```

新配置准备好后执行：

```bash
teflow06 check --config "$CONFIG"
teflow06 run --config "$CONFIG" --dry-run
```

正式启动新计算的命令保留如下；它会实际执行所有尚未完成的启用阶段，包含耗时发现工具，不能把它当成验收步骤：

```bash
RUN_LOG="$TASK_ROOT/at_v06_parallel.$(date -u +%Y%m%dT%H%M%SZ).log"
nohup "$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow run \
  --config "$CONFIG" > "$RUN_LOG" 2>&1 < /dev/null &
printf 'PID=%s LOG=%s\n' "$!" "$RUN_LOG"
```

本次不承诺普通 nohup 能应对所有 logind/管理员策略。几天的实际任务可在站点提供的作业调度环境内运行；TEflow 的生产 systemd 后端仍未启用。不要为验证退出登录而终止共享账号下的 IQTREE 或其他未知任务。

## 5. 观察、失败和恢复

```bash
teflow06 status --config "$CONFIG"
teflow06 runtime-status --config "$CONFIG"
```

`status` 检查结果存在性/元数据并显示阶段观测，不对大文件重复做内容校验。`runtime-status` 显示当前租约、PID 身份、CPU、内存申报和采样值。采样 RSS 会漏过瞬时峰值，也可能重复计算共享页面；不能据此声称硬性限制已生效。全局可用内存不足时只推迟新任务，不杀其他人的进程。

如果新启动被遗留租约阻止，先读 `runtime-status`。仅当原进程已退出且记录的子进程组也不存在时，下面的命令才会释放租约；它不向任何进程发信号，遇到未决的 dispatch 记录会拒绝自动处理：

```bash
teflow06 runtime-reconcile --config "$CONFIG"
```

科学阶段 `.lock` 与资源租约是两层机制；不要直接删锁。必要时用已有 `unlock-stage` 做单独的已退出进程核对。确认相同配置和工具未变后，可 `teflow06 run --config "$CONFIG" --resume`。资源需求需要更改时应创建新运行，不在旧运行上自动扩大配额。

```bash
teflow06 pack-feedback --config "$CONFIG" \
  --output "$TASK_ROOT/at_v06_parallel.$(date -u +%Y%m%dT%H%M%SZ).feedback.tar.gz"
```

若只执行本轮建议的第 1–3 段，请回传模拟验收包和新的旧结果评估包；无需提交任何大 FASTA、容器或数据库。
