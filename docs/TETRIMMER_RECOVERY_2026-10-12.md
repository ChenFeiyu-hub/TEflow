# TEtrimmer 实际输出复核与 v03 恢复

## 已确认的事实

用户回传的原始库及 provenance 文件 SHA256 与服务器 EDTA `complete.json` 完全一致。EDTA 和原始库 RepeatMasker 已成功；TEtrimmer 子命令退出 0，包装验收失败。Dof 系统发育的 IQ-TREE 进程与该工作流无关。

| 数量 | 正确解释 |
|---|---|
| 756 | 输入 EDTA 库条目、summary 覆盖的唯一输入数 |
| 816 | summary 行数；输入可以分裂为多个候选 |
| 176 / 580 | 唯一输入层面的 processed / skipped |
| 236 / 580 | summary 行层面的 processed / skipped |
| 254 | 最终合并 FASTA 条目数，尚非干净验收的最终结果 |
| 91 | 精修共识条目 |
| 7 | 低拷贝保留原序列 |
| 156 | 原输入回退，其中 132 条来自 skipped，24 条对应 Need_check/Need_ext |

24 条中 20 条为 Need_check、4 条为 Need_ext；全部与映射回的原始输入正向序列逐碱基一致，完整匹配数均至少 2。E0000014 实际保留 1,282 bp 原序列，summary 中的 8,077 bp 是被放弃的延伸候选。不能用这一候选长度描述保留的库序列。

上游 1.7.2 `functions.py:update_skip_and_need_check_cons_file` 与 `analyze.py` 有明确回退逻辑。当前已修正为检查原始序列身份、对应输入、完整匹配数及终态，记录 `sequence_origin`、`retained_length`、`summary_output_length`，而非放行任意带拒绝标签的序列。[上游函数](https://github.com/qjiangzhao/TEtrimmer/blob/v1.7.2/tetrimmer/functions.py#L2642-L2659)

另一个问题是真实依赖缺失：MSA `error_file.txt` 达 **4,421,454 bytes**，反馈包仅保留最后 **131,072 bytes**。尾部明确出现 curl 56 超时/重置及 TE-Aid `RepeatPeps.lib` 蛋白 BLAST 数据库缺失。不能据尾部证明全文只有这类错误。当前保留严格错误阻断；旧 TEtrimmer 库不能直接升级为完成状态。

TE-Aid 自带脚本在缺少 `.phr` 时尝试运行时联网下载并格式化 RepeatPeps。新版本将它前移到准备阶段：从已安装 RepeatMasker 的本地蛋白库复制，临时目录建 BLAST v4 索引，实际运行 `blastdbcmd -dbtype prot -info` 与单线程 `blastp` 自匹配，再发布并登记散列。不更改上游 TEtrimmer/TE-Aid 算法；也无需重下载 Pfam 或 Dfam。

## 恢复范围

完整发布包为 `te-annotation-workflow-v0.1.4.tar.gz`。使用独立 `at_pilot_v03`：

- 保留 v02、失败日志及 TEtrimmer 输出，供复核。
- 校验 v02 冻结配置、输入、软件、数据库、准备结果、EDTA/RM 完成记录和产物散列。
- 重新执行低成本 prepare，确认其产物与 v02 字节一致。
- 将已完成 EDTA / rm_edta 清单内的文件复制到 v03；写入来源清单和新的完成记录。不会复制其整个庞大临时目录，也不做可被改写的硬链接。
- TEtrimmer 在新目录从头运行；随后执行精修库 RepeatMasker、tracks、export。

迁移脚本仅接受已审计的 v02 源码指纹，不能作为任意版本通用导入器。旧配置及环境锁快照不覆盖；旧软件资产不允许变化。新增 TE-Aid 数据库单独锁入 v03。engine 沿用已有解释器/依赖，但通过新仓库 `src` 明确运行 0.1.4 封装代码。

## 服务器操作

上传完整 tar.gz 到 `/home/cfy/te_project/`，然后执行：

```bash
TASK_ROOT=/home/cfy/te_project
TE_REPO="$TASK_ROOT/te-annotation-workflow-v0.1.4"
export MICROMAMBA=/home/cfy/minimamba/bin/micromamba

if [[ ! -e "$TE_REPO" ]]; then
  tar -xzf "$TASK_ROOT/te-annotation-workflow-v0.1.4.tar.gz" -C "$TASK_ROOT"
fi
export PYTHONPATH="$TE_REPO/src${PYTHONPATH:+:$PYTHONPATH}"

# 只读核对：输出 old_run_verified=true 和本地 RepeatPeps 来源。
"$MICROMAMBA" run -p "$TASK_ROOT/envs/engine" \
  python "$TE_REPO/scripts/recover_tetrimmer_v03.py" --root "$TASK_ROOT"

# 核对通过后：构建数据库、创建 v03、复用完成产物并执行 dry-run。
"$MICROMAMBA" run -p "$TASK_ROOT/envs/engine" \
  python -u "$TE_REPO/scripts/recover_tetrimmer_v03.py" --root "$TASK_ROOT" --apply
```

脚本中的检查会在 apply 时重新执行。若找不到已安装的 RepeatPeps，可用 `--repeatpeps /实际/RepeatPeps.lib` 指定已核验本地库；脚本不悄悄下载 master。若 v03 已创建后某一步停止，保留目录和本次 `repair_logs/tetrimmer-v03-*`，回传后处理，不删除目录重试。

成功末尾应为 `V03 RECOVERY PREPARED AND DRY-RUN PASSED`；正常仅剩 tetrimmer、rm_refined、tracks、export、all 共 5 个任务。导入步骤可能提示缺少 Snakemake 原生历史 metadata；这些产物的来源由 `imported_from.json` 和 teflow 散列验证记录，微型恢复测试也覆盖了这一情况。此时才启动：

```bash
TASK_ROOT=/home/cfy/te_project
TE_REPO="$TASK_ROOT/te-annotation-workflow-v0.1.4"
export MICROMAMBA=/home/cfy/minimamba/bin/micromamba
if [[ -f "$TASK_ROOT/at_pilot_v03.dry_run_passed" ]]; then
  mkdir -p "$TASK_ROOT/logs"
  RUN_LOG="$TASK_ROOT/logs/at_pilot_v03_run.$(date -u +%Y%m%dT%H%M%SZ).log"
  nohup "$MICROMAMBA" run -p "$TASK_ROOT/envs/engine" \
    bash "$TE_REPO/scripts/run_server.sh" "$TASK_ROOT/at_pilot_v03.local.json" \
    > "$RUN_LOG" 2>&1 < /dev/null &
  printf '%s\n' "$!" > "${RUN_LOG%.log}.pid"
  printf '%s\n' "$RUN_LOG" > "$TASK_ROOT/logs/at_pilot_v03.latest.logpath"
  printf 'Log: %s\n' "$RUN_LOG"
else
  printf '未找到 v03 dry-run 通过标记，未启动。\n' >&2
fi
```

查看输出：`tail -n 80 -f "$(cat /home/cfy/te_project/logs/at_pilot_v03.latest.logpath)"`。不要终止另一个 Dof 项目的 IQ-TREE。

完成或失败后回传：

```bash
TASK_ROOT=/home/cfy/te_project
TE_REPO="$TASK_ROOT/te-annotation-workflow-v0.1.4"
export MICROMAMBA=/home/cfy/minimamba/bin/micromamba
export PYTHONPATH="$TE_REPO/src${PYTHONPATH:+:$PYTHONPATH}"
"$MICROMAMBA" run -p "$TASK_ROOT/envs/engine" python -m teflow pack-feedback \
  --config "$TASK_ROOT/at_pilot_v03.local.json" \
  --output "$TASK_ROOT/at_pilot_v03_feedback.$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
```

## 验证边界

本地已用实际回传库复核全部 254 条、核对输入文件散列，并运行错误阻断测试。微型真实 BLAST 测试验证了建库、打开、自匹配和旧数据库备份。完整服务器恢复和 v03 基因组分析仍需用户执行；本地验证不能替代其结果。完整测试状态另见 `TEST_STATUS_2026-10-12.md`。
