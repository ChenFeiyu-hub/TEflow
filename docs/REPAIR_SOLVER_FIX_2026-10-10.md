# repair 第 54 行失败：冻结参数更正

后续 fix2：服务器求解已成功；如果随后报 `Unexpected package changes: python-tzdata`，按 [时区依赖白名单修正](REPAIR_TZDATA_FIX_2026-10-10.md)补充一行即可。当前开发脚本允许 pandas、pytz、python-tzdata 三者；本文其余内容保留首次修正的诊断记录。

反馈目录：`edta-pandas-20261010T092920Z-2740035`。脚本处于 `--solve-only`，`solve.json` 返回 `success: false` 和 `conflicting requests`。本次尝试未执行安装、未创建 v02 配置或工作流冻结清单，无需回滚环境。

根因是原修复脚本同时要求 `--freeze-installed` 与 `pandas=2.3.3`。前者为**每个**已安装包创建 Freeze 请求，包括原 pandas 3.0.6，因此阻止目标降级。这是修复脚本参数错误，不推翻此前的 pandas 3 / TIR-Learner 3 索引兼容性诊断。[上游实现](https://github.com/mamba-org/mamba/blob/main/libmamba/src/api/install.cpp)

更正后的脚本从 EDTA 环境的 `conda-meta/*.json` 读取包名、版本和构建号，在本次日志目录生成 `keep-installed-except-pandas.txt`。该文件固定 pandas 以外的所有包；另行要求 pandas 2.3.3。原先的事务检查仍然保留，出现 pandas、pytz 之外的安装/卸载动作便停止。若求解失败，脚本还会把 JSON 错误打印到 `repair.log`，不再只有行号。

## 应用方法

只需将本次提供的 `repair_edta_pandas.fix1.sh` 上传至 `/home/cfy/te_project/`。不要直接在该位置运行它：脚本通过自身位置定位项目，应先替换项目的 `scripts/repair_edta_pandas.sh`。

```bash
TASK_ROOT=/home/cfy/te_project
TE_REPO="$TASK_ROOT/te-annotation-workflow-v0.1.3"
export MICROMAMBA=/home/cfy/minimamba/bin/micromamba

(
  set -euo pipefail
  test -f "$TASK_ROOT/repair_edta_pandas.fix1.sh"
  test -f "$TE_REPO/scripts/repair_edta_pandas.sh"
  cp -p "$TE_REPO/scripts/repair_edta_pandas.sh" \
    "$TASK_ROOT/repair_edta_pandas.before_fix1.$(date -u +%Y%m%dT%H%M%SZ).sh"
  cp "$TASK_ROOT/repair_edta_pandas.fix1.sh" \
    "$TE_REPO/scripts/repair_edta_pandas.sh"
  bash -n "$TE_REPO/scripts/repair_edta_pandas.sh"
  bash "$TE_REPO/scripts/repair_edta_pandas.sh" "$TASK_ROOT" --solve-only
  bash "$TE_REPO/scripts/repair_edta_pandas.sh" "$TASK_ROOT" --apply
)
```

整段代码任一步失败即停止。`--apply` 仍然只完成依赖修复、创建 v02 配置、数据库登记、输入检查及工作流 dry-run，不启动基因组计算。看到 `REPAIR AND DRY-RUN PASSED` 后，再按 [主修复说明](TIR_PANDAS_FIX_2026-10-10.md)启动 v02。

无需删除原失败日志目录或重新下载数据库，也无需覆盖整个旧项目。首次 v0.1.3 压缩包保持原样留档；本次单文件修正已经同步到当前开发目录和源码散列清单。

若再次在求解阶段失败，回传最新的 `repair.log`、`solve.json` 和 `keep-installed-except-pandas.txt`。这三个文件可区分目标冻结冲突、确实需要变更的其他依赖，以及包构建可用性问题。

## 验证

- 使用真实 micromamba 和离线的微型包元数据复现：冻结全部已安装包时降级失败；固定其余包时求解成功，LINK 计划只包含 pandas 2.3.3。
- 两次真实求解均为 dry-run；模拟环境的已安装元数据保持不变。
- Linux 测试 20 项全部通过，包括只求解不安装、原配置/锁文件保留、其他包变更被阻断。
- 此验证证明修正了求解请求中的矛盾，不等同于已在服务器完整依赖图上求解成功。服务器安装与基因组分析仍以新的执行日志验收。
