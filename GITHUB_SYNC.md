# GitHub 轻量同步

仓库：`https://github.com/lbwlele-bot/NXP_ds_v1`，默认分支 `main`，公开。
本地 Git 根：`/home/ives/桌面/NXP_ds_v1`。
与 Codex 的 `lbwlele-bot/nxp_ivesliu_skill` 独立，不把两套环境的修改互相覆盖。

## 收录范围

- 根目录与 workspace 的入口规则、设计说明和五个工程 skills。
- support_level 中已纳入 Git 的资源索引、项目说明、构建契约和模板。
- 自有轻量工具脚本/源码、对应测试、USAGE 和配置；包括 Harness 启动器、
  compile-tool、board-task 和 serial-console。
- `.agents/skills` 是指向仓库内 `workspace/.agents/skills` 的相对链接。

## 只留本地

- API key、`.env`、认证信息、Harness 会话/运行时、node_modules。
- `support_level/work/` 和 `to_absorb/` 的任务内容，仅保留各目录 README。
- 源码树及其共享叶子链接、SDK 包、镜像、固件本体、工具链、PDF。
- BCU/UUU 本机二进制、串口日志、编译产物、数据库和缓存。
- firmware 内的既有具体教材 manifest 也保持本地；通用构建输入身份见已跟踪
  的 compile_targets/flashbin/FIXED_ASSETS.yaml 等构建契约。

排除项由 `.gitignore` 管理。不得通过 `git add -f` 上传凭据、case 或重资源。
提交前审查完整暂存清单及差异；修改忽略规则后重新核查。
仓库公开可读，不得存放 API key 或其他敏感内容。

## 在其他机器恢复时

这是本机轻量环境的版本记录，不是已验证的一键安装包。README、USAGE 中的
本机绝对路径、历史 case 引用与实物 profile 仍有环境依赖；被排除的 case 链接在
纯 clone 中不存在是预期现象，不应为补链接而复制旧会话或客户材料。

1. 获取仓库后先读 AGENTS.md、workspace/AGENTS.md 和 ASSET_STATUS.md。
2. 按工具 USAGE 补齐 Harness/Node、BCU/UUU、工具链和所需重资产；既有启动器
   期待的本地目录布局见 support_level/tools/deepseek-harness/USAGE.md。
3. 重新建立共享源码输入路径，核对版本；不要对共享叶子原地修改或构建。
4. API key 只在本机通过 configure-api-key 输入；不要写进 Git 或命令行。
5. 核对绝对路径与设备 profile。已有 943 profile 不是新设备或 i.MX95 的身份
   证明；硬件动作前仍需当前身份、连接、范围和 fresh probe。

本次首次发布只验证上传范围、基本语法和远端提交一致性，不重新宣称构建、
板级功能或跨机器部署已经通过。教师 skill 保留在 Codex 仓库，不混入学生工程入口。
