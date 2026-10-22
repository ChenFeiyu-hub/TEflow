# 0.5.0.dev1 服务器运行层验收

**历史说明，已被 dev2 替代。** dev1 服务器反馈发现 loginctl 属性查询及测试虚拟地址限制问题；新操作请使用 [dev2 修订说明](RUNTIME_ACCEPTANCE_dev2_zh.md)，不要继续使用本文的占位路径。

本候选版首先完成此前未验证的故障行为。B2 是有严格上限的小型实验；B3 是退出全部登录会话后的持续运行实验。两者均不运行 EDTA、TEtrimmer、HELIANO、HiTE，不安装依赖，不修改既有分析配置、数据库或冻结目录。实际 TE 分析仍使用原来的版本与命令。

## 1. 解压候选版并验证源码

将 `TEflow-0.5.0.dev1-source.zip` 和同名 `.sha256` 上传到 `/home/cfy/te_project/uploads/`。若该目录不同，只调整 `UPLOAD`。

```bash
TASK_ROOT=/home/cfy/te_project
TE_ENV="$TASK_ROOT/envs"
MICROMAMBA=/home/cfy/minimamba/bin/micromamba
UPLOAD="$TASK_ROOT/uploads"
RUNTIME_REPO="$TASK_ROOT/TEflow-0.5.0.dev1"

cd "$UPLOAD"
sha256sum -c TEflow-0.5.0.dev1-source.zip.sha256 || exit 1
if [[ -e "$RUNTIME_REPO" ]]; then
  printf '%s\n' "目标目录已存在，请保留它，选择新的解压路径；不要覆盖正在验收的源码。"
  exit 1
fi
"$MICROMAMBA" run -p "$TE_ENV/engine" python -m zipfile -e \
  "$UPLOAD/TEflow-0.5.0.dev1-source.zip" "$TASK_ROOT" || exit 1
cd "$RUNTIME_REPO"
"$MICROMAMBA" run -p "$TE_ENV/engine" python scripts/release_manifest.py || exit 1
"$MICROMAMBA" run -p "$TE_ENV/engine" python scripts/runtime_acceptance.py --help
```

ZIP 顶层固定为 `TEflow-0.5.0.dev1/`。采用源码入口，不需要 `pip install`，不会把当前 engine 中的 TEflow 替换成开发版。不要针对本次 runtime 验收迁移已有 genome config。

## 2. B2：OOM、失败与清理

```bash
cd "$RUNTIME_REPO"
"$MICROMAMBA" run -p "$TE_ENV/engine" python scripts/runtime_acceptance.py b2 \
  --root "$TASK_ROOT"
```

通常几十秒内完成。总共七项，逐个执行；每个服务只允许一个当前可用 CPU、128 MiB 内存、0 swap，最长约 20 秒，额外有外部看守期限。OOM 子进程的分配本身也有明确有限上限。每次只测试本次唯一命名的用户服务，不会搜索或终止其他项目进程。

| 测试 | 期望判定 |
|---|---|
| 正常父子任务 | `SUCCEEDED` |
| 子进程 OOM，父进程故意返回 0 | `OOM_CONFIRMED` |
| 整组 OOM | `OOM_CONFIRMED` |
| 子进程自行 SIGKILL，没有 OOM | `CHILD_SIGNAL` |
| 超过服务时间限制 | `TIMEOUT` |
| 主动取消 | `CANCELLED` |
| 新解释器重连原任务，并拒绝错误身份/重复提交 | `SUCCEEDED` |

这些是预设实验结果，不代表工具出了新的异常。只有七项行为均符合预期且清理确认完成，摘要才是 `B2_ACCEPTANCE_PASSED`。如果状态是 fail，保留输出，不手动放宽上限或略过检查。

末尾会给出 `feedback` 的确切路径。回传该 `.feedback.tar.gz` 与旁边的 `.sha256`；体积很小，含控制器、父子进程、cgroup 采样和清理记录。不需要上传原始基因组或重跑 B1。若只完成 B2，可以先回传这一包。

## 3. B3：确认退出全部 SSH 后仍在运行

先读取用户设置：

```bash
loginctl show-user "$(id -un)" -p Linger -p Sessions
```

之前服务器反馈为 `Linger=no`。B3 启动脚本对此会返回 `NEEDS_LINGER`，不启动负载，也不会自行改变系统设置。需要管理员按服务器管理要求为该账户启用：

```bash
loginctl enable-linger cfy
loginctl show-user cfy -p Linger -p Sessions
```

如果当前账户没有权限，由管理员执行即可；无需在对话里提供密码或 token。不要使用 `terminate-user`、`kill-user` 或批量杀进程替代退出。linger 让用户管理器能够在退出登录后继续存在，但是否实际存活仍由下面的实验判断。[systemd 官方说明](https://github.com/systemd/systemd/blob/v252/man/loginctl.xml)

在正常 SSH 登录会话、B2 通过且 `Linger=yes` 后运行：

```bash
cd "$RUNTIME_REPO"
"$MICROMAMBA" run -p "$TE_ENV/engine" python scripts/runtime_acceptance.py logout-start \
  --root "$TASK_ROOT" --duration 600
```

保存输出中的 **attempt 完整路径**。确认出现 `LOGOUT_HEARTBEAT_STARTED` 后，正常退出该账户的全部 SSH/登录会话，保持至少 90 秒再登录，在启动后 10 分钟内进行下列检查。其他终端或远程开发连接也可能占着同一账户的 session；只退出一个窗口不能证明完整登出。请选择能正常退出所有会话的时间执行。

重新登录后变量需要重新赋值：

```bash
TASK_ROOT=/home/cfy/te_project
TE_ENV="$TASK_ROOT/envs"
MICROMAMBA=/home/cfy/minimamba/bin/micromamba
RUNTIME_REPO="$TASK_ROOT/TEflow-0.5.0.dev1"
ATTEMPT='/home/cfy/te_project/runtime_acceptance/logout.替换为实际编号'

"$MICROMAMBA" run -p "$TE_ENV/engine" python "$RUNTIME_REPO/scripts/runtime_acceptance.py" \
  logout-check --attempt "$ATTEMPT"
```

通过时返回 `B3_LOGOUT_SURVIVAL_PASSED`，自动清理本次服务并生成反馈包。`B3_NOT_PROVEN` 不是自动判定系统故障：可能仍有其他会话、零会话时间不足、采样不可读，或检查时心跳已经结束。报告会保留这些证据。没有足够证据但心跳仍在运行时，可以在本次期限内补做真实退出后再次检查；新检查不会重新提交任务。

如需取消这一次验收，使用确切 attempt：

```bash
"$MICROMAMBA" run -p "$TE_ENV/engine" python "$RUNTIME_REPO/scripts/runtime_acceptance.py" \
  logout-check --attempt "$ATTEMPT" --cancel
```

即使忘记检查，心跳进程也只运行预设的 600 秒；之后可用该命令清理保留的服务记录。B3 通过仅证明这次有界服务跨越了观测到的登出间隔，不等于数天的大基因组任务或主机重启恢复已验证。

## 4. 下一步范围

回传 B2/B3 后，再确认服务器后端的能力等级并接入多物种/多库共享资源账本、任务准入和失败恢复。当前 `teflow run` 不会因为安装本候选版就自动获得这些能力。[架构与后续验收门槛](RUNTIME_CONTRACT.md) 明确区分已实现、待服务器复核和待开发内容。

GitHub 远程 CI、服务器上的公开 CLI 合成流程、资源账本竞争/控制器崩溃、多物种并发，以及可选 R/RE 分支的真实基因组验证仍需分别记录。无需为了本次运行层验收重复已经完成的拟南芥分析。
