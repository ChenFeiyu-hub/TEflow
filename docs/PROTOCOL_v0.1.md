# v0.1 实现协议与边界

冻结的是一个可评价的计算流程，生物学优劣仍等待服务器结果。任何参数、数据库、软件环境、输入或封装代码变化，都构成新运行，不覆盖旧运行。

## 1. 参考范围

| 样本 | 主分析序列 | 单列且暂不注释的序列 |
|---|---|---|
| TAIR10 | 1–5 | Mt、Pt |
| CC-4532 v6.0 | chromosome_01–17、contig_18–57 | plastome、mitogenome、mating_type_plus |

排除的是明确指定的 ID，不根据名称猜测。未定位 contig 保留。先检查所有注释坐标都存在于原始 FASTA，且没有越界，然后按同一策略分区。分析时将 ID 映射为短别名，坐标与序列长度不变；导出时恢复原 ID。原文件不改动。

EDTA 会把非 A/C/G/T 字符转为 N；适配器检查这种预期标准化，不允许额外删碱基、改坐标或改 ID。最终 softmasked FASTA 从准备阶段保留的原始核序列生成，大小写还原后必须与原序列相同。

宿主 CDS 可以直接提供，也可以从匹配注释提取。自动提取要求同一链／序列、CDS 不重叠、phase 连续、完整起止密码子、无内部终止、长度至少 90 bp；GTF 独立 stop_codon 按注释补齐；每个基因选择最长合格转录本。显式标记的 TE 基因排除。它是保守的自动宿主 CDS 集，不能称为人工验证的非 TE 基因库。所有筛选数量和转录本映射保留。

## 2. 固定比较

EDTA：`--species others --step all --sensitive 1 --anno 1 --evaluate 0 --force 0 --wholeelement 0 --overwrite 0 --debug 1`。`--cds` 采用上述集合；`--maxdiv` 默认为 40。保留原始运行目录，首次 pilot 暂不启用昂贵的一致性评价。没有 rice 库强制兜底，没有额外重复运行同参数 LTR 发现。

TEtrimmer：固定可获取的正式版本 1.7.2，显式输入规范化 EDTA 库；`--classify_all`，不启用 `--fast_mode`、`--dedup` 和 `--genome_anno`。Pfam 必须事先安装并登记散列，防止运行中自动下载。TE-Aid 的 RepeatPeps 蛋白库从已安装 RepeatMasker 本地文件准备，独立构建 BLAST 蛋白索引、检索预检并登记散列。上游默认延伸、聚类等参数由锁定版本决定，`--help` 和环境锁文件归档。

TEtrimmer 的 `summary.txt` 是 CSV。每个输入必须有 `processed` 或 `skipped` 终态；保留序列必须能连到 summary，Need_check／Need_ext 描述的延伸候选不应直接进入最终合并库；上游可以在完整匹配数至少 2 时回退原输入。验收要求回退序列 ID 对应输入、序列逐碱基一致、summary 完整匹配数满足阈值，并单列实际保留长度与被放弃候选长度。skipped 原序列回退采用同样身份和拷贝证据检查；低拷贝保留单列。有非空错误文件时封装会失败，不把退出码 0 视为完全成功。跳过条目、低拷贝、Reco_check 和其他评价状态单列复核。Good／Perfect 等是上游自动标签，不能直接解释为真实准确率。

两库回贴：同一核基因组、RepeatMasker 4.2.4、RMBlast、`-s -nolow -no_is -div 40 -gff -a`、显式 `-lib`。不额外混入 Dfam 基因组命中。Dfam 仍可能参与上游分类，因此必须冻结且不得拿同一知识库当独立真值。

TRF：`2 7 7 80 10 50 500 -d -h`。dustmasker：`-level 20 -window 64 -linker 1 -outfmt fasta`。独立记录轨道，保留未合并来源；区间并集只是覆盖计算，不进行新的 TE 拷贝拼接。

## 3. 资源规则

工作流总预算初始建议 32 个核，内存由服务器实际分配填写。不是默认启用 128 个逻辑线程。`io_heavy=1` 让准备、发现、精修、回贴和导出顺序使用磁盘。TRF、dust 和导出只请求 1 个线程。

RepeatMasker 的 RMBlast 每个并行任务可使用 4 个核，因此 `-pa=floor(预算/4)`。TEtrimmer 的 `num_threads` 是并行家族 worker 数，本版也采用 `floor(预算/4)`，32 核预算下先启动 8 个 worker。上游个别子程序可能有独立并行行为；这些预算不是操作系统硬限额，服务器 pilot 要结合峰值 RSS、CPU 和 I/O 调整。Slurm 应同时限制实际 CPU／内存；普通终端需避开其他用户的资源。

`mem_mb` 是调度预算，不是软件实际内存需求的预测；普通终端不强制进程内存上限。不要把教程示例内存当成已经实测足够。数据和中间产物优先放节点本地 scratch，不在同步盘和高延迟共享目录中运行。

## 4. 输出与 pCRE 契约

BED 统一为 0-based、右端不含；GFF3 为 1-based、两端包含。反向链仍按参考正向坐标记录。嵌套片段和重叠命中保留在来源表；掩码另外计算区间并集。

- `te.mask.bed`：已分类 TE 的同源命中并集。
- `repeat_unknown.bed`：Unknown／尚未映射分类的重复，单列。
- `non_te.bed`：RNA、卫星等非 TE 分类命中。
- `repeat.mask.bed`：本版预定义为 **已分类 TE + TRF + dust** 的并集，Unknown 不在其中。
- `edta_native/intact.gff3`：EDTA 结构层；不是由同源片段重构的完整插入事件。
- `te_fragments.gff3`：保留 RepeatMasker 所有分类的片段；分类与来源必须一起解释，文件名不代表所有行均已确认为 TE。

softmask 使用 `repeat.mask.bed`；只输出选择的核序列。Unknown、非 TE 和 EDTA 原生结构结果都保留，便于下一阶段预先规定更宽的敏感性掩码。不得临时按 pCRE 预测效果增删区域。

家族库先获得稳定的 E/T 前缀 ID，来源表追踪原始 FASTA ID 和序列散列；精修 parent_map 接到 E 库，再接到原始 EDTA 家族。这是上游输出 lineage，不是家族生物学边界的新判定。总家族数、命中家族数、片段数、完整结构数和区间数不能混称 TE 拷贝数。

## 5. 状态、断点和失败

`complete.json` 表示该阶段产物满足软件契约；最终 `manifest.json` 为 `computed_awaiting_review`，不自动标成生物学验证完成。首次运行写 `run_manifest.json`，锁定配置、输入、数据库、代码与安装元数据。重新启动会复查散列，包括完成阶段的输出。

正常完成后重复运行不重复计算。失败目录不删除；`failed.json`、命令数组、日志、请求指纹与上游目录保留。检查原因后可使用 `--resume`；只允许同一指纹。EDTA 使用 `--overwrite 0`；TEtrimmer 已有 summary 时使用 `--continue_analysis`。不保证所有上游中间损坏都可安全恢复，遇到结构不完整应使用新 run_id 重跑。准备阶段中断也使用新 run_id。

`.lock/owner.json` 记录进程和主机。若节点被强制终止留下锁，先确认无对应进程，再人工移走该阶段的 `.lock`；不要自动清理活动锁。版本、输入或数据库变化后不可强行复用旧中间文件。

## 6. 先评价什么

服务器首批结果检查：输入范围是否正确；原始／精修家族数与未接受原因；分类型覆盖；原生结构与回贴关系；低复杂度／TRF 占比；CDS 重叠异常；反向链和相邻／嵌套例子的人工审查；峰值资源与耗时。

本版已经自动输出基本数量、覆盖并集、两库 TE 覆盖交并比和 CDS 重叠 bp。独立 TE 真值 precision/recall、系统边界误差、完整结构级关系、全家族域证据和人工抽样页面仍需要后续评价，未伪装成已实现。仅凭交并比、覆盖增加或 pCRE 变好，不选择胜出分支。

通过拟南芥 pilot 和衣藻运行后，再判断是否纳入 HELIANO、HiTE 或特定类型补充。尚不计算跨物种统一的 TE 插入年代，也不使用默认水稻突变率解释衣藻年代。
