# 1.1.0rc1：v4 首选、v3 备用的服务器交接

本轮执行有限封装验收和已有 hAT 中间结果审计即可。无需重新运行完整 EDTA，也不需要校验开发包 SHA-256。原成功实验和环境继续保留。

## 1. 解压到新目录

上传 `TEflow-1.1.0rc1-source.zip` 到 `/home/cfy/te_project/uploads/` 后执行：

```bash
(
set -euo pipefail
TASK_ROOT=/home/cfy/te_project
MICROMAMBA=/home/cfy/minimamba/bin/micromamba
TE_REPO="$TASK_ROOT/TEflow-1.1.0rc1"
if [[ -e "$TE_REPO" ]]; then
  printf '%s\n' "目标目录已存在，请保留并使用另一个新解压目录。"
  exit 1
fi
"$MICROMAMBA" run -p "$TASK_ROOT/envs/engine" python -m zipfile -e \
  "$TASK_ROOT/uploads/TEflow-1.1.0rc1-source.zip" "$TASK_ROOT"
PYTHONPATH="$TE_REPO/src" TEFLOW_REPOSITORY="$TE_REPO" \
  "$MICROMAMBA" run -p "$TASK_ROOT/envs/engine" python -m teflow --version
)
```

预期版本 `1.1.0rc1`。这里按源目录调用，不替换现有 engine 中安装的旧版，原冻结任务仍可用原源码续跑。

## 2. 为 v4 新建配置

下面使用已有的成功 CPU 环境，不重复安装。原配置沿用已知的 `at_v06_parallel.local.json`；命令会保留输入、数据库、分支和资源设置，创建新运行。若服务器已将原配置另存他处，只修改 `OLD_CONFIG` 这一行。

```bash
(
set -euo pipefail
TASK_ROOT=/home/cfy/te_project
MICROMAMBA=/home/cfy/minimamba/bin/micromamba
TE_REPO="$TASK_ROOT/TEflow-1.1.0rc1"
export PYTHONPATH="$TE_REPO/src"
export TEFLOW_REPOSITORY="$TE_REPO"
OLD_CONFIG="$TASK_ROOT/at_v06_parallel.local.json"
CONFIG="$TASK_ROOT/at_tir4_v11.local.json"
TIR_ENV="$TASK_ROOT/envs/tirlearner4-cpu-4.08.20261105T103817Z.05178998"
test -f "$OLD_CONFIG"
test -d "$TIR_ENV/conda-meta"
test ! -e "$CONFIG"
"$MICROMAMBA" run -p "$TASK_ROOT/envs/engine" python -m teflow fork-config \
  --config "$OLD_CONFIG" --output "$CONFIG" --run-id at_tir4_v11 \
  --tir-learner v4-cpu --tir-env "$TIR_ENV"
"$MICROMAMBA" run -p "$TASK_ROOT/envs/engine" python -m teflow plan --config "$CONFIG"
)
```

预期 `tir_backend.backend` 为 `v4-cpu`、版本 `4.08`。这一步不导入旧 EDTA 结果、不启动分析。不要给新配置导入 v3 的 EDTA 完成文件来绕过版本差异。

## 3. 有限封装验收

```bash
(
set -euo pipefail
TASK_ROOT=/home/cfy/te_project
MICROMAMBA=/home/cfy/minimamba/bin/micromamba
TE_REPO="$TASK_ROOT/TEflow-1.1.0rc1"
export PYTHONPATH="$TE_REPO/src"
export TEFLOW_REPOSITORY="$TE_REPO"
OUT="$TASK_ROOT/reviews/tir4_packaging.$(date -u +%Y%m%dT%H%M%SZ).$$"
"$MICROMAMBA" run -p "$TASK_ROOT/envs/engine" python "$TE_REPO/scripts/accept_tir_backend.py" \
  --config "$TASK_ROOT/at_tir4_v11.local.json" \
  --completed-experiment "$TASK_ROOT/reviews/tir4_full.20261107T083349Z.3b2f6ba0" \
  --output "$OUT"
)
```

预期 `TIR4_PACKAGING_ACCEPTANCE_PASSED`，并输出反馈包路径。这会运行所选分支的依赖探针和 v4 的实际 CPU 模型探针，并读取旧完整实验的原始序列/坐标；不会调用全基因组发现，不会改旧结果。如果旧完整实验的 genome.fa.mod 已清理，可去掉 `--completed-experiment` 两项参数，仅完成安装与适配验收，记录中会相应缺少历史序列复核。

## 4. hAT 中间结果只读审计

```bash
(
set -euo pipefail
TASK_ROOT=/home/cfy/te_project
MICROMAMBA=/home/cfy/minimamba/bin/micromamba
TE_REPO="$TASK_ROOT/TEflow-1.1.0rc1"
NATIVE="$TASK_ROOT/reviews/tir4_full.20261107T083349Z.3b2f6ba0/runs/v4/genome.fa.mod.EDTA.raw/TIR/TIR-Learner-Result"
OUT="$TASK_ROOT/reviews/tir4_hat_audit.$(date -u +%Y%m%dT%H%M%SZ).$$"
"$MICROMAMBA" run -p "$TASK_ROOT/envs/engine" python "$TE_REPO/scripts/audit_tir_checkpoints.py" \
  --native-dir "$NATIVE" --sites "$TE_REPO/examples/tirlearner4/hat_watchlist.tsv" --output "$OUT"
tar -czf "$OUT.feedback.tar.gz" -C "$OUT" .
printf '反馈包：%s\n' "$OUT.feedback.tar.gz"
)
```

`AUDIT_READY` 表示四个中间文件均可读取；`AUDIT_PARTIAL` 表示部分文件缺失、超过解压上限或结构不符，不等于没有候选。工具默认每个文件最多读取 128 MiB 解压数据，最多保存 10,000 个匹配详情。它保留精确、任意重叠和双向 80% 重叠计数，不以这些计数自动判定真假。

第 3、4 节各自独立，任一失败不应触发安装重做或全基因组重跑。回传这两个小反馈包即可。

## 5. 将来的正式运行与备用选择

完成封装验收后，正式新任务仍使用 `check`、`run --dry-run`、`run` 的常规入口。一次新的完整 v4 分析会重新计算依赖该库的后续分支；本轮无需执行它。

若要选择备用 v3，用新的运行名：

```bash
teflow fork-config --config at_tir4_v11.local.json --output at_tir3_backup.local.json \
  --run-id at_tir3_backup --tir-learner v3
```

这是显式改变算法的备用配置，不是 v4 失败时自动重试。新服务器默认安装还会新增 `tirlearner4-cpu` 环境；可先用 `bootstrap_server.sh ENV_ROOT --solve-only --only tirlearner4-cpu` 检查解算，再去掉 `--solve-only` 安装。既有合格环境通过 `--tir-env` 复用即可。
