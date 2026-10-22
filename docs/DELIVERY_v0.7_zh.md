> Historical 0.7 preparation record. Target-server acceptance subsequently passed on 2026-10-22; see [current validation](TEST_STATUS_v1.0.md). Earlier pending statements below are dated, not current release status.

# TEflow 0.7.0rc1 交付说明

本轮已完成单物种发布候选版。重点是运行管理、资源观测和结果报告，算法、分支结构、合库规则与默认 mask 策略保持 0.6 的既有协议。

- 新增 `run-preview`、`cancel`、`logs`、`runtime-summary`、`report`。
- 启动器持续监督 Snakemake，保留调度日志及成功、失败、取消和清理未完成的最终状态；阶段完成与启动器完成分开表达。
- 取消只针对同主机上已验证的当前运行。外部任务清理自己启动的子进程；恢复必须显式使用相同源码及配置的 `--resume`。控制器崩溃后的自动接管不在本版范围。
- 每个外部命令启动后立即采样，前十秒每 250 ms 采样，之后沿用配置间隔，并记录子进程覆盖、采样数量和间隔。内存仍为观测模式。
- 报告区分 TEtrimmer 精修序列、回退原序列和低拷贝原序列；不自动选择“最佳库”。旧 0.6 数据可以只读汇总。

## 文件

- `TEflow-0.7.0rc1-source.zip`：服务器建议使用的独立源码包，含测试、工作流、环境配方与文档。
- `te_annotation_workflow-0.7.0rc1-py3-none-any.whl`：Python 安装包，不包含外部 TE 工具或数据库。
- `te_annotation_workflow-0.7.0rc1.tar.gz`：标准源码分发包。
- `SERVER_v0.7_zh.md`：本次服务器操作；只需完成第 1–3 节。
- `TEST_STATUS_v0.7.md`、`local_v0.7.0rc1.json`：实际本地验证与尚待完成的验收范围。

## 已完成的验证

Windows 165 项：141 通过、24 平台/环境跳过；Linux 安装版 165 项：164 通过、1 项环境跳过。八条源码调度回归通过；独立 wheel 的 CLI、取消恢复、多库并行通过；冻结源码中的服务器验收入口已在本地 Linux 通过。源码/sdist/wheel 的载荷进行了直接比较，未新增 SHA-256 上传步骤。

还验证了真实 0.6 反馈的报告兼容性，包括 23 个运行记录、5 个采样不足的 QC 记录和 TEtrimmer 的三类序列来源。反馈副本缺少完整服务器文件，所以本地报告不会把它误标为完整产物验收。

## 下一步

先上传源码 ZIP 并执行 `SERVER_v0.7_zh.md` 第 1–3 节，回传 RC 验收反馈包和旧 0.6 报告包。无需重装环境、重新下载数据库或再跑真实 EDTA。通过后再推进 GitHub 同步和实际 CI，检查作者元数据，然后决定 RC 标签与正式版。

本轮没有向 GitHub 推送、打标签或发布 PyPI。0.7 的目标服务器验收与远程 CI 仍待执行；多物种调度、生产硬内存限制和严格 B3/logout 证明没有被提前标为完成。旧 0.6 包和旧运行继续保留。
