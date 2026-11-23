# DeepSeek workspace 设计起点

## 已确定的结构

```text
NXP_ds_v1/
  AGENTS.md                 整个环境的共享资源和证据边界
  README.md
  workspace/                DeepSeek Harness 实际工作目录
    AGENTS.md
    .agents/skills/          五个独立工程技能及参考/模板/脚本
    docs/DESIGN.md
  support_level/
    ASSET_STATUS.md
    code_assets/            独立说明 + 最内层源码软链接
    compile_targets/        独立编译对象说明和配置
    software_stacks/        独立软件栈说明
    board_knowledge/        继承的历史参考，待本环境验证
    tools/                  独立轻量工具和说明
    Image/ SoC_material/ linux_document/
    release_packages/ toolchain/ firmware/
    work/                   DeepSeek 自己的过程、日志和产物
    to_absorb/              DeepSeek 自己的经验待审区
```

源码软链接只放在项目/工作区叶子层，不能把整个 support_level 或项目说明目录链接过去。
非源码重资产暂只建立目录和说明，实际配置情况以 ASSET_STATUS.md 为准。
源码版本会随原环境变化，每次任务记录实际 ref/dirty 状态，必要时再校验文件哈希。

## 后续 Harness 接入

2026-11-02 已完成接入：独立 Node 24.22.2、Harness 0.2.1-rc.5、独立凭据和 profile，
CLI/Web、五技能 provider 发现读取、headless 真实模型调用和首轮只读教学通过。
具体用法与版本差异以 `../../support_level/tools/deepseek-harness/USAGE.md` 为准。
以下保留接入时的设计依据，其他插件和工程能力仍需逐项验收。

安装前重新核对固定发行版的 Node 和原生依赖要求。上一轮检查发现本机 Node 为
22.22.1，而官方 master 的 package.json 要求 >=24.9.0；这两个观察不能用于证明
选定 npm 发行版已经兼容。npm 顶层包缺失 engines 字段也不能替代依赖检查。
如需新运行时，使用任务专用用户目录，避免替换现有 Node。

Harness 的运行配置、凭据和会话目录应在本环境独立落位（建议 `support_level/runtime/`），
在安装时核对 DSH_HOME 的版本行为；工作目录始终为 `workspace/`。
DSH_HOME 不作为安全隔离机制。API key 由用户在本机配置，不进入仓库或聊天记录。
当前会话继承的 NODE_TLS_REJECT_UNAUTHORIZED=0，应在安装/运行子进程中移除；
上一轮已验证移除该变量后 npm registry 可以正常验证证书并访问。

先验收 CLI/Web 启动，再做不含客户数据的模型调用。随后验收：

- 项目和上级 AGENTS.md 是否实际进入模型上下文；若未加载上级规则，须显式接入。
- 选定版本的技能发现位置、触发方式和文件权限。
- headless/SDK 的任务提交、日志、会话续接、停止与失败返回。
- 工作目录、共享源码和凭据的访问边界；提示词规则不能代替 OS 权限隔离。

## 技能设计

已从同一 GitHub 提交复制 understanding、support、compile、board-exec 和
build-customer-release，连同配套 references/assets/scripts 独立维护。
路径和共享源码规则已按本环境适配。每个技能还需做触发、路由和最小案例验收，
再扩大任务范围。

技能本体位于 workspace/.agents/skills。由于 Git 根目录在 NXP_ds_v1，
增加根目录 .agents/skills -> ../workspace/.agents/skills 的内部链接。
依据官方 skill-filesystem 文档，默认从最近 Git 根的 .agents/skills 扫描；
此规则已通过实际安装版 provider 验证；模型在首课实际加载了 understanding/support。
参考：https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/skill/skill-filesystem/README.md

不要把 Codex 专用工具名、内置工具调用语法或私有 memory 当成 Harness 接口。
客户包技能附带的 agents/openai.yaml 仅保留为原平台 UI 元数据，不作为 Harness 配置。
可复用的工程事实放 support_level；模型差异和调用适配留在 Harness 接入层。

## 历史教学设计（不作为日常任务规则）

每次练习在 `support_level/work/<日期-教学主题>/` 建立独立 case，记录：
题目与授权数据、给学生的输入、教师掌握的参考结论、学生答案、批改、修订和验收。
教师参考答案先不放在学生可以读取的目录，以免把查答案当成独立能力。

第一阶段选择历史日志和源码片段，练习区分现象、根因假设和下一条证据。
第二阶段使用一次性副本练习小补丁与检查，要求报告具体差异和未执行的验证。
第三阶段完成受控编译与交接，再由用户指定板卡和动作范围做上板练习。

Codex 可在授权范围内调用 headless/SDK 分配任务、检查结果、继续纠错。
每轮限定目标、可访问数据、时间或调用预算及停止条件，保留完整任务记录。
进程结束、模型回答完成、工程验收通过分别记录。
通过新会话和相近但不同的案例复测后，再把经验纳入长期技能。

## 当前能力入口

本页保存初始化结构和历史设计，不持有动态验收结论。
当前工具范围见对应 USAGE，任务状态见各 case；教学方法由 Codex 教师 skill
维护，不把这里的阶段安排作为普通工程任务前置。
2026-11-17 的边界修复见 ../../support_level/work/2026-11-17-workspace-scope-repair/README.md。
