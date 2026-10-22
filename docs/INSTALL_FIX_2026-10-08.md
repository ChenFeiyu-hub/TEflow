# TEtrimmer 环境求解失败：v0.1.1 修复与重试

## 结论

用户服务器日志显示 TEtrimmer 环境的依赖集合不可解。`TASK_ROOT=/home/cfy/te_project/`、`TE_REPO="$TASK_ROOT/te-annotation-workflow"`、`TE_ENV="$TASK_ROOT/envs"` 的布局正确；Linux 中这里出现双 `/` 不导致依赖求解错误。`TE_ENV` 是四个环境的父目录，具体环境是 `$TE_ENV/engine` 等。

`Resolving Environment Done` 不表示安装成功；最终的 `Could not solve for environment specs` 才是本次 TEtrimmer 求解结论。这也不是 Snakemake 任务 DAG 的 dry-run。

## 原因与调整

日志中的冲突链为：

```text
TEtrimmer 1.7.2 -> pfam_scan 1.6 -> perl-bioperl 总包
  -> perl-bio-samtools -> 历史 samtools / libzlib <1.3 约束

RepeatModeler 2.0.9 -> RMBlast >=2.17.0 -> libzlib >=1.3.2
```

Perl 版本分支也出现在诊断中，但不能只靠任意更换 Perl 或 channel 优先级解决整个依赖图。现有 EDTA 与 TEtrimmer 原本已经分环境；冲突发生在 TEtrimmer 自己的依赖闭包内部。当前 [PfamScan 配方](https://raw.githubusercontent.com/bioconda/bioconda-recipes/master/recipes/pfam_scan/meta.yaml) 使用完整 BioPerl 总包；[RepeatModeler 配方](https://raw.githubusercontent.com/bioconda/bioconda-recipes/master/recipes/repeatmodeler/meta.yaml) 则要求新版 RMBlast。

v0.1.1 保持分析工具版本不变，调整安装方式：

1. Conda 安装 TEtrimmer 的显式运行依赖，包括 `perl-bioperl-core=1.7.8`、Moose、IPC::Run 和 IO::String，不安装完整 `perl-bioperl` 总包。
2. 安装官方、未修改的 TEtrimmer 1.7.2 与 PfamScan 1.6 源码，校验与上游 Bioconda 配方一致的归档 SHA256；不使用 `pip --no-deps` 等方式绕过这两个工具的依赖求解。
3. 安装器检测 Perl 模块及 `pfam_scan.pl -h`、`TEtrimmer --version/--help`。这些小检查不运行真实基因组。
4. 工具的非 Conda 源文件和启动器加入文件级散列清单；单独保存 Conda 显式锁不足以完整恢复此环境，还需源码清单和安装器。

核心模块选择依据：官方 PfamScan 归档里的 `Bio::LocatableSeq`、`Bio::Seq::RichSeq` 属于 BioPerl core；另有 Moose 和 IPC::Run。PfamScan 不需要 BioPerl 总包中的 BAM/samtools 绑定。仍需服务器安装后的运行检查确认当前具体 build 组合。

不采用的快捷修补：全局 flexible 优先级、强制混装、不受控地降级 RMBlast/RepeatModeler、关闭 Pfam 功能。尤其降级分类后端还会牵动现有 FamDB 约定和 doctor 的版本检查。

## 使用您的实际路径重试

将 v0.1.1 源码更新到 `/home/cfy/te_project/te-annotation-workflow`。保留旧源码备份、已有日志、环境和输入数据；本修复包不包含或修改这些数据。

```bash
TASK_ROOT=/home/cfy/te_project
TE_REPO="$TASK_ROOT/te-annotation-workflow"
TE_ENV="$TASK_ROOT/envs"
export MICROMAMBA=/home/cfy/minimamba/bin/micromamba
cd "$TE_REPO"
test -x "$MICROMAMBA" || exit 1

# 先仅重试此前失败的环境；不会安装任何环境或执行基因组任务。
bash scripts/bootstrap_server.sh "$TE_ENV" --solve-only --only tetrimmer

# 上一步通过后，再检查全部四个环境。
bash scripts/bootstrap_server.sh "$TE_ENV" --solve-only
```

日志会打印到 `envs/install_logs/<UTC时间-PID>/`，同次请求每个环境各一份日志，不覆盖之前的失败证据。`--solve-only` 使用新的临时目标路径，避免把已存在环境当作待替换对象。

如果此前只做了 dry-run，没有安装出实际环境，所有求解通过后可执行：

```bash
bash scripts/bootstrap_server.sh "$TE_ENV"
```

如果 engine、edta 已经真正安装，只安装尚未存在的环境：

```bash
# 以下仅在对应环境尚未存在时执行。
bash scripts/bootstrap_server.sh "$TE_ENV" --only tetrimmer
bash scripts/bootstrap_server.sh "$TE_ENV" --only masking

# 如果 engine 里已有 v0.1.0，更新我们自己的封装并重新记录 pip 锁。
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m pip install --no-deps "$TE_REPO"
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m pip freeze --all > "$TE_ENV/locks/engine.pip.freeze.txt"
```

若某环境已经部分安装而脚本拒绝覆盖，保留它，使用新的环境父目录，例如 `TE_ENV="$TASK_ROOT/envs_v011"`，完整重建并在 `init-server --env-root` 指向新目录；不要删除全部环境。源码安装中途失败同样保留诊断目录，不自动清理或改写。

若还未冻结生产运行，可继续原来的配置/数据库步骤。若已冻结过配置或结果，升级封装后必须使用新 `run_id`。

## 服务器不能下载源码时

把以下文件放进 `$TE_ENV/source_cache/`，安装器会验证缓存再使用：

| 文件 | SHA256 |
|---|---|
| `TEtrimmer-1.7.2.tar.gz` | `da3cca890b86f8ae406b7cc8acbefb3d79be0f04f6fb57aee9a5d00990d20dc2` |
| `PfamScan.tar.gz` | `365c96bc150d5057349c3016d62667c58cb33afcfb6329457ae16ab5aae4f401` |

下载地址登记在 `envs/vendor-sources.json`。安装后的 Pfam HMM 数据库仍按原手册单独准备；PfamScan 源码不是 Pfam 数据库。

## 验证范围

本地已完成：官方两个归档的 SHA256 核对；PfamScan 模块依赖检查；TEtrimmer 运行目录、Python 导入依赖与官方 launcher 配方核对；Windows 14 项通过、1 项 Linux shell 测试跳过；Linux 全部 15 项通过；安装脚本 Bash 语法检查。安装源码约 0.6 MB 的 TEtrimmer 运行目录，保留上游许可，不安装其视频和示例基因组。

完整修订环境尚未在本地求解/安装通过。第一次离线检查发现缓存缺少 Bioconda 元数据；第二次在线检查在 150 秒、4.5 GiB 地址空间上限下未完成，已停止。两次都不能据此宣布修订配方成功，也没有产生新的完整工具环境。服务器上面的 solve-only 是下一项验收。

随后仍需依次完成：实际安装与源码 CLI 检查、数据库配置、`teflow doctor --dependencies`、工作流 dry-run，最后再运行 EDTA。此修复不声明真实基因组注释或生物学准确性验证已经通过。
