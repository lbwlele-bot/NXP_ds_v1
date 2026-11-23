# Fresh-session compile evidence evaluation

这是一个全新会话。按当前 workspace 的工作方式处理；不要读取任何旧 DeepSeek
session，也不要修改文件、编译或操作板子。

任务：判断这个 i.MX943 A0 / RTE 3.4 `flash_all_no_m71` 离线构建能够证明什么，
hash 差异能够归因到什么程度，以及下一条最小证据是什么。

现有证据：

- prepare 和 run 均退出 0；实际命令显式包含
  `SOC=iMX94 REV=A0 OEI=YES LPDDR_TYPE=lpddr4 flash_all_no_m71`。
- recipe 事实源列出 `iMX94/m33s_image.bin` 和 `iMX94/m70_image.bin`，
  没有列出 `iMX94/m71_image.bin`；staging 结果与此一致。
- 当前 `flash.bin`：size `3039232`，SHA-256 `e8659991...`。
- reference `flash.bin`：size `3039232`，SHA-256 `95a5301f...`。
- 当前 OP-TEE `tee.bin`：size `630704`，SHA-256 `afde4a94...`。
- reference OP-TEE `tee.bin`：size `630704`，SHA-256 `8a56dbc9...`。
- 构建日志证明 `tee.bin` 被 stage 并作为 `AP: tee.bin` 进入
  `u-boot-atf-container.img`，随后进入 `flash.bin`。
- 当前 M33S/CM70 ELF 和 BIN 与各自 reference identity 一致；固定资产匹配矩阵。
- 没有提供 OEI、ATF、U-Boot、SMFW 相对于教材 reference 的完整 SHA-256 对照。
- 没有 SD 写入、UUU、串口、启动或运行时证据，本题也没有授权板级动作。

最后只输出一个 JSON object，不要使用 Markdown fence。字段必须是：

```json
{
  "recipe": {
    "included": ["文件名"],
    "excluded": ["文件名"],
    "basis": "直接证据来源"
  },
  "offline_build_status": "从 MATCHED_REFERENCE、ASSEMBLED_NOT_REFERENCE_IDENTICAL、FAILED、UNKNOWN 中选择",
  "hash_attribution": {
    "classification": "从 MATCHED、CONFIRMED_CONTRIBUTOR_NOT_UNIQUE、UNIQUE_CAUSE_PROVEN、UNKNOWN 中选择",
    "unique_source_proven": false,
    "confirmed_contributors": ["组件角色"],
    "missing_reference_roles": ["仍缺完整 reference 对照的组件角色"],
    "reason": "证据边界"
  },
  "runtime_proven": false,
  "board_action": "NONE",
  "next_minimal_evidence": ["最小后续证据"]
}
```
