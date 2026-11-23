# m_freertos_sdk

这是 M 核 SDK 的独立 producer。它先生产带身份的 ELF/BIN，随后才由
imx-mkimage、Linux remoteproc 或其它 consumer 选择需要的格式。

## 唯一公开编译入口

把本目录 `COMPILE_CHECKLIST.yaml` 复制到当前 case 的固定位置：

```text
records/compile/m_freertos_sdk/compile.yaml
```

AI 只填写 SDK 包、编译器、具名 jobs 和 `intent.scope/reason`，然后提交：

```bash
compile-tool prepare <case>/records/compile/m_freertos_sdk/compile.yaml
compile-tool run <case>/records/compile/m_freertos_sdk/compile.yaml
```

不能填写 raw command、backend、任意输出路径或内部 manifest/request。
工具根据本轮实际 SDK 包和 job 生成全部命令、环境变量及发布路径。

SDK 包不是 AI 可以自动获取的 Git 源码。目录中缺目标包时，`prepare` 当前返回
`USER_INPUT_REQUIRED`，列出包 ID、版本和期望放置位置。这个返回不等于必须由人
手工提供每个已授权已知包：先转资源 owner 在既有授权内核查已有共享来源并准备
必要输入；只有确实需要超出既有授权的外部获取，或存在凭据/权限/许可/版本决策
缺口时，才交给用户。
工具本身不实现登录或下载；资源获取仍按上述任务授权与许可处理。
用户新提供的未登记包可在 `sdk` 中增加 `archive`、
`sdk_release` 和 `trust_reason`，无需先修改全局 `PACKAGES.yaml`。
工具加载全目录元数据并校验路径边界，只对本轮选中的归档检查存在性和实际 SHA-256。
登记落点哈希不符会拒绝，不自动降低信任后继续；显式 case 输入匹配已知目录哈希时
标记为 `catalog_verified`，不匹配则必须有 `trust_reason` 并标为 `user_attested`，
不伪装成已知厂商包验证。

一张清单可以声明多个 job，例如 `m33s`、`m70`、`m71`。每个 job 独立维护
状态；`intent.scope` 只重建或导入本轮选择的 job，范围外 job 必须已有可复用
成功状态。

## 来源和产物

- `source_build`：必须从同一 job 发布 `<job>.elf` 和 `<job>.bin`，分别导出
  `nxp.mcore.elf` 与 `nxp.mcore.bin`。
- `prebuilt_import/vendor_package`：只允许导入本轮已确认 SDK 压缩包中的明确
  成员；工具校验选中包和成员，允许只有 BIN。包来自已知目录时为
  `catalog_verified`，来自用户新提供文件时继承 `user_attested`。
- `prebuilt_import/user_supplied`：文件必须位于当前 case，清单填写预期
  SHA-256 和信任理由；状态标为 `user_attested`，不声称厂商验证。

artifact identity 至少包含 `soc`、`board`、`core`、`core_role`、
`application`、`build_configuration`、`sdk_release` 和 `origin`。Linux
remoteproc 后续可以消费 ELF；flash.bin 只允许消费 `nxp.mcore.bin`。

## backend 硬规则

- SDK `2.x`：legacy。
- YYMM `<= 25.09`：legacy。
- YYMM `>= 25.12`：MCUX West。
- `25.10/25.11`或无法解析的版本：阻断；用户新提供包无需预先登记，但必须
  明确 SDK release、case 内路径和信任理由。
- 版本选择与压缩包结构不一致：阻断。

legacy 必须存在精确的
`boards/.../<core>/armgcc/build_<configuration>.sh`。工具不再执行原厂脚本，
而是从受支持的标准脚本中解析已知 CMake 缓存清理、唯一 `cmake` 配置和唯一
`make` 构建，生成分离的 clean / configure / build 步骤。脚本显式配置参数、
release/debug、相对工具链路径和生成器语义会保留；未知命令、额外配置/构建
调用、未知清理目标或不匹配的生成器会 fail-closed，并给出脚本路径和行号。
原脚本只读，源包内容不改。

legacy 解析采用明确子集而不是透传未知参数：

- `make` 只接受标准 `-j` / `-jN` / `--jobs` / `--jobs=N` 并发写法；
  命令行变量赋值全部拒绝，不通过变量名黑名单判断其是否安全。
  自定义脚本需要单独审查并扩展契约。`-C`、`--directory`、`-f`、`--file`、`-o`、`-W`、
  `-n`、`-t`、`-q`、组合短选项（如 `-kj`）和显式 target 等未知构建语义
  全部拒绝。`MAKEFLAGS`、`MFLAGS`、`GNUMAKEFLAGS`、`MAKEFILES` 等变量
  赋值也拒绝。
- `cmake` 只接受配置模式下的 `-G`、`-D CMAKE_BUILD_TYPE`、
  `-D CMAKE_TOOLCHAIN_FILE` 和源目录 `.`；`-P`、`--build`、`-E`、
  `-B`、`-T`、`-A`、`-C`、`--toolchain` 等非配置模式/后端替换参数拒绝。
- 实际执行时显式设置生成器和 make 程序，并清空继承的
  `MAKEFLAGS`/`MFLAGS`/`GNUMAKEFLAGS` 等环境，避免主机环境改写有限并发或
  后端选择。

清单可选 `parallelism`（正整数，默认 2）只给 legacy source_build 的显式
`make -jN` 上限。工具不沿用脚本里可能无界的 `make -j`，也不依赖环境变量作为
唯一限制。`prepare` 只在本轮 scope 含 legacy source_build 时显示有效值；
只有 West、prebuilt_import 或复用 job 时显示“不适用”，不承诺未实施的限制。该值进入构建
configuration/state 并使旧 prepare 失效，但不属于 artifact 的 board/core
identity。configure 和 build 是独立命令，失败退出码不会被 `tee` 吞掉，
失败后不会继续执行发布步骤。

West 必须包含 `.west/config`、`manifests/west.yml`、
MCUX West build 扩展和匹配 job 的 `example.yml`；工具生成受控
`west build`，将 `board@core` 拆为 `-b <board>` 与 `-Dcore_id=<core>`，并用
`-p always` 隔离失败缓存。West 和 prebuilt_import 不应用 legacy 脚本解析规则。

### 主机资源边界

已知本机 SDK 25.09.00 的 CM70 Linux RPMsg ping-pong `build_release.sh` 使用
无限制 `make -j`；2026-11-17 的一次执行触发主机 OOM 并杀死 VS Code，虽然产物
最终生成。修复后的 legacy 路径执行有限并发的分离命令；但有限 jobs 不保证
任意 SDK/编译单元都适合主机容量，合成测试不能代替实际资源验证。
该 case 已完成一次有限并发真实重建，证据见
`../../work/2026-11-17-imx943-cm70-rpmsg-build/records/run-verify.md`；
这不是所有 SDK、工具链或主机的资源安全保证。
工程证据：`../../work/2026-11-17-imx943-cm70-rpmsg-build/records/host-oom.md`，
实现与验证边界：`../../work/2026-11-17-imx943-cm70-rpmsg-build/records/parallel-fix.md`。

工具自动设置 `ARMGCC_DIR` 并记录编译器身份。当前
`SDK_2_9_0_EVK-MIMX8DXL` 源码构建仍强制 GCC 9.2.1；预编译导入不伪装成
本地构建，也不要求为了导入 BIN 重新编译 SDK。

## 与 flash.bin 的边界

M producer 只负责产出 M 核 artifact。imx-mkimage 的 `soc.mak` 决定当前 recipe
实际需要哪些 M 镜像和文件名，compile-tool 再补 producer identity：

- 当前源码的 i.MX95 `flash_all` 由 `soc.mak` 得出 `core_role=m7` 的 BIN；
- 当前源码的 i.MX94 `flash_all` 由 `soc.mak` 得出 `m33s`、`m70`、`m71` BIN；
- recipe 内部固定落位为 `m7_image.bin`、`m33s_image.bin`、
  `m70_image.bin`、`m71_image.bin`，AI 不能改名。

可信预编译 BIN 也必须先经过本清单导入，不能作为 mkimage 裸文件输入。
producer 成功不等于 flash.bin 已经打包成功，更不等于 M 核已上板运行。

相关资产：

- `../../release_packages/m_freertos_sdk/PACKAGES.yaml`
- `../../release_packages/m_freertos_sdk/`
- `../../toolchain/`
- 必要时回看 `../../code_assets/projects/mcuxsdk-core/`
