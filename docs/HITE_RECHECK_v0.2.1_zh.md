# HiTE 验收失败复核与 0.2.1 接续

日期：2026-10-14。此文针对 `/home/cfy/te_project` 的 `at_compare_v02`。该运行的输入检查和 freeze 已执行，doctor 尝试 `a14522574db3469292facfc66f024122` 失败。保留旧配置、旧仓库、冻结文件及全部失败日志。

## 1. 已确认的情况

本次 doctor.json 共 16 项：14 项 pass，2 项 fail。EDTA、TEtrimmer、RepeatMasker、TRF、dustmasker、HELIANO、heliano_cons、DIAMOND，以及 EDTA 依赖、pandas 操作、TE-Aid 蛋白数据库、两个分类后端和 HELIANO 合成序列依赖操作均通过。它们无需重新安装。

第一项失败是 `Expected hite 3.3.3 not found in version output`。这表明本次 doctor 实际读取的配置仍要求 3.3.3；修改下载命令中的 grep 不会修改已有 JSON。0.2 的 migrate-config 默认会写入 3.3.3，且不会覆盖已经存在的配置。修复脚本会从旧配置克隆新配置，明确设置实际 CLI 版本。

已校验的官方镜像：

| 字段 | 值 |
|---|---|
| 发布来源 | https://zenodo.org/records/15734031 |
| 原始文件名 | hite_3.3.3.sif |
| 字节数 | 3674533888 |
| 官方 MD5 | c782a0befa8e8a422e5c45830e30d958 |
| 实测 SHA256 | 4776bd6a1c0d8797f0e1e5febe385b157fb36a5de0615b2b7f8818672de74e55 |
| 发布标签 / CLI 横幅 | 3.3.3 / 3.3.2 |
| 镜像内 main.py SHA256 | c740ed0695e521d7317c37220864de324a52711291e6f49d19656dd1baea49b9 |

仅比较了镜像内 main.py 与 Git 标签 v.3.3.3 的同名文件：除 version_num 外字节一致。没有据此声称镜像内全部源码、依赖或模型等同于该 Git 标签。后续用实际 SIF 散列锁定比较条件，不修改镜像内部的版本号。

第二项是 `hite_dependencies` 退出 2。上传的 doctor.json 只含日志路径，不能据此确定其最先触发的具体异常，仍需原始 `hite.dependencies.log`。独立核验发现 0.2 的确有错误：它查找小写 ninja，而镜像内实际存在、HiTE/module/Util.py 实际调用的生物信息聚类工具是大写 Ninja。不要安装 Ninja 构建系统来满足错误检查。0.2.1 修复此问题，并会把依赖异常文本写入 doctor.json 的 probe_error。

## 2. 部署新副本，仅执行一次

上传 `te-annotation-workflow-v0.2.1.tar.gz` 和 `SHA256SUMS-v0.2.1.txt` 到 `/home/cfy/te_project/releases/`。无需再次下载 SIF 或运行 bootstrap。

```bash
(
set -euo pipefail
TASK_ROOT=/home/cfy/te_project
TE_ENV="$TASK_ROOT/envs"
export MICROMAMBA=/home/cfy/minimamba/bin/micromamba

cd "$TASK_ROOT/releases"
grep 'te-annotation-workflow-v0.2.1.tar.gz$' SHA256SUMS-v0.2.1.txt | sha256sum -c -
test ! -e "$TASK_ROOT/te-annotation-workflow-v0.2.1"
tar -xzf te-annotation-workflow-v0.2.1.tar.gz -C "$TASK_ROOT"

TE_REPO="$TASK_ROOT/te-annotation-workflow-v0.2.1"
export TEFLOW_REPOSITORY="$TE_REPO"
export PYTHONPATH="$TE_REPO/src${PYTHONPATH:+:$PYTHONPATH}"
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow --version

"$MICROMAMBA" run -p "$TE_ENV/engine" python \
  "$TE_REPO/scripts/prepare_hite_recheck.py" \
  --config "$TASK_ROOT/at_compare_v02.local.json" \
  --output "$TASK_ROOT/at_compare_v021.local.json" \
  --run-id at_compare_v021 \
  --image "$TASK_ROOT/containers/hite-3.3.3.sif"
)
```

应显示软件版本 0.2.1，随后显示新配置路径和镜像身份。镜像校验需要读取约 3.67 GB；这不是重新下载。脚本保留全部原有分支参数、QC 和参考设置，仅修正 HiTE 身份、wrapper 路径和 run ID。若新目录/新配置已存在，停止检查它，不覆盖。

## 3. 先验收，再冻结

下面步骤可在新配置已创建后执行。doctor 失败会自动停止，尚未 freeze，便于根据具体日志修复；不要在失败后直接跳到正式分析。验收仅执行小型依赖操作。

```bash
(
set -euo pipefail
TASK_ROOT=/home/cfy/te_project
TE_ENV="$TASK_ROOT/envs"
TE_REPO="$TASK_ROOT/te-annotation-workflow-v0.2.1"
CONFIG="$TASK_ROOT/at_compare_v021.local.json"
export MICROMAMBA=/home/cfy/minimamba/bin/micromamba
export TEFLOW_REPOSITORY="$TE_REPO"
export PYTHONPATH="$TE_REPO/src${PYTHONPATH:+:$PYTHONPATH}"
cd "$TE_REPO"

"$MICROMAMBA" run -p "$TE_ENV/engine" python -u -m teflow plan --config "$CONFIG"
"$MICROMAMBA" run -p "$TE_ENV/engine" python -u -m teflow validate-inputs \
  --config "$CONFIG" --output "$TASK_ROOT/at_compare_v021.input_audit.json"
"$MICROMAMBA" run -p "$TE_ENV/engine" python -u -m teflow doctor \
  --config "$CONFIG" --dependencies --output "$TASK_ROOT/work/at_compare_v021/doctor"
"$MICROMAMBA" run -p "$TE_ENV/engine" python -u -m teflow freeze --config "$CONFIG"
echo 'DEPENDENCY ACCEPTANCE AND FREEZE PASSED. No genome analysis launched.'
)
```

HiTE version 检查应报告 expected_version=3.3.2，并包含 release_label=3.3.3 的 image_identity。HiTE dependencies 需要全部通过，不能只看 version 项。若失败，新 doctor.json 会尽可能列出 probe_error；回传失败尝试里的 doctor.json 和 hite.dependencies.log。其他 Python/共享库/挂载问题需要按该日志判断，不能预先宣布本补丁解决全部运行问题。

## 4. 验收通过后的接续

使用新的 CONFIG、TE_REPO。按 0.2 交接文档导入已有并完成校验的 EDTA 与 rm_edta；source-config 应指向真正拥有完整回执的 v03 或对应旧运行，而不是本次只做了 doctor 的 at_compare_v02。导入仍执行完整性及兼容性检查；不要手动修改散列绕过。之后执行 `run_server.sh "$CONFIG" --dry-run`。通过后再按 E → ET → H → HiTE → E+H 的顺序进行全基因组验收。

0.2.1 的源码指纹与 0.2 不同，旧 at_compare_v02 不作为恢复运行的目标。不要删除它的 run_manifest.json 以继续原 run ID。

## 5. 验证边界与证据

本地直接从同一 SIF 提取 Ninja 命令（SHA256 `f9d87a738aecd1dcd4fbf22bc76887e5e5f7d9133aa763ce92399c5a358dd7e8`），三个 160 bp 对齐序列、一个线程，官方调用参数返回 0，输出保留三个序列 ID。镜像源码中同样使用大写 `Ninja --in ... --out_type c --corr_type m`。

完整测试结果见本目录 validation/v0.2.1_checks.json。单元回归覆盖准确镜像识别、未知镜像拒绝、旧冻结文件保护、新 wrapper 绑定、实际版本溯源、Ninja 输出完整性和依赖错误透传。调度测试仍使用合成工具；未在本机运行完整真实 HiTE/HELIANO/TEtrimmer 基因组分析。本地完整 SIF 依赖执行未完成，最终以服务器新 doctor 回执为准。

官方参考：[HiTE v.3.3.3 源码](https://github.com/CSU-KangHu/HiTE/tree/v.3.3.3)、[发布镜像存档](https://zenodo.org/records/15734031)。镜像身份差异和 Ninja 大小写以对该 SIF 的实际只读检查为依据。
