# 0.7.0rc1 服务器验收与交接

本轮交付候选版，先做小型验收与旧结果汇总。**不需要重新运行 EDTA、TEtrimmer、HELIANO、HiTE 或 RepeatMasker；不需要重装现有工具环境。** 源码、上传与反馈包不设 SHA-256 校验步骤；下载外部工具/数据库的既有校验保留。

## 1. 上传与独立解压

上传 `TEflow-0.7.0rc1-source.zip` 到 `/home/cfy/te_project/uploads/`。在一个子 shell 中执行，避免退出当前登录会话或遗留源码环境变量：

```bash
(
set -e
TASK_ROOT=/home/cfy/te_project
MICROMAMBA=/home/cfy/minimamba/bin/micromamba
TE_ENV="$TASK_ROOT/envs"
RC_REPO="$TASK_ROOT/TEflow-0.7.0rc1"
if [[ -e "$RC_REPO" ]]; then
    printf '%s\n' "候选版目录已存在，请保留；若已解压，请直接从第 2 节继续。"
    exit 1
fi
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m zipfile -e \
    "$TASK_ROOT/uploads/TEflow-0.7.0rc1-source.zip" "$TASK_ROOT"
cd "$RC_REPO"
export PYTHONPATH="$RC_REPO/src"
export TEFLOW_REPOSITORY="$RC_REPO"
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow --version
)
```

预期版本 `0.7.0rc1`。保留 `TEflow-0.6.0`、原配置和全部旧结果。

## 2. 小型验收

```bash
(
set -e
TASK_ROOT=/home/cfy/te_project
MICROMAMBA=/home/cfy/minimamba/bin/micromamba
RC_REPO="$TASK_ROOT/TEflow-0.7.0rc1"
cd "$RC_REPO"
"$MICROMAMBA" run -p "$TASK_ROOT/envs/engine" python \
    scripts/accept_release_candidate.py --root "$TASK_ROOT" --threads 8
)
```

只用 160 bp 合成输入、模拟工具和真实 Snakemake，依次测试取消/子进程清理/恢复/报告，以及串行/多库并行/独立分支失败。调度预算最多 8 CPU、4096 MiB；实际内存是观测模式，不是硬限额。输出到全新的 `acceptance/rc07.*`；不会访问旧分析的工作目录。预计数分钟，时间取决于服务器负载。

成功末尾应为 `RC_ACCEPTANCE_PASSED`，并给出本次 `.feedback.tar.gz`。如失败，回传同一反馈包；不要删除旧锁、杀同账号进程或重跑真实分析。

## 3. 从已经完成的 0.6 结果生成报告

通过第 2 节后：

```bash
(
set -e
TASK_ROOT=/home/cfy/te_project
MICROMAMBA=/home/cfy/minimamba/bin/micromamba
RC_REPO="$TASK_ROOT/TEflow-0.7.0rc1"
CONFIG="$TASK_ROOT/at_v06_parallel.local.json"
REPORT="$TASK_ROOT/reviews/at_v06_rc07.$(date -u +%Y%m%dT%H%M%SZ).$$"
export PYTHONPATH="$RC_REPO/src"
export TEFLOW_REPOSITORY="$RC_REPO"
"$MICROMAMBA" run -p "$TASK_ROOT/envs/engine" python -m teflow report \
    --config "$CONFIG" --output "$REPORT"
tar -C "$(dirname "$REPORT")" -czf "$REPORT.tar.gz" "$(basename "$REPORT")"
printf '报告反馈包：%s\n' "$REPORT.tar.gz"
)
```

该命令不会冻结旧运行、重跑分析或改写结果。报告包括 `report.md`、`report.json`、`stages.tsv`、`runtime.tsv`。旧 0.6 的启动器只记录 dispatch，因此报告中旧启动记录可能是 `scheduler_dispatch`，它不推翻已通过的阶段/最终输出验收。资源表应明确显示旧 QC 的 `initial_only` 采样限制。

## 4. 后续正式运行的命令接口

本节仅作接口说明，本次验收后无需运行新的真实基因组任务。

- `run-preview --config CONFIG`：区分已有完成回执与新工作；不调用工具。
- `run --config CONFIG --dry-run`：冻结新运行并检查 DAG。
- `run --config CONFIG`：正式启动，会进行真实分析。
- `status --config CONFIG`：同时查看阶段和启动器状态。
- `logs --config CONFIG`：最近的调度日志；加 `--stage tetrimmer` 查看该阶段。
- `cancel --config CONFIG`：仅向当前可验证的 0.7 运行提交取消请求。等待启动器为 `cancelled` 且 `runtime-status` 的 leases 为空。
- `run --config CONFIG --resume`：相同源码、配置及输入下显式恢复。

取消是协作式操作，纯 Python 步骤或大型输入读取可能先结束。不要仅凭 `CANCEL_REQUESTED` 认为已停止。旧 0.6 不支持此取消协议；恢复旧运行必须使用它自己的源码，不能用 RC 替换。`cleanup_unresolved` 或控制器意外退出需要反馈复核，不能自动删除状态文件。

## 5. 升级范围

第 2、3 节反馈通过后，再推进 GitHub 分支同步与实际 CI，随后决定 RC 标签/正式版。当前不改变库选择，不因短任务内存较低就自动降低预算，也不增加多物种和生产 systemd 分支。既有严格 B3 的未证明状态如实保留。
