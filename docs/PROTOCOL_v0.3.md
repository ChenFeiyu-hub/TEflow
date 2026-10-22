# 0.3：通用注释与独立候选审核协议

日期：2026-10-16。发现、分类和标准化规则沿用 0.2，并保留 0.2.1/0.2.2 的接口与故障保护；本文件规定 0.3 的增量。新版本不改写已经冻结的 v022 运行。

## 1. 软件定位和默认值

核心产物是 TE 序列库、来源表、原生结构候选、同源匹配注释、类别覆盖、重复/低复杂度轨道、BED/GFF3 和 softmasked FASTA。基因组注释、TE 生物学及其他区域研究可以直接使用这些通用接口。基因 GTF/GFF3 与蛋白参考可选；缺失时显式记录未评估。表达数据、pCRE 训练标签或性能不是 TE 发现、筛选和默认接纳条件。

`init-server` 默认 `baseline`，新配置 `evaluation.promoter_analysis=false`。`--promoter-analysis` 显式启用原有启动子机会数分析；关闭时不输出空的 `promoters.tsv`/机会数表。有基因注释时仍输出 `gene_context_coverage.tsv`，包括基因体、CDS、exon 区间与 TE 的描述性覆盖。

为保证旧配置语义，缺少 `promoter_analysis` 字段的历史 schema 2 配置仍沿用原启用行为；不要通过编辑旧配置关闭它。迁移到新运行时明确选择开关。临时 gene-boundary 启动子统计不定义任何下游最终窗口协议。

示例 `general_genome.json` 可用于自定义样本路径和核序列排除项；比较预设仍只在拟南芥实测。预设名是便利入口，不是声称其他物种已验收。未启用的分支不增加工具依赖。

## 2. RepeatMasker 原始 alignment 契约

新 RM 阶段继续请求 `-a`。有 `.out` 命中时必须有非空 `genome.fa.align`，并登记到 `complete.json.outputs`；无命中/空库允许无 alignment，记录原因。

旧运行可能只登记 `.out`。`alignment_artifacts.locate_alignment` 首先检查阶段目录，再检查保存的成功 `run.log.command.json.cwd`。使用原目录时要求 `.out` 和命令记录的 SHA256 与导入结果完全一致。若原回执锁定了 alignment，验证该散列；否则只称为“本次补登记的辅助文件”，不伪称旧回执已经锁定它。找不到文件时停止局部审核，保留路径，不自动重跑 RM。

新 EDTA/RM 导入在满足原迁移条件的基础上复制可核验的 alignment 并记录 `alignment_source.json`。旧回执保持不变。当前 v022 局部审核只读取旧运行，不需要执行迁移。

## 3. 原始比对与最终注释必须区分

`repeat_alignments.py` 支持本流程 RMBlast 后端 `-a` 的带 raw match ID/final group ID 文本格式。所有块核验：标题坐标、chunk 连续性、正反链、gap 长度、实际参考序列及库序列。输出坐标统一为 0-based、右开；未知格式或不一致直接停止。

最终 `.out` 只按参考序列、方向、组号和基因组重叠连接原始比对。`final_to_raw.tsv` 保留最终家族、原始家族集合、比对 ID、覆盖和未覆盖 bp。一个最终家族可能连接多个原始家族。绝不按最终库坐标线性缩放或推断整个最终片段的蛋白来源。[RepeatMasker 官方输出说明](https://www.repeatmasker.org/webrepeatmaskerhelp.html)

蛋白跨度通过原始对齐列投射；库侧 gap 对应的基因组插入另列。投射使用 DIAMOND 报告的核酸跨度包围区，不等同于每个碱基均被蛋白残基支持。候选 QC 输出按 raw block 列示、并集 BED 只表示原始支持；不把相互重叠比对逐条相加，也不把它冒充经过最终 `.out` 裁定的新增 mask。

## 4. 独立审核目录

`review-prepare` 支持两种输入：

1. 完成的工作流配置、样本和分支。核验旧 run/config 身份、原输入、prepared 文件和相关阶段回执，允许旧实现指纹不同于当前版本。
2. 显式 genome/library/rm-out/rm-align 文件；可附加 annotation、prepared manifest、原生位点、蛋白或 CDS。所有散列从本次登记起锁定，不假定上游曾冻结。

两种模式均须提供唯一候选 ID 清单；只读取参考/注释，向全新审核目录写入。`review.json` 保存参数、原文件散列、版本/源码指纹和派生产物散列。源文件和派生证据发生变化即拒绝执行。已存在的审核或 QC 目录不会被覆盖/清理；失败目录保留，重试需新目录。

`decisions.template.tsv` 是锁定的空模板。需要人工决策时另复制为 `decisions.tsv`，不可修改模板或科学表格。审核包可在源文件无法访问时打包既有证据，但仍验证本地证据完整性。

## 5. 原生候选、侧翼与转录本证据

HELIANO 的 `native_sequence` 父子关系可定位原生片段；E+H 精确/RC 别名沿父记录追溯。要求原生长度和非 N 序列与参考相符，拒绝全 N 的空洞匹配。`official_consensus` 的 subfamily 支持不强行转换成精确原生位点。

每候选保留可核验原生位点，并从该原始家族比对中按库跨度覆盖比例、score、ID 确定性排序，选择最多 10 个不相互重叠的附加片段；不与该候选已有原生位点重叠。两侧各取 500 bp，染色体端点裁切并记录实际长度。条数上限与侧翼长显式冻结；这是一套有限的案例取样，不估计拷贝总数。

`loci.tsv`、`locus_genes.tsv`、`locus_transcripts.tsv` 保存注释状态、基因/各转录本 CDS 并集、重叠和完整包含关系。解析 GTF gene_id/transcript_id 和 GFF3 Parent 链；未解析特征数另记。CDS 并集完整包含不证明独立功能宿主基因，也不证明候选是假 TE。剪接证据来自已有注释，没有重新运行基因预测或 splice-aware aligner。

`locus_flanks.fa` 与 `boundary_inputs/*.fa` 是可供 MAFFT/可视化复核的候选局部序列，`boundary_inputs.tsv` 给出家族与文件对应关系。raw fragment 可能只是基因相似片段，不能将它的两端当作完整插入端点。0.3 不自动修剪、延长候选或裁断基因捕获片段。

## 6. 有界扩展蛋白 QC

`review-plan` 不启动外部工具。`review-run` 只搜索候选库，默认 8 核、每命令 6 小时超时，允许 1–32 核，Linux 子进程继承 CPU affinity。建立新的局部 DIAMOND 数据库，记录工具版本、可执行文件/Conda 元数据散列和完整 argv。它不是完整内存硬限制。

固定参数：DIAMOND `blastx --max-target-seqs 0 --max-hsps 0 --evalue 1e-5 --query-gencode 1`；其余搜索设置保留已安装版本默认，并锁版本。不额外增加 range-culling/frameshift 模式。字段：`qseqid sseqid pident length evalue bitscore qstart qend sstart send qframe btop qlen slen`。校验 BTOP 消耗的 query/subject 长度、阅读框和坐标，再统计跨度；原 BTOP 保留。

`0` 解除报告数量上限，并不是穷举所有生物学同源关系。`max-target-seqs` 也影响搜索启发式；多个 HSP 必须满足上游非包围条件。因此重复命中同一蛋白的同一范围不一定全部报告，新旧输出也不保证严格包含关系。扩展 HSP 会增加计算量，所以只用于选中的小批候选。[DIAMOND 官方参数说明](https://github.com/bbuchfink/diamond/wiki/3.-Command-line-options)

优先使用明确提供的蛋白 FASTA；若使用 prepared CDS，按标准核遗传密码翻译并拒绝非完整 frame/内部终止。参考 CDS 的筛选和转录本策略沿用已冻结输入，不能因此声称排除了全部 TE 编码基因。当前不支持替代遗传密码。

若原分支有 top-5 结果，保存选中家族的原记录并输出 `previous_vs_expanded.tsv`。目标数和跨度变化是检索证据差异，不是误报率，也不直接决定接纳。无命中显式记为 `no_reported_hit_not_negative_truth`。

## 7. 两类决策和可接纳接口

| 维度 | 允许值 | 用途 |
|---|---|---|
| biological_status | unreviewed / supported_te / gene_capture_candidate / boundary_uncertain / likely_host_fragment / unresolved | 当前生物学判断 |
| catalog_action | pending / retain / exclude | 是否进入本批审核后的目录库 |
| masking_action | pending / include / exclude | 是否进入本批屏蔽用途候选库 |

初始全部 unreviewed/pending；改变任何决策需 reviewer、reviewed_at、evidence、reason。masking include 必须同时明确 retain，且处于 supported_te 或 gene_capture_candidate。基因捕获状态也可留在目录、屏蔽 exclude；规则不把基因捕获自动等同于假阳性。[Helitron 基因捕获原始研究](https://pmc.ncbi.nlm.nih.gov/articles/PMC2785268/)

`review-export` 生成 `catalog.fa`、`mask_library.fa`、决策表和回执。只含本批明确接纳的候选，可能合法为空；不能直接替换全基因组库。本版不生成新的坐标 mask，不按最终家族 ID 粗略删 `.out` 片段。若要正式使用新库，须明确创建新注释运行并回贴/评价边界，保留原始比较分支。

## 8. 当前边界

已实现工程接口和本批数据回放；待服务器返回 11 候选扩展蛋白结果，再完成端点和其他片段的人工/已发表工具局部对照。本版不引入 TE 新发现算法、自动边界分类器或预测性能驱动筛选。无完整插入/家族真值 benchmark，不声明跨物种准确率和普适默认获胜分支。
