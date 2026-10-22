# TE-Aid 清理警告复核与 v0.2.2 恢复

日期：2026-10-15。对象：`at_compare_v021 / arabidopsis_TAIR10`。这是对已提供反馈包的复核；没有访问或操作用户服务器。

## 1. 结论与边界

**现有证据支持复用这次 TEtrimmer 的最终序列库，进入下游 RepeatMasker、QC 和导出。无需重新进行 EDTA 或 TEtrimmer 发现计算。** 原有失败目录完整保留，新建 `at_compare_v022` 承接结果。

TEtrimmer 子命令已经以退出码 0 完成，但上层封装正确拦截了 183 字节的非空错误文件。其唯一内容是针对 `E0000733` 的 `rm: cannot remove 'header': No such file or directory`。用户已确认所见 IQ-TREE 进程属于其他项目，因此它不构成本工作流仍在运行的证据，也不应终止它。

核对对象包括原始反馈包、完整错误记录，以及补充的 `at_compare_v021.teaid_review.20261015T023614Z.tar.gz`。补充包有 11 个普通文件，包含输入库、最终库和受影响条目的精修证明材料。原始冻结清单、请求回执及上游源码身份也已核对。

| 复核项目 | 观察结果 |
|---|---|
| 输入家族及终态覆盖 | 756 / 756；无遗失输入 |
| 最终保留序列 | 252 条 |
| 实际序列来源 | 精修共识 88；低拷贝原序列 7；原序列回退 157 |
| 受影响条目 | `E0000733`，DNA/CMC-EnSpm，仍保留 `Reco_check` 标签 |
| 独立共识重建 | 从 12 条、每条 4,829 列的比对按上游 0.7 阈值重建，与最终 FASTA 完全相同 |
| 证明图 | 8 页均已逐页检查，包含精修前后、蛋白/Pfam 证据与比对图 |
| ORF 表 | 补充包中没有；默认清理已删除逐查询中间目录，不能宣称其表头通过复核 |

`summary.txt` 有 816 行，是因为部分输入产生多个候选；236 个 processed 行不等于 236 个独立输入。候选评价标签也不能替代实际保留序列的来源。252 条结果不是 252 条都经过成功精修，更不能据此宣称 ET 优于 E。

### 原因定位

已校验散列的 TEtrimmer 1.7.2 `TEaid.py` 调用 TE-Aid 时没有指定 `cwd`。TE-Aid 脚本在第 340–342、354–356 行使用固定相对文件名 `header`；多个进程共享当前目录，会互相覆盖或删除这个临时文件。此次日志与该并发缺陷吻合。

受影响的清理发生在绘图步骤之后。上游后续蛋白分析读取的是原始 `orftetable.txt`，而上述表头拼接影响的是另一个导出文件 `<query>.orftable.txt`。这些源码证据、完整终态覆盖以及精确共识复现共同支持**序列层面的限定复用**；它们没有恢复已经删除的 ORF 表，也没有完成独立生物学验证。

### 修复方式

新封装仅为每次 TE-Aid 子进程创建独立临时工作目录，保留绝对输入/输出路径和全部生物学参数。Python 模块局部代理在 Linux fork 子进程中继承；父进程目录和其他工具不变。上游三个关键源码文件须匹配已核对的 1.7.2 散列，否则拒绝启动。没有修改已安装的 TEtrimmer/TE-Aid 文件，也没有屏蔽 stderr 或改为 `rm -f`。

专用恢复程序只接受源码中写死的这一次配置、冻结清单、输入库以及 20 个证据文件的散列；也会重新检查当前数据库、软件和输入是否与原冻结状态一致。额外错误、不同输出、不同配置或仍有相关活动进程都会阻止恢复。常规 `audit_tetrimmer` 和普通 `import-stage` 不放宽准入标准。

新阶段记录 `complete_with_reviewed_warning`，保留原错误；原 `failed.json`、`request.json` 和旧审计文件另存于 `source_evidence/`。`reviewed_import.json` 分别记录实际生产命令、今后重算用的新命令，以及 `computation_rerun=false`。最终序列内容没有被人工修改，新的标准库仅按既有规则规范化名称。

## 2. 上传、校验和准备新运行

将发布包 `te-annotation-workflow-v0.2.2.tar.gz` 和 `SHA256SUMS-v0.2.2.txt` 上传到 `/home/cfy/te_project/releases/`。不覆盖旧仓库，不移动旧结果，不重新安装环境或下载数据库。

以下代码放在子 shell 内，失败会停在当前步骤而不退出登录终端。校验和文件同时列有 ZIP 和 TAR，这里只核对实际上传的 TAR。

```bash
(
  set -euo pipefail
  trap 'echo "Recovery preparation stopped at line $LINENO; retain the log and new directory for review." >&2' ERR
  TASK_ROOT=/home/cfy/te_project
  TE_ENV="$TASK_ROOT/envs"
  MICROMAMBA=/home/cfy/minimamba/bin/micromamba
  TE_REPO="$TASK_ROOT/te-annotation-workflow-v0.2.2"
  OLD_CONFIG="$TASK_ROOT/at_compare_v021.local.json"
  CONFIG="$TASK_ROOT/at_compare_v022.local.json"
  cd "$TASK_ROOT/releases"
  grep -E '  te-annotation-workflow-v0\.2\.2\.tar\.gz$' SHA256SUMS-v0.2.2.txt | sha256sum -c -
  if [[ -e "$TE_REPO" ]]; then
    echo "Destination repository already exists; do not overwrite: $TE_REPO" >&2
    exit 2
  fi
  tar -xzf te-annotation-workflow-v0.2.2.tar.gz -C "$TASK_ROOT"
  export TEFLOW_REPOSITORY="$TE_REPO"
  export PYTHONPATH="$TE_REPO/src${PYTHONPATH:+:$PYTHONPATH}"
  mkdir -p "$TASK_ROOT/repair_logs"
  LOG="$TASK_ROOT/repair_logs/teaid_v022.$(date -u +%Y%m%dT%H%M%SZ).log"
  {
    "$MICROMAMBA" run -p "$TE_ENV/engine" python "$TE_REPO/scripts/recover_teaid_cleanup_v022.py" \
      --config "$OLD_CONFIG" --output "$CONFIG" --run-id at_compare_v022 --apply || exit "$?"
    "$MICROMAMBA" run -p "$TE_ENV/engine" bash "$TE_REPO/scripts/run_server.sh" \
      "$CONFIG" --dry-run --target-stage export_edta_tetrimmer || exit "$?"
    echo REVIEWED_RECOVERY_AND_DRY_RUN_PASSED
  } 2>&1 | tee "$LOG"
)
```

预期出现 `reviewed_recovery_prepared`，最后出现 `REVIEWED_RECOVERY_AND_DRY_RUN_PASSED`。SHA256 核验和 doctor 会读取已有软件/大文件并执行小型依赖测试，可能需要等待；不会启动真实基因组发现分析。此次需要核验的数据库不重新下载。

新建配置继承旧配置的所有分支、生物学参数、32 核和 131072 MB 预算，替换 TEtrimmer 隔离入口，并将字节相同的 HiTE 包装脚本定位到新仓库；镜像本身及身份记录保留。随后导入已经完成的 E/RM 与这次经复核的 ET。共享 tracks、QC 和导出在新命名空间重建。

如果准备失败，保留日志和新目录，不删除旧错误、不编辑冻结清单，不重复覆盖新配置。默认不带 `--apply` 的 Python 恢复命令只检查源状态，但同样要求目标尚不存在。依赖校验成功后才冻结新运行；源文件改变、目标已存在等情况需要根据具体日志处理。

## 3. 后台完成 ET 下游

仅在上一段成功后执行。dry-run 预期只安排尚未完成的 tracks、RM、QC、export；不应再次安排 `stage=tetrimmer` 或 `stage=edta`。保留旧运行目录即可，不需要向新运行手工复制其他文件。

```bash
TASK_ROOT=/home/cfy/te_project
TE_ENV="$TASK_ROOT/envs"
TE_REPO="$TASK_ROOT/te-annotation-workflow-v0.2.2"
CONFIG="$TASK_ROOT/at_compare_v022.local.json"
MICROMAMBA=/home/cfy/minimamba/bin/micromamba
RUN_LOG="$TASK_ROOT/at_compare_v022.ET.$(date -u +%Y%m%dT%H%M%SZ).log"
nohup "$MICROMAMBA" run -p "$TE_ENV/engine" bash "$TE_REPO/scripts/run_server.sh" \
  "$CONFIG" --target-stage export_edta_tetrimmer > "$RUN_LOG" 2>&1 < /dev/null &
RUN_PID=$!
printf 'PID=%s\nLOG=%s\n' "$RUN_PID" "$RUN_LOG"
tail -n 60 "$RUN_LOG"
```

此命令只推进 ET 分支，不启动 HiTE/HELIANO。最终检查：

```bash
export TEFLOW_REPOSITORY="$TE_REPO"
export PYTHONPATH="$TE_REPO/src${PYTHONPATH:+:$PYTHONPATH}"
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow status --config "$CONFIG"
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow pack-feedback --config "$CONFIG" \
  --output "$TASK_ROOT/at_compare_v022.feedback.$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
```

ET 的分支结果应位于 `results/at_compare_v022/arabidopsis_TAIR10/edta_tetrimmer/`，存在 `manifest.json`，并有对应 `export_edta_tetrimmer` 完成回执。其余启用分支尚未执行时，整个比较运行尚未完成是正常现象。

ET 成功后，下一步先导出同一新运行的 E 基线（目标 `export_edta`，复用已导入 E/RM），比较类别覆盖、宿主/域证据、回退比例与启动子机会数，再分别推进 HELIANO 和 HiTE。当前不基于条目数自动选优，也不因恢复成功取消 `Reco_check`。

## 4. 已测范围

- Windows 单元测试：62 项，50 通过，12 项因 Linux/可选运行时条件跳过。
- Linux 单元测试：62 项，61 通过，1 项可选 micromamba 离线 solver 测试未启用；本次没有修改求解器修复逻辑。
- 并发测试：两个子进程各自持有 `header`，线程调用及真实 fork 继承均通过；非零退出码和真实 stderr 原样保留。
- 上游接口核对：实际散列锁定的 `TEAid` Python 类，在真实 fork 与模拟 TE-Aid 可执行程序下通过；没有将其描述成完整安装后的 TE-Aid 基因组试验。
- 实际附件：原审计可重现，12 条比对精确生成最终共识，限定恢复验证通过；注入额外错误会被拒绝。
- 真实 Snakemake + 模拟上游工具：七分支流程及专用恢复流程通过；后者检查旧证据不变、服务器入口 dry-run、无 TEtrimmer 重算、下游完成、重复运行与反馈打包。
- **尚待服务器确认**：新 wrapper 在用户已安装环境中的 doctor、实际恢复执行、ET 的全基因组 RM/QC/导出，以及后续分支的生物学比较。上述脚本负责前两项和接续启动。

验证摘要位于 `docs/validation/*v0.2.2*.json`。发布包只包含工作流源码、测试和说明，不打包基因组、TE 库、证明 PDF、环境或容器。恢复使用服务器原目录中的散列匹配证据，原始数据无需再次上传。
