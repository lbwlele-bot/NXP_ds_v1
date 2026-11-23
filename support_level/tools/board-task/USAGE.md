# board-task

有界板级执行器。接口是 `run_board_check(case_id, operation)`，模型负责根据
任务目标和实际状态选动作，工具核对身份、产物、串口 READY、动作范围并保留证据。
默认启动器提供此能力，但不会默认选择教材、设备或任务。

## 使用前

当前 executor 只支持已登记的 i.MX943 A0 / 15x15 LPDDR4、A-core/SM 串口、
SD device 1 的 bootloader 链路；不是通用刷机程序。已登记实物见 profiles/。
其他板型、介质和新增动作先补充并验证对应契约，不能套用已有 profile。

在当前 case 中创建 `records/board-task.yaml`：

```yaml
schema_version: 1
profile: imx943evk19b1-18A177
authorization:
  source: records/authorization.md
  operations: [bcu_list, bcu_identity, uuu_list, serial_probe]
  max_reset_attempts: 1
artifact: null
```

authorization.md 记录用户实际目标、已有授权、板子控制权及不可触碰范围，
不是模型自行授权。只读任务可保持 artifact 为 null；只列实际授权的动作。
准备配置本身不会操作板子。配置不等于权限隔离，正常 workspace 读写权限
仍由 Harness 配置管理，不把模型可编辑文件描述成不可绕过的安全边界。

需要消费已构建 bootloader 时，将 artifact 填成：

```yaml
artifact:
  key: task_bootloader
  id: task_bootloader_v1
  path: artifacts/flash.bin
  size: <actual-byte-count>
  sha256: <actual-64-hex-digest>
  build_recipe: <recipe-from-compile-state>
  target_module:
    carrier: i.MX943 EVK B1
    module: i.MX943 15x15 SoC A0
    ddr: LPDDR4
    software: <confirmed-software-version>
```

路径必须在本 case 内，实际大小/hash 必须匹配；工具还核对 compile-tool 生成的
state/software-state.yaml 中 imx-mkimage 产物、recipe、SOC/A0/LPDDR4。
不能从 EEPROM 的 carrier 文本推断可更换模块身份。软件兼容性仍需 compile
handoff 和工程判断；文件身份一致不证明新版本上板可用。无旧事务的新 case/产物只改配置，
不再向通用程序增加 case id/hash 常量。

## 执行与证据

同一 MCP 会话先 bcu_identity，随后根据当前未解决步骤选动作。
正常任务可连续执行，不要求每个阶段新开会话。只读探测也受任务目标约束。

### 身份、控制台与状态查询

以下操作仍须出现在当前 case 的授权列表中。除 `bcu_list` 外，均要求同一
服务会话已经成功执行 `bcu_identity`；改变 case 配置会重新要求身份核对。
表格是可选能力说明，不是每个任务必须全部执行的清单。

| 操作 | 行为与前提 |
| --- | --- |
| `bcu_list` / `bcu_identity` | 单适配器核对 / EEPROM 只读身份核对；不写 EEPROM，不证明可更换模块身份。 |
| `bcu_bootmode` / `uuu_list` | 查询启动模式 / USB 枚举；不复位、不传输，不单独证明运行阶段。 |
| `serial_recover` / `serial_probe` | 恢复主机 UART 驱动 / 核对当前适配器与串口角色。BCU 访问后先恢复再探测。 |
| `serial_capture` | 被动捕获 A-core/SM 8 秒；日志无输出不等于板卡失败。 |
| `serial_wake` | 当前 case 已有被动捕获记录后，在 A-core 发一个换行并捕获响应。 |
| `serial_login_root` | 仅在上次交互末尾观察到 login/password 提示后发送实验板 `root`；不猜测其他凭据。 |
| `linux_status` | 上次交互末尾必须为 root Linux prompt；查询 uname、os-release、链路、地址和 uptime。不会检查 remoteproc/固件身份。 |
| `serial_shell_status` | 保持一条串口连接，条件性换行、实验板登录和上述固定 Linux 查询；最长约 35 秒。未见完成标记时不能宣布查询完成。 |
| `uboot_storage_status` | 当前 case 最新 `.log` 必须以 U-Boot prompt 结尾；查询 fdtfile/image/bootcmd、MMC1 分区和 FAT 目录。会把 U-Boot 当前 MMC 设备临时选为 1，但不写存储、不启动镜像。 |

查询结果和原始命令保存在当前 case 的 `logs/`；查询成功不等于生成了完整
工程状态，仍由 `board-exec` 更新 ledger。更细的只读调查并不包含在
`linux_status` 等固定查询中；先核对相应工具手册、当前阶段和任务授权，
不要为了取得固定查询之外的信息调用 reset/刷写操作。

注意 `serial_wake` 和 `serial_shell_status` 的条件性换行都是主动输入：
U-Boot 可能重放上一条命令。已有 U-Boot prompt 时不要用它们冒充被动刷新；
阶段未知时也须评估重放风险。被动观察使用 `serial_capture`，具体交互边界见
`../serial-console/USAGE.md`。这些查询入口不是任意现场的无副作用保证。

### 启动、下载和恢复

- confirm_case_usb_identity：fresh BCU/USB 与当前产物绑定；已有匹配 receipt
  时验证并复用，不覆盖原证据。换板、换产物的旧 receipt 不自动迁移。
- uuu_boot_case_flashbin：SDPS RAM boot，校验 spl recipe、双串口 READY、
  实际产物和 software-state；FB 后置条件成立才记录完成。
- uuu_flash_case_bootloader：匹配 RAM receipt、fresh FB 后，只写 SD bootloader，
  显式 sd_dev=1；不写 FAT/rootfs/eMMC。失败写入不自动重试。
- reset_sd_case：消费 matching write receipt；复位成功不等于运行验证成功。
- reset_usb/reset_sd/reset_bootswitch：只做当前授权的复位和前后探测；
  ledger 描述该动作事实，不替任务层生成后续禁令。

attempted/completed 和原始日志不能删除来绕过保护。复位按任务预算计数
（每模式有限正整数，示例 1 次，由任务目标确定，不设教学用全局次数上限）；
reset_sd 与 reset_sd_case 共用 SD 模式预算。再次复位仍核对控制进程、串口占用及 READY。
旧事务结果不明时，可在已有授权内使用 review_reset：检查主机 BCU/UUU 无
残留、单板身份、串口未占用并 fresh probe，追加审查记录，不执行复位或存储写入。
它不证明旧动作成功，也不增加预算。预算耗尽或存储写入结果不明时先分析，
需要新范围再询问用户，不必须由 Codex 教师处理。
物理设备锁按 adapter 放在 support_level/runtime/board-task/，不按 case 分锁；
它只能协调本工具，仍需确认没有其他工具控制同一块板。

当前恢复边界：RAM attempted/completed 和写入 receipt 尚未实现同 case 的
多版本/多次事务。已有 RAM 事务后再次下载、或已有 receipt 后更换产物，不能
仅改配置继续；先读取原证据，说明当前状态与需要的恢复动作，再补充并验证
对应事务契约。不要删除 marker/receipt 或另建 case 绕过。这是工具能力缺口，
不是要求某位教师永久审批，也不是要求用户为每个正常工程步骤重新授权。
本版只解决复位的有界审查/重试，不声称已经提供完整的板级自主恢复。

## 工具环境

固定 UUU 路径由程序选择，不能依赖 PATH 中另一版本。已知 second-stage 的
sd recipe 必须显式 sd_dev=1。命令、USB、启动和业务结果分别验收。
fuser 参数以安装版本支持为准，by-id 先解析存在的 tty；BCU if01 不作为
A-core/SM 占用门。read-only sandbox 的最小 /dev 不代表主机设备消失，
在这种隔离环境下使用主机 MCP 证据，不将沙箱 lsusb 结果解释为板故障。
readonly patch 不限制独立 MCP 的硬件能力，是否可执行由本任务范围决定。

旧 standard/1250 bundle 专用操作不再出现在正常 MCP schema。
其旧实现、产物绑定和测试保存在修复 case 的 before/ 历史快照；当前通用接口
覆盖上述 bootloader 链路。FAT bundle 部署不是本版已迁移能力，不能用 bootloader
写入代替；需要时单独建立输入契约和回归，不恢复默认教材硬编码。

## 验证

`python3 -B tests/test_board_task.py`：临时案例的身份、路径、hash、授权、
receipt、协议/recipe、复位预算和恢复行为回归；不读取真实教材产物。
所有硬件调用在测试中替换或禁止，离线通过不证明真实板级行为。
2026-11-17 的重构尚未做实机复验。此前实机证据仍属于原实现和原 case。
