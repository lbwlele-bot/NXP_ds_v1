# 本环境资产索引

资源和工具可用性按任务核对；本页不是板子当前状态或授权清单。
2026-11-02 从 GitHub 02c4fbf 导入的说明属于参考基线，不自动构成运行证据。

| 资源 | 定位与使用边界 |
| --- | --- |
| code_assets | 独立项目说明、源码叶子共享链接；修改和构建用 case 副本 |
| compile-tool | 独立程序；已执行项目见对应 case/software-state，不推广为全部项目已验收 |
| board-task | 当前 case 配置选择目标/产物/动作；支持范围及重构验证状态见 tools/board-task/USAGE.md |
| bcu / uuu / serial-console | 主机工具与手册；具体板型和本次设备状态须核对 |
| imx-rm | 说明/关系索引，程序及资料缺项须核实 |
| Image / SoC_material / linux_document | 入口说明，不代表镜像或 PDF 已接入 |
| toolchain / firmware / release_packages | 目录内 README/manifest 定位重资产；逐项验证存在性和身份 |
| i.MX943 SDK 25.09.00 | 独立普通文件副本：`release_packages/m_freertos_sdk/SDK_25_09_00_IMX943-EVK.tar.gz`；来源、身份和消费边界见 [SDK 资源交接](work/2026-11-17-imx943-sdk250900-resource/README.md) |
| skills / Harness | 五个独立工程技能、已接入 Harness；技能加载不等于任务成功 |
| work / to_absorb | 独立任务记录与待吸收经验；不复制原环境全部 case |

共享输入清单初始来源：
work/2026-11-02-deepseek-workspace-bootstrap/records/asset-links.json。
源码链接不是版本快照，使用前核对 ref/dirty 状态。

历史证据入口（只描述相应时间和实现）：

- work/2026-11-02-imx943-board-tools-lesson/README.md：初次板级工具验证。
- work/2026-11-02-imx943-imx8mp-1250-engineering-training/README.md：构建与后续部署。
- work/2026-11-17-workspace-scope-repair/README.md：任务边界修复和离线验证。

继续任务读取该 case 当前摘要、handoff、ledger、receipt；旧失败/缺收据记录
不能覆盖更新证据，历史完成记录也不能代替接手时的 fresh probe。
