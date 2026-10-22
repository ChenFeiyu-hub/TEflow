# 五物种输入文件准备规范

日期：2026-10-23。适用对象：Chlamydomonas reinhardtii、Klebsormidium nitens、Marchantia polymorpha、Arabidopsis thaliana、Oryza sativa。

沿用各物种已经用于其他研究的参考版本即可。每个物种独立准备，最少提供基因组 FASTA；本轮完整测试推荐准备“基因组 + 同版本基因注释 + 同版本蛋白”。CDS 核酸文件可选。不要为凑齐文件而混合不同组装或品系。

本文件定义输入准备要求；多物种批量入口仍按 [1.1 开发计划](MULTISPECIES_PLAN_v1.1_zh.md)实施。模板不是 1.0 `--config` 文件。

## 1. 文件清单

| 文件 | 本轮建议 | 具体用途与格式 |
|---|---|---|
| 基因组 `genome.fa` / `.fasta` / `.fna` | **必需** | 原始未硬屏蔽的完整核基因组；FASTA，一条染色体/contig 一个唯一 ID |
| 基因注释 `genes.gff3` 或 `genes.gtf` | **强烈建议**，二选一 | 与上述 FASTA 完全匹配；含基因、转录本和 CDS/phase 信息，用于 CDS 提取、宿主审核和基因区重叠统计 |
| 蛋白 `proteins.fa` / `.faa` / `.pep.fa` | **建议一并提供** | 同一注释发布版的氨基酸序列；用于核对翻译及可选宿主蛋白参考；不是 EDTA 的 `--cds` 输入 |
| CDS `cds.fa` / `.fna` | **可选，有现成文件建议保留** | 剪接后的编码核酸，不含 UTR/内含子；完整注释可用于软件自行提取 CDS |
| 来源/版本记录 | **必需信息，格式简单即可** | 物种、品系、组装版本或 accession、注释版本、原文件名与来源；可填写 JSON 模板，未知项目暂记 null |
| assembly report / seqid 说明 | 有则提供 | 确认核染色体、叶绿体、线粒体、alternate/haplotype 和未定位 scaffold 的归属 |
| 已发表 TE 库或 TE 坐标 | 可选 | 独立参考对照；注明来源、组装、版本和是否被发现/分类工具用过，不替代基因注释 |

不需要为这一轮准备 RNA-seq FASTQ、表达矩阵、Mfuzz RData、ChIP-seq、DAP-seq 或 JASPAR。已有的共享工具、Pfam 和分类数据库也不必按五个物种各复制一份。

## 2. 基因组 FASTA

接受未压缩 FASTA，或保留原始 `.gz` 供准备阶段处理。压缩包/zip 本身不能直接作为运行配置中的 genome 路径。上游运行使用解压后的独立工作文件，原文件保持不变。

- 标头以 `>` 开始，第一段不含空白的字段作为 seqid；同一 FASTA 内不可重复。其他描述可以保留。
- DNA 序列允许 A/C/G/T/N 和正常 IUPAC 模糊碱基；不能是蛋白序列、序列比对文件、带 gap 的 alignment 或网页下载错误页。
- 优先原始 unmasked genome；softmasked 小写序列仍保留碱基，现有 prepare 会转大写并记录小写比例。已用 N 替换重复区域的 hardmasked 版本无法恢复被遮掉的序列，不适合作为本次 TE 发现输入。天然 gap 中的 N 与硬屏蔽不同，不要求删除所有 N。
- 保留完整核组装，包括有明确归属的未定位核 scaffold。不要提前按 TE 含量、长度或低复杂度删除序列。
- 可提供包含细胞器的原始整套 FASTA，由我们用精确 ID 制作排除清单。不要只改 FASTA 的 `chr` 前缀而不改 GFF3，也不要猜测排除编号。
- alternate/haplotig、额外 mating-type 或混合性染色体参考必须说明范围；一个组装里的额外性染色体不能被当成细胞器自动剔除。

命名文件为 `genome.fa` 只是方便管理，不要求改原文件名，也不要求改标头。

## 3. GFF3 / GTF

优先提供发布方原始、完整的 GFF3。如果已有完整 GTF，则直接提供；没有必要手工转换一份仅为统一后缀。

GFF3/GTF 均应为 Tab 分隔的九列。坐标使用 1-based、闭区间；第 1 列必须与 FASTA seqid 一致，末端不得越出对应序列长度。GFF3 中的 gene/mRNA/CDS 通过 `ID`/`Parent` 关联；GTF 通过 `gene_id`/`transcript_id` 关联。CDS 需要正确的正负链与 0/1/2 phase。多 isoform、同一 CDS 的多个 Parent 及官方功能属性应原样保留。

只含 gene 坐标的 GFF、只有 exon 而没有 CDS/phase 的简化文件、只含 TE 的 GFF3，不足以支持当前 CDS 提取流程。文件名带 `gene_exons` 并不必然缺少 CDS，需要检查实际第 3 列，不能仅凭文件名判断。

现有提取流程选每基因最长的**合格**转录本：读取注释的 CDS 片段和 stop_codon，要求完整、phase 一致、无内部终止等条件，并排除被注释明确标为 TE gene 的基因。不同物种注释完整程度会影响接受比例，应保留剔除原因和映射，不能为了得到相同接受比例强行修正序列。

## 4. 蛋白与 CDS

### 蛋白 FASTA

提供该注释版本的全套预测蛋白即可，保留全部 isoform，无需先选最长。FASTA 主 ID 需要唯一，保留发布方标头和描述。若蛋白 ID、转录本 ID、gene ID 不同，有官方 ID 对应表就一起提供。

蛋白是氨基酸序列，不是转录本核酸。X 和发布方标记的末端 `*` 保留供检查；内部 `*`、不完整模型和重复 ID 应报告，不要先无记录地删除或拼接。建议提供未做多序列比对的原始蛋白，不要提供 MAFFT 输出。

当前 1.0 的 `init --protein-qc` 从 CDS 派生宿主蛋白；它不会自动读取目录下的 `proteins.fa`。直接指定外部宿主蛋白需要在对应成员配置里设置 `qc.host_proteins`，且先核查是否包含 TE 编码蛋白。蛋白相似性是审核证据，不是自动删除某个 TE 的理由。

### CDS FASTA

CDS 是转录本方向、剪接后的编码 DNA。带 UTR 的全长 cDNA/mRNA 不是等价替代；蛋白序列也不能反推为 CDS 输入。提供原始完整 CDS 集合即可，不需自行选代表 isoform。

若同时提供 GFF3 和官方 CDS，先核对二者关系，再决定实际运行采用“从注释派生”还是“已审核的 CDS”。现有程序直接收到 `--cds` 时走 supplied 路线，并不再次执行注释派生时的最长转录本和显式 TE gene 排除，因此不能随手把未核查的全套 CDS 当成完全去污染的宿主集。

## 5. 每个物种需要说明的身份信息

| sample_id（建议） | 拉丁学名 | 需要记录的版本信息 |
|---|---|---|
| `creinhardtii` | Chlamydomonas reinhardtii | 品系/交配型、assembly 版本、annotation 版本；已有 v6.0 genome + v6.1 annotation 可是正常配对，不要求两个数字相同 |
| `knitens` | Klebsormidium nitens | 品系、组装编号/版本；历史文件可能用 K. flaccidum 命名，保留原名并记录对应关系 |
| `mpolymorpha` | Marchantia polymorpha | Tak-1/Tak-2/其他品系，或是否为组合 standard reference；注明性染色体范围 |
| `athaliana` | Arabidopsis thaliana | 组装和注释版本；本轮优先沿用原已验收参考，便于回归比较 |
| `osativa` | Oryza sativa | 品种/亚种、组装版本和注释来源，避免把不同品种或不同 release 的 FASTA/GFF/蛋白混用 |

“同版本”是指文件属于同一发布方明确对应的组装和注释组合，不要求所有文件的版本字符串逐字相同。

这些身份注意点可由官方记录核对：衣藻 CC-4532 的 [v6 发布说明](https://www.chlamycollection.org/version-6-of-the-chlamydomonas-reference-genome-is-released/)，K. nitens NIES-2285 的[项目命名记录](https://www.ncbi.nlm.nih.gov/bioproject/248948)，地钱的[参考组成说明](https://marchantia.info/about_genome/)。这些链接用于解释已用文件，不要求本轮重新下载参考。

## 6. 推荐交付目录

```text
five_species_inputs/
  inputs.template.json              # 复制后填写；名称可改为 inputs.json
  inputs/
    creinhardtii/
      genome.fa
      genes.gff3                    # 或 genes.gtf，二选一
      proteins.fa
      cds.fa                        # 可选
      assembly_report.txt           # 可选
      source_readme.txt             # 可选的原始来源说明
    knitens/
    mpolymorpha/
    athaliana/
    osativa/
```

后四个物种与第一个采用同样结构。可以直接保留各自原始文件名，只需把 [JSON 模板](../examples/multispecies/inputs.template.json) 中的路径改成实际路径。没有的可选文件写 null，不要为了填满模板创建空文件。

`exclude_seqids` 可暂留空；`sequence_scope_reviewed` 保持 false，待核对细胞器/alternate 范围后再确认。空列表本身不表示已经审查过组装范围。

本地可放在已有大磁盘工作区下面的 `five_species_inputs/`，服务器使用同构目录。相对路径以清单所在目录为基准，便于整体迁移；正式上游工具工作路径避免空格、中文和 shell 特殊字符。无需重新上传已有且版本匹配的数据，也不增加源码或上传包的人工 SHA-256 验证步骤。

## 7. 收到数据后的检查与回传

预检将报告 FASTA 真实格式、重复 ID、总长度、GC、N/模糊碱基/小写比例、seqid 与坐标匹配、CDS 派生可用性、蛋白/CDS/gene ID 对应、明确 TE gene 标记、纳入/排除序列及可用的来源信息。

文件大小和名称相似不能证明版本一致；若 annotation 版本来源不明或蛋白无法映射，应在开始耗时发现前说明。预检保留所有物种的错误和警告，不因为第一个出错就停止生成其余成员的报告。

先通过输入和少量依赖检查，再进入全基因组 E 基线与多物种资源试跑。每一阶段的运行完成、资源优化效果和生物学正确性分别记录。
