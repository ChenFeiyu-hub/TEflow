# dev2 修订说明与服务器重试命令

版本：0.5.0.dev2；日期：2026-10-17。dev1 包和失败记录保留。本次不重装环境，不重跑 TE 分析，也不需要再次启用已经为 yes 的 linger。

## 对本次反馈的判断

1. 源码清单通过，说明解压和对应源码校验正常。B2 返回 fail 不能算验收通过。通过的三项是 SIGKILL、超时和取消；四个需要实际分配内存的项目失败。
2. `Linger=yes` 是有效反馈。dev1 查询用了 `--property=Linger,Sessions`；目标 loginctl 把它当成一个属性名，返回 0 但输出为空，脚本又把未知状态误判成需要启用 linger。这是代码缺陷。[systemd v252 文档](https://github.com/systemd/systemd/blob/v252/man/loginctl.xml) 要求多属性重复使用 `-p`。
3. `logout-start` 已明确返回 `launched:false`，所以没有启动心跳，也没有实际 attempt 可供重新登录后检查。`logout.替换为实际编号` 只是旧说明的示例文本；现在改为成功启动后保存身份文件，避免手填编号。
4. B2 的空异常文字与低内存峰值，高度符合固定 `RLIMIT_AS=256 MiB` 提前触发 Python `MemoryError` 的路径。它限制虚拟地址空间，不是实际驻留内存；旧日志缺少类型/VmSize，不能仅凭空字符串将服务器原因定为已证实。新版本补充异常类型、堆栈、VmSize/VmRSS 和限制值，等待服务器复核。[Python resource 文档](https://docs.python.org/3/library/resource.html)

本地已构造大虚拟地址基线：旧绝对上限使 32 MiB 分配失败，新增量上限可以完成分配。128 MiB cgroup 实际内存上限保持不变；另外加入相同大虚拟地址背景下的真实 OOM 对照。

## 1. 上传并执行 B2

把 `TEflow-0.5.0.dev2-source.zip` 和 `.sha256` 上传到 `/home/cfy/te_project/uploads/`，然后完整执行以下块。括号让失败只结束本命令块，不会退出你的 SSH shell。

```bash
(
set -e
TASK_ROOT=/home/cfy/te_project
TE_ENV="$TASK_ROOT/envs"
MICROMAMBA=/home/cfy/minimamba/bin/micromamba
UPLOAD="$TASK_ROOT/uploads"
RUNTIME_REPO="$TASK_ROOT/TEflow-0.5.0.dev2"

cd "$UPLOAD"
sha256sum -c TEflow-0.5.0.dev2-source.zip.sha256
if [[ ! -e "$RUNTIME_REPO" ]]; then
  "$MICROMAMBA" run -p "$TE_ENV/engine" python -m zipfile -e \
    "$UPLOAD/TEflow-0.5.0.dev2-source.zip" "$TASK_ROOT"
fi
cd "$RUNTIME_REPO"
"$MICROMAMBA" run -p "$TE_ENV/engine" python scripts/release_manifest.py
"$MICROMAMBA" run -p "$TE_ENV/engine" python scripts/runtime_acceptance.py login-status
"$MICROMAMBA" run -p "$TE_ENV/engine" python scripts/runtime_acceptance.py b2 --root "$TASK_ROOT"
)
```

已存在的 dev2 目录只验证，不覆盖；若源码校验失败，先报告。正常应看到 `LOGIN_STATE_READ`，`linger: "yes"`，并显示实际 session 数。B2 现在为 **9 项**：原 7 项，加上大虚拟地址基线下的正常/OOM 对照。它们仍逐项使用一个允许 CPU、128 MiB 内存和 0 swap。384 MiB 测试映射不可访问、不触碰，并非额外实际分配 384 MiB 内存。

只有返回 `B2_ACCEPTANCE_PASSED` 才继续 B3。若失败，先回传末尾指定的 `.feedback.tar.gz` 与 `.sha256`；新的错误诊断也会显示在终端。不要自行放宽内存限制来换取通过。

## 2. B2 通过后启动 B3，自动保存真实身份

```bash
(
set -e
TASK_ROOT=/home/cfy/te_project
MICROMAMBA=/home/cfy/minimamba/bin/micromamba
"$MICROMAMBA" run -p "$TASK_ROOT/envs/engine" python \
  "$TASK_ROOT/TEflow-0.5.0.dev2/scripts/runtime_acceptance.py" logout-start \
  --root "$TASK_ROOT" --duration 600 \
  --attempt-file "$TASK_ROOT/runtime_acceptance/logout-dev2.json"
)
```

**必须看到 `LOGOUT_HEARTBEAT_STARTED`，且 `attempt_file` 指向上面的真实文件，才开始退出登录。** `NEEDS_LINGER`、`LOGIN_STATE_UNAVAILABLE`、`LOGOUT_START_FAILED` 都不表示启动成功。已有身份文件不会覆盖；如果重复执行提示已存在，先用下一节检查或取消原测试，再为新的测试使用另一个明确文件名。

你之前有 4 个 session（212、211、185、69）。关闭一个终端通常不足以完成完整登出。安排正常退出该账户的全部 SSH/登录会话，保持至少 90 秒，再在启动后 10 分钟内登录。软件不替你结束会话，也不要求终止其他项目的进程；如果不能正常退出全部会话，就暂时保留 B3 未验证状态。

## 3. 重新登录后检查，无需填写 attempt 编号

```bash
(
set -e
TASK_ROOT=/home/cfy/te_project
MICROMAMBA=/home/cfy/minimamba/bin/micromamba
"$MICROMAMBA" run -p "$TASK_ROOT/envs/engine" python \
  "$TASK_ROOT/TEflow-0.5.0.dev2/scripts/runtime_acceptance.py" logout-check \
  --attempt-file "$TASK_ROOT/runtime_acceptance/logout-dev2.json"
)
```

通过时为 `B3_LOGOUT_SURVIVAL_PASSED`，并清理本次服务。`B3_NOT_PROVEN` 表示证据不足，例如仍有会话、零会话时间不足或心跳已经结束；不应强行改成通过。回传末尾反馈包即可。

如需主动结束本次心跳，在同一条 `logout-check` 命令末尾加 `--cancel`。脚本只操作身份核验一致的本次服务。即使没有检查，心跳进程也仅运行设定的 600 秒，之后可用该命令清理保留的服务记录。

## 4. 本版本的验证范围

这里只修复运行层测试与操作接口。多物种/多库资源账本、生产后端接入、数天运行及主机重启恢复仍未完成。实际服务器 B2/B3 结果必须回传后判断；本地成功不能替代服务器验收。GitHub 尚未推送正式发布。
