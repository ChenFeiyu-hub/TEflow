# 0.3.0 服务器交接：已有 v022 结果的局部候选审核

本次只准备和运行 11 个候选的补充蛋白 QC。继续读取 `at_compare_v022.local.json`，不新建全基因组比较运行，不重新运行 EDTA/TEtrimmer/HELIANO/HiTE/RepeatMasker，不覆盖原输出。包已提供本次候选 ID 清单；它是案例审核清单，不是普适过滤阈值。

## 1. 上传与展开新版本

上传 `te-annotation-workflow-v0.3.0.zip` 和同名 `.sha256` 至 `/home/cfy/te_project/`。使用新目录，保留原 v0.2.2 仓库。

```bash
set -Eeuo pipefail
TASK_ROOT=/home/cfy/te_project
TE_ENV="$TASK_ROOT/envs"
MICROMAMBA=/home/cfy/minimamba/bin/micromamba
cd "$TASK_ROOT"
sha256sum -c te-annotation-workflow-v0.3.0.zip.sha256
test ! -e "$TASK_ROOT/te-annotation-workflow-v0.3.0"
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m zipfile -e \
  "$TASK_ROOT/te-annotation-workflow-v0.3.0.zip" "$TASK_ROOT"
TE_REPO="$TASK_ROOT/te-annotation-workflow-v0.3.0"
chmod +x "$TE_REPO"/scripts/*.sh
export TEFLOW_REPOSITORY="$TE_REPO"
export PYTHONPATH="$TE_REPO/src${PYTHONPATH:+:$PYTHONPATH}"
cd "$TE_REPO"
"$MICROMAMBA" run -p "$TE_ENV/engine" python scripts/verify_source.py
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow --version
```

应显示源码核验通过和 `0.3.0`。无需重新 bootstrap/install，旧 engine 内装过的 teflow 不会盖过这里显式选定的源码。若目标仓库已经存在，先核对来源和清单；不要覆盖一个已经用于审核准备的仓库。

## 2. 后台执行本批候选审核

下面启动器先核验旧输入/回执，准备候选与局部序列，再进行 8 核 DIAMOND QC。读取全基因组参考及全部 EH `.align` 是序列/坐标验证，不是重新搜索基因组。没有新的数据库下载。

```bash
OLD_CONFIG="$TASK_ROOT/at_compare_v022.local.json"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REVIEW="$TASK_ROOT/reviews/at_v022_candidates_v030.$STAMP"
RUN_LOG="$TASK_ROOT/at_v022_candidates_v030.$STAMP.log"
FAMILIES="$TE_REPO/examples/at_v022_review_families.txt"
test -s "$OLD_CONFIG"
test -s "$FAMILIES"
export TEFLOW_REVIEW_SAMPLE=arabidopsis_TAIR10
export TEFLOW_REVIEW_BRANCH=edta_plus_heliano
nohup "$MICROMAMBA" run -p "$TE_ENV/engine" \
  bash "$TE_REPO/scripts/run_candidate_review.sh" \
  "$OLD_CONFIG" "$REVIEW" "$FAMILIES" 8 \
  > "$RUN_LOG" 2>&1 < /dev/null &
REVIEW_PID=$!
printf 'PID=%s\nREVIEW=%s\nLOG=%s\n' "$REVIEW_PID" "$REVIEW" "$RUN_LOG"
```

用这一 PID/命令行和目录确认归属，不以服务器上任意 `python`/`iqtree` 进程判断本任务是否完成。

```bash
tail -n 70 "$RUN_LOG"
ps -ww -p "$REVIEW_PID" -o pid,ppid,etime,time,pcpu,args
```

成功结束标志是 `CANDIDATE_REVIEW_COMPLETED`，同时存在 `protein_qc/complete.json` 和 `${REVIEW}.feedback.tar.gz`。目录中 `review.json` 的 prepared 状态只说明证据准备完成，不等于蛋白 QC 已完成。正常结束后进程查询找不到 PID 是预期现象。

本任务只解除选中候选的目标数/HSP 报告限制；它仍有上游启发式和非包围条件，不能将无命中解释为安全 TE。每个外部命令最多 6 小时；实际持续时间依赖参考蛋白和候选长度。

## 3. 返回反馈与失败时的处理

成功后返回这两个文件：

```text
<REVIEW>.feedback.tar.gz
<REVIEW>.feedback.tar.gz.sha256
```

包内包含候选库、原生/附加位点表、基因/转录本上下文、边界比对输入、扩展蛋白 HSP、旧新检索差异、原始比对投射、命令和回执；不包含原基因组、GTF、完整 `.align`、蛋白 FASTA 或索引。原始比对中与候选有关的选中子集会保留，便于核验。

若失败，保留目录和日志；不要删除结果或修改旧配置后续跑。脚本不会自动清理/重试。准备阶段失败时请先返回 `$RUN_LOG` 及 `prepare_failed.json`（若存在）；准备成功、蛋白检索失败后可打包：

```bash
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow review-pack \
  --review "$REVIEW" --output "${REVIEW}.failed.feedback.tar.gz"
```

若在新终端操作，重新设置第 1 节中的 `TASK_ROOT/TE_ENV/MICROMAMBA/TE_REPO/TEFLOW_REPOSITORY/PYTHONPATH`，再把 `REVIEW` 设为实际记录的路径。

## 4. 本轮审核之后

先比较扩展蛋白跨度、原生注释 CDS、各转录本和局部重复片段，再审视 H0000139/H0000060 等候选的端点。`boundary_inputs.tsv` 映射到每家族的带侧翼 FASTA，可供既有 MAFFT/可视化工具使用；此时并不声称其中每条 raw fragment 是完整拷贝。

本版先交付有限、可复核的序列和证据。接收局部 QC 后再确定需要哪几条做进一步人工边界对照，不要求本轮同时重跑全基因组或做统一大规模 MSA。所有接纳初始为 pending。

如已完成明确人工判断，可另复制模板、填写证据再导出；以下不是当前服务器任务的必需步骤：

```bash
cp "$REVIEW/decisions.template.tsv" "$REVIEW/decisions.tsv"
# 编辑 decisions.tsv：填写生物学状态、目录/屏蔽决策、审核者、日期、证据和理由
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow review-export \
  --review "$REVIEW" --decisions "$REVIEW/decisions.tsv" \
  --output "$TASK_ROOT/reviews/at_v022_curated_candidates_v030"
```

导出的 `catalog.fa` 和 `mask_library.fa` 仅属于本批候选；不能直接替代包含 E 基线的全流程库。生成新基因组 mask 需要后续明确的新运行。本轮不依赖 pCRE，也不根据下游预测成绩挑 TE 候选。
