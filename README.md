# NXP_ds_v1

独立轻量仓库：`https://github.com/lbwlele-bot/NXP_ds_v1`（私有）。
同步范围及恢复前提见 [GitHub 同步说明](GITHUB_SYNC.md)。本仓库不是整机备份；
下文“已安装/已配置”和 case 链接描述原本机环境，不代表 clone 后已具备运行条件。

DeepSeek Harness 的独立 NXP i.MX 工作环境。用户实际打开的工作目录是
`/home/ives/桌面/NXP_ds_v1/workspace`。

- `workspace/`：DeepSeek 的入口规则、后续技能与工作方式设计。
- `support_level/`：独立维护的说明、配置、轻量工具、case 和知识沉淀。
- `support_level/code_assets/`：项目说明属于本环境；最内层源码通过软链接复用 `NXP_v2`。

Harness 0.2.1-rc.5 已安装，API key 已在本机配置；五个工程技能的发现/读取、
Codex headless 调用已验证。部分构建及板级链路有历史 case 证据，
不表示所有工程能力已验收；工具修改后的验证范围见对应 USAGE 和修复记录。

打开方式：在 `workspace/` 运行 `./dsh web`。
使用说明：[DeepSeek Harness](support_level/tools/deepseek-harness/USAGE.md)。

入口：[workspace/AGENTS.md](workspace/AGENTS.md)。
后续设计：[workspace/docs/DESIGN.md](workspace/docs/DESIGN.md)。
资产状态：[support_level/ASSET_STATUS.md](support_level/ASSET_STATUS.md)。
来源记录：[初始化 case](support_level/work/2026-11-02-deepseek-workspace-bootstrap/README.md)。

规则和工具参考 `lbwlele-bot/nxp_ivesliu_skill` 已发布提交
`02c4fbf16ee80a5c1732a080facacc855a588231`，此后由本环境独立维护。
原 Codex workspace 的未提交改动未迁入。
