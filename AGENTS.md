# NXP_ds_v1 全局边界

默认中文。这里是 DeepSeek 的独立工作环境；操作入口见 `workspace/AGENTS.md`。

本根目录的规则同样适用于 `support_level/`。支撑层沿用的旧说明是参考基线，
其中的“已验证”“当前版本”“当前板子”描述原环境历史，不构成本环境的运行证据。
查资源先读 `support_level/ASSET_STATUS.md`，再读所属目录的 RELATION 和 README/USAGE。

`support_level/code_assets/` 下的软链接指向 Codex 共用资源。它们不是文件系统隔离：
不得在链接目标原地 checkout、reset、clean、west update、打补丁、构建或生成缓存。
需要变更时，在本环境 `support_level/work/<case>/` 建立独立副本，核对指定 ref 后再做。
独立 clone 优先不使用共享可写 Git 元数据；不能把共享源码当前 checkout 当成固定版本。
此共享资源限制不能由沿用的项目说明中“允许切版本”等历史规则放宽。

任务记录、产物和待吸收知识只落到本环境的 `support_level/work/` 与 `to_absorb/`。
原环境 case 按明确任务选择性读取；不得整批复制或向新模型发送客户材料、凭据和会话历史。
涉及第三方模型的数据范围应在教学任务中明确。

工具能力和适用范围见所属 USAGE；任务目标、产物及已有授权保存在当前 case，
不从某次教学记录推导其他任务权限。板级动作仍需 fresh probe、串口证据和具体范围。
物理板卡、串口和存储设备也是共享资源；接手前确认 Codex 或其他进程没有正在进行的
冲突测试，明确本轮控制者，避免两个环境并发复位、刷写或改变同一设备状态。
