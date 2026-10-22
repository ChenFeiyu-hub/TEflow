# v0.1.2：移除重复 BLAST 包，修复 Entrez Direct 冲突

## 这次日志说明什么

用户回传的 `tetrimmer.log` 已不再显示前一轮的 PfamScan/BioPerl 冲突，而是两套 BLAST Conda 包要求的 `entrez-direct` 版本范围没有交集。核对官方 Linux x86_64 包记录得到：

| 包与 build | Entrez Direct 要求 |
|---|---|
| `blast 2.17.0 h66d330f_0` | `>=24.0,<25.0a0` |
| `blast 2.17.0 hb02a186_1` | `>=26.0,<27.0a0` |
| `rmblast 2.17.0 hbfc2172_0` / `hbfc2172_1` | `>=25.3,<26.0a0` |

因此不能靠手工指定某一个 Entrez Direct 版本满足这组要求。改 channel 优先级也不是此次修复措施。

## 最小修复

从 `envs/tetrimmer.yml` 和 `envs/masking.yml` 删除重复的：

```yaml
- blast=2.17.0
```

保留 `rmblast=2.17.0`。它已经提供需要的标准 BLAST 命令和 dustmasker。其余工具版本、PfamScan 修订及算法参数不变。`envs/edta.yml` 本身没有这条重复要求，此次不改 EDTA 配方。

依据不仅是工具名称：[RMBlast 官方 Bioconda 配方](https://raw.githubusercontent.com/bioconda/bioconda-recipes/master/recipes/rmblast/meta.yaml) 明确测试标准 BLAST 程序；本次还通过 HTTP 字节范围读取真实发布包 `rmblast-2.17.0-hbfc2172_1.conda` 的 info 清单，确认包含：

```text
bin/rmblastn
bin/blastn
bin/blastp
bin/blastx
bin/tblastn
bin/makeblastdb
bin/blastdbcmd
bin/dustmasker
```

此次包审计读取了 66,554 字节元数据，没有下载 159 MB 的完整二进制包，也没有执行其中的程序。与独立 BLAST 包混装还会产生同名程序/库文件覆盖风险，因此采用单一程序提供方。

## 服务器立即重试

可直接做以下最小修改，不必为了验证这两行调整先重新传输整个仓库。备份放在源码目录外，避免混入工作流的源码指纹。

```bash
TASK_ROOT=/home/cfy/te_project
TE_REPO="$TASK_ROOT/te-annotation-workflow"
TE_ENV="$TASK_ROOT/envs"
export MICROMAMBA=/home/cfy/minimamba/bin/micromamba
cd "$TE_REPO"

TE_BACKUP=$(mktemp -d "$TASK_ROOT/blast-recipe-backup.XXXXXX")
cp envs/tetrimmer.yml envs/masking.yml "$TE_BACKUP/"
sed -i '/^[[:space:]]*-[[:space:]]*blast=2\.17\.0[[:space:]]*$/d' \
  envs/tetrimmer.yml envs/masking.yml

bash scripts/bootstrap_server.sh "$TE_ENV" --solve-only --only tetrimmer
bash scripts/bootstrap_server.sh "$TE_ENV" --solve-only --only masking
```

也可以更新到完整 v0.1.2 源码包（包含同样的两个 YAML 修复及安装后 BLAST CLI 检查），再执行这两个 `--solve-only` 命令。无需改变服务器路径、清空缓存或删除环境。

两项通过后再执行全环境 `--solve-only`。当前尚未正式安装任何环境时，全环境求解通过后可执行不带 `--solve-only` 的安装命令。已有实际环境时，按服务器手册分环境安装，不覆盖已存在环境。

## 本地实际验证

- **TEtrimmer 完整 Conda 运行依赖 dry-run 成功**：331 个包，包含 `rmblast=2.17.0=hbfc2172_1`、`entrez-direct=25.3=he881be0_0`、RepeatMasker 4.2.4、RepeatModeler 2.0.9、Perl 5.32.1、BioPerl core 1.7.8、Python 3.10；没有单独的 `blast` 包。
- **masking 完整 Conda 运行依赖 dry-run 成功**：96 个包，同样没有单独的 `blast` 包。
- **engine 的 Conda 部分 dry-run 成功**；不涵盖 YAML 中由 pip 安装的 Snakemake。
- 官方 RMBlast 包文件清单核查通过；Linux 15 项原有回归测试通过。
- EDTA 配方未改动。本地 EDTA 求解达到为本任务设置的 6 GiB 地址空间上限，分配失败而退出；这不是服务器安装错误，也不能据此判定 EDTA 配方不可解。保留其服务器求解验收步骤，没有提高本地资源限额。

完整求解摘要及关键包 build 见 [solver_summary_v0.1.2.json](validation/solver_summary_v0.1.2.json)。检查主机为本地 WSL Linux x86_64，Conda Forge 使用已有缓存，Bioconda 元数据在本次检查中补齐。为避免本地的分片下载延迟，仅对本地检查关闭了 sharded repodata；服务器不需要照做或更改全局 micromamba 配置。

这里的成功只表示 Conda 依赖可满足：尚未下载/安装这些完整环境，源码安装的真实 CLI 导入、数据库配置、分类探针和全基因组 EDTA 都仍须在服务器验收。TEtrimmer 源码安装器现会先检查同一环境中的 `blastn`、`makeblastdb`、`blastdbcmd`、`rmblastn` 版本命令，再检查 PfamScan 和 TEtrimmer CLI。
