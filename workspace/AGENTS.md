# DeepSeek 工作区入口

工作根目录：`/home/ives/桌面/NXP_ds_v1/workspace`。
支撑根目录：`../support_level/`。

先遵守上一级 `AGENTS.md`，再按当前问题进入对应资源。

## 资源与状态

资源位置和能力边界见 `../support_level/ASSET_STATUS.md`；具体任务进展以当前
case 的状态和证据为准。历史验证不能代替本次执行前的核对。

## 技能入口

NXP 工程任务先读 `.agents/skills/understanding/SKILL.md`，随后按当前问题按需加载：

| 技能 | 入口 | 用途 |
| --- | --- | --- |
| understanding | `.agents/skills/understanding/SKILL.md` | 证据边界、问题拆解和路由 |
| support | `.agents/skills/support/SKILL.md` | 找资料、源码、工具和 case |
| compile | `.agents/skills/compile/SKILL.md` | 编译对象、依赖和受控构建 |
| board-exec | `.agents/skills/board-exec/SKILL.md` | 板状态、烧写、串口和验证 |
| build-customer-release | `.agents/skills/build-customer-release/SKILL.md` | 按用户要求生成客户交付包 |

路径相对本 workspace。加载技能时完整读取 SKILL.md，只按当前任务读取其引用资料。
如果 Harness 的技能目录尚未接入，可按本表直接读取；不得把未加载的技能声明为已应用。
根目录 `.agents/skills` 指向这里，供以 NXP_ds_v1 为 Git 项目根的 Harness 发现。
技能本体均为独立文件；没有链接到原 Codex 的 skills。

## 工作方式

1. 明确目标、成功判据和当前最先未解决的问题；只查询会影响本步骤决定的资料，
   遍历以本轮任务和已允许的读取范围为准。排除范围按实际遍历/读取路径执行，
   不用搜索词或输出过滤代替。排错中发现确实影响当前决定的新缺口，可在已允许
   范围内扩大并记录（完整盘点或 release/source 检索同样按任务范围进行）；
   超出读取授权则先说明缺口。证据足以回答本轮问题时，先交付已知/未知和下一步，
   不追求查完未来所有阶段。
2. 找资源先看 `../support_level/ASSET_STATUS.md` 和 `README.md`。
   若存在 RELATION.yaml，先核对 owner，再以对应 README/USAGE 解释具体操作。
3. 任务进入实施后，在 `../support_level/work/<日期-主题>/` 记录输入版本、
   命令、日志、修改、产物校验和、结论和下一步。继续任务先读已有 case。
4. 分清文档记载、源码证据、本次实际执行证据；工具成功返回不自动等于任务 PASS。
5. 共享源码只读；修改和编译在本环境 case 的独立源码副本中进行。
6. 新的可复用经验进入 `../support_level/to_absorb/`，注明来源 case，
   由后续审阅决定是否写进长期规则。

真实板级任务如果命中 `board-task` 板型与动作能力，按当前 case 的配置使用 MCP，
不临场拼接 sudo/BCU/UUU/串口命令。工具调用仍必须落到当前 case；模型要读回
原始证据并区分工具完成、阶段迁移、Linux-ready 和任务 PASS。

真实编译使用 `compile-tool` 的 prepare、展示命令、run 工作流；
先核对本次所需工具、资产路径和输出范围，不把某项目的成功推广到所有构建。
软件状态由工具生成，handoff 归编译阶段，ledger 归板级执行阶段。
纯资料查询不要求板级物理状态；真实板级执行必须先确认对象与当前状态。

## 独立推进与经验维护

根据用户目标、已有授权和当前证据选择步骤，在范围内自行分析、执行和恢复。
不要求教师在场、逐条给命令或每个阶段另开会话。需要新输入、重大方向决策或
超出已有授权时说明具体缺口；工具不支持某动作不等于板卡失败。

本题指定步骤、临时禁令和动态状态只留在 case。只有适用条件明确、可复用且
不会误伤相邻合法任务的经验才进入长期层；一次纠正不自动新增全局规则。
正常任务不要求教学标签或固定答题格式，保持事实、推断和未知可区分即可。
