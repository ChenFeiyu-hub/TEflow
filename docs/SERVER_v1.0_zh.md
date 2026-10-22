# TEflow 1.0：服务器轻量验收与结果交付

本轮保留已完成的 0.6/0.7 目录及环境。先执行第 1–2 节；只使用小型模拟数据和实际 Snakemake，不执行 EDTA、TEtrimmer、HELIANO、HiTE 或真实 RepeatMasker。无需重复下载数据库，也不进行源码、上传包或反馈的 SHA-256 验证。

## 1. 解压至独立目录

把 `TEflow-1.0.0-source.zip` 上传至 `/home/cfy/te_project/uploads/`。以下使用子 shell，失败不会退出当前 SSH 登录；目标存在时停止，不覆盖源码。

```bash
(
set -euo pipefail
TASK_ROOT=/home/cfy/te_project
MICROMAMBA=/home/cfy/minimamba/bin/micromamba
TE_REPO="$TASK_ROOT/TEflow-1.0.0"
if [[ -e "$TE_REPO" ]]; then
  printf '%s\n' "目标已存在，保留它并选择另一个解压位置；不要覆盖。"
  exit 1
fi
"$MICROMAMBA" run -p "$TASK_ROOT/envs/engine" python -m zipfile -e \
  "$TASK_ROOT/uploads/TEflow-1.0.0-source.zip" "$TASK_ROOT"
cd "$TE_REPO"
export PYTHONPATH="$TE_REPO/src"
export TEFLOW_REPOSITORY="$TE_REPO"
"$MICROMAMBA" run -p "$TASK_ROOT/envs/engine" python -m teflow --version
"$MICROMAMBA" run -p "$TASK_ROOT/envs/engine" python -m teflow capabilities
)
```

## 2. 验收 1.0 的接口与并行流程

需要至少 4 个可用逻辑 CPU，模拟池预算 4096 MB；这不是硬内存限制。实际 mock 负载很小。使用 4 核即可，不需要配置 32/128 核。

```bash
(
set -euo pipefail
TASK_ROOT=/home/cfy/te_project
MICROMAMBA=/home/cfy/minimamba/bin/micromamba
TE_REPO="$TASK_ROOT/TEflow-1.0.0"
cd "$TE_REPO"
export PYTHONPATH="$TE_REPO/src"
export TEFLOW_REPOSITORY="$TE_REPO"
"$MICROMAMBA" run -p "$TASK_ROOT/envs/engine" python scripts/accept_release.py \
  --root "$TASK_ROOT" --threads 4
)
```

成功时应显示 `RELEASE_ACCEPTANCE_PASSED`，并打印独立的 `output`、`feedback` 路径。回传该反馈包即可。如果失败，保留相同目录，回传输出的反馈包；不要据此启动真实分析或终止其他项目进程。验收包括 1.0 单元回归、受控取消/恢复、串行/并行等价、独立分支失败处理、ET 亲本报告与显式交付。

## 3. 可选：只读重建已有真实结果的报告

这一步读取较大的原始 TSV，但不重跑发现、比对或 QC。报告必须写到新的目录；读旧结果时不要调用新版本的 `run --resume`。

```bash
(
set -euo pipefail
TASK_ROOT=/home/cfy/te_project
MICROMAMBA=/home/cfy/minimamba/bin/micromamba
TE_REPO="$TASK_ROOT/TEflow-1.0.0"
CONFIG="$TASK_ROOT/at_v06_parallel.local.json"
cd "$TE_REPO"
export PYTHONPATH="$TE_REPO/src"
export TEFLOW_REPOSITORY="$TE_REPO"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
REPORT="$TASK_ROOT/reviews/at_v06_v1_report.$STAMP.$$"
"$MICROMAMBA" run -p "$TASK_ROOT/envs/engine" python -m teflow report \
  --config "$CONFIG" --output "$REPORT"
tar -czf "$REPORT.tar.gz" -C "$(dirname "$REPORT")" "$(basename "$REPORT")"
printf 'REPORT=%s\nFEEDBACK=%s\n' "$REPORT" "$REPORT.tar.gz"
)
```

亲本数量应为 E 732、ET 唯一亲本 215、未保留亲本 517。覆盖率由服务器完整 `mask_sources.tsv` 计算；缺失文件会明确显示未知，不能当成零。该覆盖是 E 中未保留亲本的命中并集，不是 E/ET 的准确率差。

## 4. 需要下游交付时再显式选择

选择 E 的示例（不是对所有物种推荐唯一最佳库）：

```bash
TASK_ROOT=/home/cfy/te_project
MICROMAMBA=/home/cfy/minimamba/bin/micromamba
TE_REPO="$TASK_ROOT/TEflow-1.0.0"
cd "$TE_REPO"
export PYTHONPATH="$TE_REPO/src" TEFLOW_REPOSITORY="$TE_REPO"
"$MICROMAMBA" run -p "$TASK_ROOT/envs/engine" python -m teflow select \
  --config "$TASK_ROOT/at_v06_parallel.local.json" --branch edta \
  --policy te_primary --output "$TASK_ROOT/deliverables/at_v06_edta_v1" \
  --reason "Explicit EDTA baseline for downstream genome annotation"
```

默认相对软链接依赖原结果持续保留；需要转移至其他机器时加 `--mode copy`。已有交付目录不会覆盖。此操作选择完整分支并记录理由，不更改旧结果、不生成自动综合最佳库。`te_fragments.gff3` 是片段证据，不是完整插入/表达定量 GTF。

本地和 GitHub CI 通过不能替代本机 1.0 的验收记录；严格退出登录 B3、生产硬内存限制、多物种调度和真实容器取消测试仍单独登记。本次无需终止其他人在共享账户下运行的任务。
