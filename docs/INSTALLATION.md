> Historical/version-specific record. For a current installation start with [INSTALL](INSTALL.md); for an existing run see [UPGRADING](UPGRADING.md) and the [0.6 handoff](SERVER_v0.6_zh.md).

# 安装与执行顺序

> 0.2 新运行请使用 [版本交接文档](SERVER_HANDOFF_v0.2_zh.md)。以下保留四环境基线与数据库准备说明；本页旧 init-server 示例应加 `--profile baseline` 才只启用 E/ET。

生产环境为 Linux。Windows 可阅读代码、运行便携单元测试和核对数据，不在本地默认执行全基因组发现。服务器按实际分配填写 CPU、内存与工作盘。

## 1. 软件环境

先安装 micromamba，设置其绝对路径 `MICROMAMBA`，再运行：

```bash
export MICROMAMBA=/实际路径/micromamba
bash scripts/bootstrap_server.sh /srv/teflow/envs --solve-only
bash scripts/bootstrap_server.sh /srv/teflow/envs
```

四个环境分别用于调度、EDTA、TEtrimmer、统一回贴与轨道。主要工具版本见 `envs/*.yml`；实际解析 build 与安装日志另行保存。TEtrimmer/PfamScan 运行源码由 `install_tetrimmer_sources.py` 校验官方归档 SHA256 后安装，源代码不做算法修改。

## 2. 输入和配置

准备相互匹配的 FASTA 和 GFF3/GTF，记录物种、组装和注释版本。生成配置示例：

```bash
"$MICROMAMBA" run -p /srv/teflow/envs/engine teflow init-server \
  --root /srv/teflow --env-root /srv/teflow/envs --data-root /srv/teflow/inputs \
  --sample arabidopsis --threads 32 --mem-mb 131072 --run-id pilot_v01 \
  --micromamba "$MICROMAMBA" --output /srv/teflow/pilot.json
```

上述资源是填写示例，不是实际需求保证。检查配置内真实文件路径、器官基因组排除 ID、CDS 来源和所有工具前缀。

## 3. 数据库和预检

- Pfam：固定版本、HMM/dat 与 hmmpress 索引。辅助脚本为 `scripts/fetch_pfam.sh`。
- Dfam/FamDB：配置各 EDTA/TEtrimmer 环境实际使用的 RepeatClassifier 后端；首轮不要求下载全部未整理 HMM。
- 上游自带数据库：登记实际 EDTA、TEsorter 数据目录。
- TE-Aid：从已安装 RepeatMasker 的本地 RepeatPeps 蛋白库准备并实际检索测试。

```bash
"$MICROMAMBA" run -p /srv/teflow/envs/engine python scripts/prepare_teaid_database.py \
  --config /srv/teflow/pilot.json --output /srv/teflow/teaid_install_01
```

随后使用 `teflow lock-databases --help`，登记实际 Pfam、分类库、自带数据库与环境锁目录；TE-Aid 的运行资产会自动加入。数据库内容与源代码不能在已冻结运行中变更。

执行 `teflow validate-inputs` 和 `teflow doctor --dependencies`；详细参数见 CLI `--help`。doctor 包括索引与实际分类/蛋白检索探针，但不代替真实基因组验证。

## 4. 调度与结果

```bash
"$MICROMAMBA" run -p /srv/teflow/envs/engine \
  bash scripts/run_server.sh /srv/teflow/pilot.json --dry-run
"$MICROMAMBA" run -p /srv/teflow/envs/engine \
  bash scripts/run_server.sh /srv/teflow/pilot.json
```

启动器明确运行当前仓库源码。单节点 Slurm 入口见 `scripts/submit_slurm.sh`。普通 resume 只允许同一冻结指纹；不删除旧失败目录后声称是续跑。

工作记录在 `work/<run_id>/<sample>/`；正式导出在 `results/<run_id>/<sample>/`。`pack-feedback` 可收集轻量状态、日志和来源记录。输出语义、Unknown 策略和坐标定义见协议；测试证据见当前测试状态文档。

完整服务器详细手册存在于正式发布包；架构复核包仅保留本简明说明。各上游工具和数据库遵循其自身许可，本仓库的 MIT 许可不覆盖它们。
