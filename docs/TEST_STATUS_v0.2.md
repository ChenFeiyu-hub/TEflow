# 0.2 验证记录

日期：2026-10-13。本版可以进入服务器分支验收；尚未完成拟南芥五路线全基因组比较，也尚未选择 pCRE 默认 mask。

## 本轮实际完成

| 检查 | 结果 | 声明范围 |
|---|---|---|
| Linux 单元/回归 | 48 项通过，无跳过 | 含真实离线 micromamba 事务约束、中断进程组、失效锁、版本/坐标/缓存/来源等 |
| Windows 单元/回归 | 40 项通过，8 项因平台或可选依赖跳过 | 不宣称 Windows 能运行生产发现工具 |
| schema 1 + 真实 Snakemake 9.27.0 | 通过 | 模拟上游的旧两分支兼容性 |
| schema 2 + 真实 Snakemake 9.27.0 | 七分支通过 | 五主分支与两参考分支均为模拟工具，非生物学 benchmark |
| 内容/恢复验证 | 通过 | EDTA/RM 导入、独立导出、>1 MB 文件 touch、marker 重建、输入/导出篡改拒绝、禁止导入旧 TT、目标预检 |
| HELIANO 1.3.1 Conda dry-run | 通过，169 包，约 590 MB | 未安装完整 HELIANO 环境；未运行真实 HELIANO 发现 |
| DIAMOND/HMMER QC Conda dry-run | 通过，19 包，约 38 MB | 配方可解；实际服务器仍需安装检查 |
| TRF + dustmasker 真实执行 | 通过，900 bp 合成序列 | 真实版本/参数/输出格式、区间和序列保持契约 |
| DIAMOND + HMMER 真实执行 | 通过，单条 250 aa 合成蛋白/玩具 HMM | 宿主/TE 蛋白阳性与域命中可正确解析，库未自动删除；不是实际 Pfam 的生物学检测 |
| HELIANO/HiTE 固定版本源码与接口 | 已核查 | 参数、1-based 取序列、共识边界扩展、HiTE 高置信库、退出/重试风险 |
| HiTE 3.3.3 镜像安装/完整执行 | 待服务器 | 本地未下载大型 SIF；官方 run 入口仍需实际服务器 doctor |

Linux 使用 Python 3.11.17；Windows 使用本地打包 Python。新增真实轻量环境装在 WSL `/tmp/teflow-v02-lightcheck`，没有改动用户已有 EDTA、TEtrimmer 或 masking 环境。实际轻量工具 build：DIAMOND `2.1.11 h5ca1c30_2`、HMMER `3.4 h7d74f8d_5`、TRF `4.10.0rc2 h7b50bb2_0`；TRF 横幅是 `4.10.0-rc.2`，不是声称稳定版 4.10.0。现有配方的 `trf=4.10.0` 是 Conda 前缀约束，实际解析到 rc2，必须保存服务器 explicit lock。dust 使用已有 BLAST+ 2.17.0 构建。原服务器版本不由这次本地验证替换。

新增 HELIANO 包 `heliano-1.3.1-py39r41_0.tar.bz2` 的公开散列已核对：`258d7a924583cdb7ea13df9dc913e24e35cf9deedde487ba4192ca85d9de52ce`。检查了包内路径替换和 HMM 入口；这不等于已证明 conda post-link 和所有算法依赖运行成功。求解期间出现过一次 channel shard TLS 重试提示，最终两次 dry-run 均成功，无安装事务发生。

机器可读记录见 `docs/validation/tests_v0.2.json`、`source_checks_v0.2.json`、`solver_summary_v0.2.json` 和对应轻量实测摘要。大日志不放进发布包。

## 七分支合成验收实际核对的行为

1. 同一科学输入、相同工具/预算下导入旧 E/RM，旧目录不变；拒绝 TT 导入。
2. 单独完成 E 的导出时，HiTE 尚未执行，总比较未伪造完成。
3. 原生 H 坐标转换回原始染色体 ID；嵌套屏蔽后重算序列散列；多来源关系保留。
4. MITE 纳入 TE，宿主蛋白/域 QC 执行状态准确；参考不假定完整独立。
5. 七分支全部产物、公共轨道、启动子机会数、分支差异和反馈包满足接口。
6. 物理大小 1,100,199 bytes、实际序列仅 180 bp 的 FASTA 在 touch 后不触发科学重算；可重建丢失调度指针。
7. 同尺寸输入内容改变、完成 mask 改变会在调度前拒绝；正式启动器的 target 预检有效。

## 已有服务器证据的继承边界

已有拟南芥 EDTA 与公共回贴可按哈希和兼容性校验尝试导入。先前 TEtrimmer 的 RepeatPeps/TE-Aid 错误输出不作为正常生物学结果；v03 已完成恢复准备与 dry-run 的反馈，不代表我们已经收到干净完整运行结果。0.2 没有为该旧结果“解除隔离”。

服务器顺序仍为安装/doctor → 验证 E 导入 → 干净 ET → H → HiTE → E+H → 描述性比较。只有这些实际输出、资源记录和科学差异得到审核后，才讨论默认路线。参考家族敏感度、插入边界准确率、跨植物物种表现和发表级质量结论仍需独立工作。
