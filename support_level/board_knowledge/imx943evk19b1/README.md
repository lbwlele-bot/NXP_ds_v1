# i.MX943 EVK B1 carrier

## 身份必须拆层

BCU EEPROM 身份、carrier、可更换核心板、DDR 和启动产物不是同一个字段。

2026-11-02 历史验收实物（不替代当前模块确认）：

| 层 | 历史证据 |
| --- | --- |
| BCU board id | `imx943evk19b1` |
| FTDI | `18A177`，历史 location `3-1.3.3` |
| EEPROM Board Info | `NXP i.MX943 19x19 EVK Board Rev B1` |
| carrier | B1 |
| 可更换核心板 | i.MX943 15x15，SoC A0 |
| DDR | LPDDR4，U-Boot RAM 启动实测 7.8 GiB |
| PMIC | MFS5600 |

EEPROM 的 `19x19 EVK` 是板控/carrier 注册身份，不能据此选择 19x19 OEI、
DDR firmware 或 flash.bin。FTDI `18A177` 的历史 case 明确是 B1 carrier 上的
15x15 LPDDR4 核心板；当时的 15x15 标准镜像已 RAM 引导到 SPL/BL31/OP-TEE/U-Boot。

机器 profile：`../../tools/board-task/profiles/imx943evk19b1-18A177.yaml`。
标准产物 manifest：
`../../firmware/imx943/boot-baselines/15x15-lpddr4-rte34/MANIFEST.yaml`。

## 串口

- onboard FT4232H 四接口，115200 8N1；
- `if01` 是 BCU channel，BCU 后可能从 `ftdi_sio` 解绑；
- `if02` 是 A-core，负责 SPL/BL31/U-Boot/Linux；
- `if03` 是 SM；
- `if00` 应用核 role 仍是 partial，不根据端口顺序补猜。

任何需要 reset 起始日志的动作：

1. BCU identity；
2. `serial-console recover`；
3. `serial-console probe`；
4. 启动 a-core/sm `capture-set`；
5. READY 同时核对 `state=active`、本次 PID、roles；
6. 才能 reset/UUU；
7. 动作后 fresh USB、串口、CPU0 阶段探测。

## 2026-11-02 阶段链历史

2026-11-02，DeepSeek 经固定 MCP 真正执行：

- `reset usb -hold=2000 -auto` 后：MX943 `SDPS 1FC9:0027`；
- hash-pinned 15x15 LPDDR4 `flash.bin` 经 `uuu -b spl`：
  SPL → BL31 → OP-TEE → U-Boot Fastboot `1FC9:0152`；
- UUU RAM boot 不等于 Linux；USB manufacturing 路径会进入 U-Boot Fastboot；
- 从现成 FB 单独运行 `-b sd` 时必须显式传 `-e sd_dev=1`；否则 built-in
  recipe 中 `${sd_dev}` 无上下文，可能在真正写入前失败；
- 修正后 `flash bootloader` 返回成功，fresh `reset sd -hold=2000 -auto`
  已从 SD 走到 SPL → BL31 → OP-TEE → U-Boot；
- 当时 SD 的 FAT 分区只有 i.MX93 DTB，没有 `imx943-evk.dtb`。U-Boot 虽读到
  35,633,664-byte `Image`，仍以 `Failed to load 'imx943-evk.dtb'` 停在 prompt；
- 物理 BOOT SWITCH 路径曾出现 `read_auth_image wrong`、
  `mmc block read error`、`Error: -38`；这是启动失败证据，不足以单独归因。

阶段必须分别表述：

`SDPS -> UUU transfer -> SPL -> U-Boot/FB -> storage write -> fresh reset -> Linux login -> root shell -> application PASS`

任何前项成功都不自动覆盖后项。

因此当次 SD 的状态记录为 `bootloader repaired, Linux payload mismatch`。
这不是 bootloader 写入失败，也不是 Linux-up。若目标是 Linux，下一步必须选择
与 i.MX943 15x15/LPDDR4 和该 bootloader 软件组合匹配的 Image、DTB、rootfs，
不能把现有 i.MX93 文件改名冒充。

上述记录不描述今天的 SD 内容，也不要求后续任务重复当次路径。
分区中出现其他板型 DTB 本身不是 mismatch，必须核对实际选择/加载的文件。

## 工具化入口

在当前任务属于受支持范围时使用 `board-task` MCP，配置和授权见其 USAGE：

- 文档：`../../tools/board-task/USAGE.md`
- MCP：`mcp__board_task__run_board_check`
- 每次提供当前 `case_id`
- 所有原始 argv、退出码和输出进入当前 case 日志

`board-task` 当前 profile 只覆盖 FTDI `18A177`。换另一块 B1 实物时，先建立
新 profile；不能因为 board token 相同就复用核心板/DDR/USB serial 事实。
