# repair fix2：允许 pandas 必需的 python-tzdata

依据：`edta-pandas-20261010T101054Z-2762137/solve.json` 与 `repair.log`。模式为 `--solve-only`，求解器返回 `success: true`；随后修复脚本的事务检查退出，因此尚未执行安装。

本次完整 LINK/UNLINK 计划：

| 包 | 动作 |
|---|---|
| pandas | 3.0.6 → 2.3.3，目标 build 为 py311hed34c8f_2 |
| pytz | 新增 2026.5，build pyh5ded981_0 |
| python-tzdata | 新增 2026.5，build pyh5ded981_0 |

其余 406 个既有包没有 LINK/UNLINK 动作。选定 pandas 包的 `depends` 明确包含 `python-tzdata >=2022.7` 和 `pytz >=2020.1`。上次只允许 pandas、pytz，漏掉 python-tzdata，导致成功的求解被检查误拦截。只需补齐这项依赖，保留其他包的限制。

## 服务器单行修正与继续执行

不需要上传新包。以下命令备份脚本，然后改白名单，再执行 `--apply`。`--apply` 内部会重新求解和核对事务，成功后才安装。

```bash
TASK_ROOT=/home/cfy/te_project
TE_REPO="$TASK_ROOT/te-annotation-workflow-v0.1.3"
export MICROMAMBA=/home/cfy/minimamba/bin/micromamba

(
  set -euo pipefail
  SCRIPT="$TE_REPO/scripts/repair_edta_pandas.sh"
  cp -p "$SCRIPT" \
    "$TASK_ROOT/repair_edta_pandas.before_fix2.$(date -u +%Y%m%dT%H%M%SZ).sh"
  sed -i "s/unexpected = changed - {'pandas', 'pytz'}/unexpected = changed - {'pandas', 'pytz', 'python-tzdata'}/" "$SCRIPT"
  grep -Fq "unexpected = changed - {'pandas', 'pytz', 'python-tzdata'}" "$SCRIPT"
  bash -n "$SCRIPT"
  bash "$SCRIPT" "$TASK_ROOT" --apply
)
```

任一步失败便停止。本阶段会完成环境修复、pandas 索引探针、v02 配置与数据库登记、9 项 doctor 检查及工作流 dry-run，不启动基因组分析。成功末尾为 `REPAIR AND DRY-RUN PASSED`，随后可按主修复说明启动 v02。仍然失败时回传本次新建的修复日志目录。

## 本地修正和验证

当前开发目录及单独交付脚本 `repair_edta_pandas.fix2.sh` 已同步此更正，旧 fix1 文件和原发布包保留。测试夹具从本次真实求解记录提取 LINK/UNLINK 的包名、版本、build 和依赖，去掉服务器路径；该计划通过事务检查。针对修复脚本的 3 项 Linux 回归测试及 Bash 语法检查通过，其他包意外变更仍被阻断。实际服务器安装和完整基因组运行尚待执行。
