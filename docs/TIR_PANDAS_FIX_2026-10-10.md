# 拟南芥首轮运行诊断与 pandas 修复

日期：2026-10-10。适用反馈包：`at_pilot_feedback.20261010T090253Z.tar.gz`；主日志：`at_pilot_run.20261009T095419Z.log`。

同日更正：若修复停在原脚本第 54 行，见 [repair fix1](REPAIR_SOLVER_FIX_2026-10-10.md)。原始 v0.1.3 压缩包需替换 `scripts/repair_edta_pandas.sh` 后再执行以下步骤。

## 诊断结论

本次流程在 EDTA 的 TIR-Learner 步骤失败。输入准备成功；未完成 EDTA 总阶段，未执行 TEtrimmer 及后续结果比较。

| 环节 | 反馈中的证据 |
|---|---|
| 安装探针 | 原有 8 项全部通过 |
| 输入准备 | 5 条核染色体，119,146,348 bp；Mt、Pt 排除 |
| 宿主 CDS | 接受 27,295 个基因的 CDS；155 个转录本被标记为不完整或非规范 CDS |
| LTR 候选发现 | 2026-10-09 18:02:42 CST 日志记录结束 |
| SINE 候选发现 | 18:12:18 CST 日志记录结束 |
| LINE 候选发现 | 19:51:04 CST 日志记录结束 |
| TIR | `check_TIR_TSD.py:118` 的 `family = x[0]` 报 `KeyError: 0` |
| 流程退出 | 20:07:58 CST，EDTA 返回 2；主流程历时约 2 小时 12 分 40 秒 |

“候选发现结束”仅引用上游日志，不等同于已对这些候选作完整性或生物学质量验收。反馈包没有包含大型候选文件。本次明确错误是 Python 索引兼容性异常，日志没有给出 OOM 或磁盘耗尽证据。

冻结清单记录 EDTA 2.3.0、TIR-Learner 3.0.7、pandas 3.0.6、swifter 1.4.0。pandas 3 开始将 `Series[0]` 中的整数始终解释为标签；TIR-Learner 的这一行需要按位置读取首列，因而在使用字符串列名的行上失败。[pandas 3.0 变更记录](https://pandas.pydata.org/docs/whatsnew/v3.0.0.html#other-removals)

随后出现的 `TIR-Learner_FinalAnn.fa`、GFF3 缺失和 `Raw TIR results not found` 是前述异常的连锁结果。不要依据最后一行的通用提示使用 `--force 1`，也不要将其解释为拟南芥没有完整 TIR。

原 doctor 检查了 CLI、EDTA 自带依赖检查和分类后端，没有执行到这一段 pandas 运算。因此，之前的 8/8 通过是安装探针通过，不能证明 TIR-Learner 所有内部步骤可运行。v0.1.3 专门补充此检查。

## 本次修复范围

- 将 EDTA 环境固定为 `tir-learner=3.0.7`、`pandas=2.3.3`。不修改第三方算法源码。
- doctor 新增 `edta_tirlearner_pandas`：在 EDTA 环境的 Python 中，对 3 行合成数据实际执行 `row[0]`。正常生产检查由 8 项变为 9 项。
- 此探针仅验证 pandas 索引语义，不执行完整 TIR-Learner、swifter 调度或真实基因组分析，也不评价生物学准确率。
- 随包包含此前服务器已手工采用的 RepeatMasker `-v` 修复。
- 更正后的修复脚本只允许安装计划涉及 pandas 和必要的 pytz、python-tzdata；从 `conda-meta` 为其余已安装包生成精确版本/build 约束。有其他包变化则在实际安装前停止。原先的 `--freeze-installed` 会连 pandas 也冻结，因此已移除。[micromamba 冻结请求实现](https://github.com/mamba-org/mamba/blob/main/libmamba/src/api/install.cpp)

更改 Conda 包或封装源码后，旧运行的软件指纹会改变。使用新的 `at_pilot_v02` 配置与工作目录，不删除旧 `run_manifest.json`，不修改旧阶段指纹，也不对 v01 直接使用 `--resume`。

此次修复会更新现有 EDTA 环境和 engine 中的 teflow 包；不会保留一份可原样执行的旧环境，但会备份原包规格和配置。旧项目目录、v01 输出、原 `envs/locks` 和旧配置均保留。v02 使用独立的 `env-locks/at_pilot_v02` 快照。Pfam、Dfam 无需重新下载。

考虑到 v01 只有 prepare 得到工作流完成记录，EDTA 原始步骤未被独立验收，v02 从头运行，不跨环境复制或硬链接这些未完成中间文件。新增约两小时的已运行部分，是本次保持来源清晰的代价；实际重跑耗时不能由首轮失败耗时推定。

## 服务器命令

将 `te-annotation-workflow-v0.1.3.tar.gz` 上传到 `/home/cfy/te_project/`。新版本解压到独立目录，保留旧代码目录。

```bash
TASK_ROOT=/home/cfy/te_project
export MICROMAMBA=/home/cfy/minimamba/bin/micromamba
TE_ENV="$TASK_ROOT/envs"
TE_REPO="$TASK_ROOT/te-annotation-workflow-v0.1.3"
CONFIG="$TASK_ROOT/at_pilot_v02.local.json"

if [[ ! -e "$TE_REPO" ]]; then
  tar -xzf "$TASK_ROOT/te-annotation-workflow-v0.1.3.tar.gz" -C "$TASK_ROOT"
fi

# 第一次可以先单独查看求解结果；不会安装或创建新配置。
bash "$TE_REPO/scripts/repair_edta_pandas.sh" "$TASK_ROOT" --solve-only

# 此命令会重新求解并检查事务，再执行修复、9 项 doctor 和工作流 dry-run。
# 任一步失败即停止；它不会启动全基因组分析。
bash "$TE_REPO/scripts/repair_edta_pandas.sh" "$TASK_ROOT" --apply
```

修复过程日志、原始配置和旧包规格位于 `repair_logs/edta-pandas-<UTC时间>-<PID>/`。成功末尾会显示 `REPAIR AND DRY-RUN PASSED`，并写入 `at_pilot_v02.dry_run_passed`。

若 `--apply` 在创建 v02 配置后失败，保留已经生成的目录并回传修复日志；不要删除目录后盲目重试。若只是数据库或配置检查失败，环境变更可能已经完成，应按实际完成位置处理。

仅在修复和 dry-run 成功后启动：

```bash
if [[ -f "$TASK_ROOT/at_pilot_v02.dry_run_passed" ]]; then
  mkdir -p "$TASK_ROOT/logs"
  RUN_LOG="$TASK_ROOT/logs/at_pilot_v02_run.$(date -u +%Y%m%dT%H%M%SZ).log"
  nohup "$MICROMAMBA" run -p "$TE_ENV/engine" \
    bash "$TE_REPO/scripts/run_server.sh" "$CONFIG" \
    > "$RUN_LOG" 2>&1 < /dev/null &
  RUN_PID=$!
  printf '%s\n' "$RUN_PID" > "${RUN_LOG%.log}.pid"
  printf 'PID: %s\nLog: %s\n' "$RUN_PID" "$RUN_LOG"
else
  echo "Repair/dry-run has not passed; no genome job launched." >&2
fi
```

沿用 32 线程和 131072 MB 预算；新结果目录为 `results/at_pilot_v02/arabidopsis_TAIR10/`。如果服务器需要通过 Slurm 运行，请使用新版本的 `submit_slurm.sh`，不要绕过调度要求。

完成或失败后打包：

```bash
"$MICROMAMBA" run -p "$TE_ENV/engine" teflow pack-feedback \
  --config "$CONFIG" \
  --output "$TASK_ROOT/at_pilot_v02_feedback.$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
```

回传反馈包和新一轮运行日志；若停在修复阶段，则回传对应的 `repair.log` 和 `solve.json`。修复阶段日志不在工作流反馈包内。

## 验证边界

本地使用 pandas 3.0.1 复现了与服务器 pandas 3.0.6 相同的整数标签索引错误；在独立临时目录加载 pandas 2.3.3 后，同一探针通过。没有修改系统 Python 的依赖。Bash 语法检查及 doctor 回归测试通过；Linux 单元测试与修复脚本模拟事务测试记录随版本提供。

服务器实际 pandas 降级求解、安装事务和完整 v02 运行尚未执行，必须以服务器的新日志为验收依据。不存在“已完成 TEtrimmer”或“已取得可用于 pCRE 的最终掩码”的结论。
