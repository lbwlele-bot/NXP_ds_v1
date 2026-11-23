# DeepSeek Harness

本环境安装：`@deepseek-ai/dsh 0.2.1-rc.5`，专用 Node `24.22.2`。
运行时在本目录 `runtime/`；没有替换系统 Node，也没有安装全局 npm 包。
依赖版本由 `runtime/app/package-lock.json` 锁定。

## 日常打开

```bash
cd /home/ives/桌面/NXP_ds_v1/workspace
./dsh web
```

命令会在终端前台运行并打开带本地认证 token 的浏览器地址。结束时 Ctrl+C。
默认只监听本机；不要分享启动地址中的临时 token。
启动器固定工作目录为 workspace，并指定独立的 DSH_HOME 和 DSH_AGENTS_HOME。
本目录的 `dsh` 则保留调用者 cwd，供将来指定练习副本使用。

## Codex 只读调用

```bash
cd /home/ives/桌面/NXP_ds_v1/workspace
timeout --signal=TERM 240 ./dsh --profile headless \
  --patch ../support_level/tools/deepseek-harness/readonly.patch.yml \
  --json '这里填写范围明确的只读任务'
```

stdin 任务用 `--json -`，从任务文件重定向输入。JSON 事件输出应保存到当前 case。
续接同一对话时增加 `--session-id <上次 session 事件中的 sessionId>`。
必须重复指定只读 patch；它把沙箱设为 read-only，并拒绝需要人工审批的请求。
读权限仍不能当成秘密隔离，教学只提供用户授权的资料。

教师需要让全新会话修改 DeepSeek 本地工作区、但课程不包含真实编译时，使用
`supervised-workspace.patch.yml`；真实编译课程才使用
`supervised-compile.patch.yml`。Codex 的 `deepseek-teacher` 新会话运行器默认直接
调用基础 Harness，不注入 board-task MCP；只有明确的真实板级课程才增加
`--board-mcp`。

此发行版的 headless 没有 `--permission-mode` / `--approval-policy` 参数，
也不能把 `--patch` 放在最前面后再依靠位置参数解析 profile。
使用上述实测的 `--profile headless --patch ...` 写法。

本机 0.2.1-rc.5 已观察到：续接 readonly 会话时，仅更换命令行 patch 仍可能
保留旧会话的只读权限。需要切换权限时用对应 patch 新开会话，并核对实际工具
结果；不要通过轮换编辑手段绕过权限拒绝。这是运行时版本行为，不是教学流程要求。

Codex `deepseek-teacher/scripts/run_fresh_lesson.py` 当前使用缓冲输出，JSONL
在子进程退出或超时后落盘；中途无增量日志不代表没有执行。需要实时观察时应使用
经验证的流式运行方式。运行器中断也不自动证明外部执行已停止，恢复前须按相应
工具契约核对。命令行 patch 不会自动约束另一个 MCP 服务开放的能力。

完成判断必须同时检查进程退出码、`turn_end.reason.kind=completed` 和最终任务结果。
本版 final 事件只有 text，没有新版文档中的 final.reason，不能照搬 master 的解析器。

## 冷启动能力回归

同一 `session-id` 内改对只算本轮修订，不算持久化能力。针对编译证据边界的
冷启动回归位于：

```text
evals/compile-evidence-cold-start.md
evals/run_compile_evidence_cold_start.py
```

运行器故意不传 `--session-id`，从 workspace 启动全新 headless 会话，要求模型
重新发现入口规则和 skills，并对一个同类但非 case 原文照抄的问题给出结构化判断。
结果必须同时通过 Harness 完成状态和语义字段检查。

```bash
mkdir -p ../support_level/work/<eval-case>/logs
python3 ../support_level/tools/deepseek-harness/evals/run_compile_evidence_cold_start.py \
  --output ../support_level/work/<eval-case>/logs/compile-evidence-cold-start.jsonl
```

输出文件必须是新的明确 case 路径；运行器默认拒绝覆盖。该回归只验证规则发现和
工程判断，不证明真实构建、SD 写入或板级运行。

## 凭据

凭据：`../../runtime/deepseek-harness/.env`，权限 600，父目录权限 700，Git 忽略。
首次密钥已从用户指定 U 盘文件导入；不删除或修改 U 盘原文件。

更换密钥在自己的终端执行：

```bash
/home/ives/桌面/NXP_ds_v1/support_level/tools/deepseek-harness/configure-api-key
```

也可传 `--from-file <单行密钥文件>`。输入不回显，密钥不会写进命令行。
headless 使用启动环境/本环境 .env；Web UI 保存的凭据不一定适用于 headless。
如果已有 Web 进程，更换密钥后重新启动。

启动器对本次进程移除 NODE_TLS_REJECT_UNAUTHORIZED 和 NODE_OPTIONS，
使用正常 TLS 校验；不会修改主机 shell 配置。

## 已完成的验证

- CLI 版本和帮助。
- Web 本机启动、认证跳转和 HTML 返回 200。
- 原生 PTY 运行简单 Bash 命令、Koffi 调用 libc getpid。
- 安装版 FileSystemSkillProvider 发现并读取全部五个本地技能，无警告。
- 真实 API 回答 DSH_SMOKE_OK。
- 第一课实际调用 skill 工具读取 understanding/support，并读取本环境入口规则。
- 同一 session-id 续接成功，能接收教师反馈并修订先前结论。
- 默认 dsh 自动加载 `board-task` MCP；全新 headless 会话已独立完成 BCU、UUU、
  串口和 U-Boot 存储探测，并正确判断未 Linux-up。

以上为各原版本的历史验证，不自动覆盖后续工具重构。当前 board-task 的配置、
支持范围、离线/实机验证边界以 `../board-task/USAGE.md` 为准。

安装时 npm 11 默认没有放行 5 个依赖的安装脚本。上述原生测试均通过，
没有额外放开脚本，也没有从源码编译原生模块。
这些验证不覆盖所有插件、SDK、真实工程编译或板级执行。

记录：`../../work/2026-11-02-deepseek-harness-install/`。
官方入口：https://github.com/deepseek-ai/deepseek-harness

## 第一堂板级工具课

记录：`../../work/2026-11-02-imx943-board-tools-lesson/README.md`。
模型实际加载 board-exec 并通过固定 MCP 调用 BCU、UUU、serial-console。
shell 仍使用 read-only patch；主机硬件动作由固定命令白名单桥接器执行。
早期 lesson MCP 按用户授权逐步开放 reset；收敛版本位于
`../board-task/`，由 `workspace/dsh` 对 web/headless/tui/acp 默认注入。
它仍只接受固定 `case_id + operation`，真实 reset 必须过 capture READY 屏障，
持久写入绑定目标、产物 hash、recipe 和完成 marker。
不要把这次受控实操描述成已取得任意 sudo/刷写权限，或模型权重经过训练。
学习记录保存在工作区，后续任务仍需读取规则、fresh probe 和当前授权。
