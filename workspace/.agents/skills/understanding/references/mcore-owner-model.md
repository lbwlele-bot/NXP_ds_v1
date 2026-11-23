# `M` core loading and lifecycle model

## 核心结论

M 核问题不能压缩成一个单一 owner。

至少要分别确认：

1. payload 被放在哪里
2. 谁负责加载并启动
3. 谁负责后续生命周期和资源管理
4. M 核运行后与其它处理器遵守什么通信和内存契约

这四项可以由不同组件承担，不能互相替代。

## 四个独立维度

### 1. Packaging carrier

描述 payload 作为 artifact 被放在哪里，例如：

- 被打包进 boot image / `flash.bin`
- 放在存储分区或文件系统
- 由 U-Boot 从某个地址或文件读取
- 作为 Linux firmware 文件提供

packaging carrier 不是运行时 owner，
也不能单独证明 payload 会被加载或启动。

### 2. Loader / starter

描述谁实际把 payload 放入目标内存并发起启动，例如：

- early boot flow
- U-Boot
- Linux remoteproc
- 板型特有的系统控制固件或启动机制

要区分“payload 已经在 image 中”和“某个阶段确实启动了目标核”。

### 3. Lifecycle and resource manager

描述运行期间谁负责：

- 核的 start / stop / reset / suspend / resume
- power domain 和 clock
- memory region 和 peripheral ownership
- interrupt 和 wakeup route
- 与系统控制固件的资源协调

loader 和 lifecycle manager 不一定是同一个组件。
某些责任还可能分散在 Linux、ATF、SCFW/SMFW 和 M 核 firmware 之间。

### 4. Runtime contract

描述 M 核运行后与 A 核或其它组件之间的契约，例如：

- RPMsg / virtio / MU
- resource table
- vring 和 shared memory
- device address 与 system address
- cache、MPU、DMA 和内存属性
- notification、interrupt 和 wakeup

runtime contract 是否存在、如何实现，
不由 loader 路径单独决定。

例如：

```text
M 核 payload 被打包进 flash.bin
-> early boot flow 启动 M 核
-> Linux 不负责加载 M 核
-> Linux 和 M 核仍通过 resource table、RPMsg 和 shared memory 协作
```

因此“不是 Linux remoteproc 加载”不能推出“不需要 resource table”。

## 建立问题身份

开始修改或执行前，至少回答：

- 目标是哪颗 M 核或辅助核
- 当前板型有哪些保留核，哪些核允许当前 case 使用
- payload 的版本、链接地址和运行内存是什么
- packaging carrier 是什么
- loader / starter 是谁
- lifecycle 和资源分别由谁管理
- runtime contract 包含哪些通信、地址和内存约束
- 当前观察证明了 artifact、loading、running 还是 communication

如果其中一项未知，应把它保留为未知，
不要用另一个维度的事实代替。

## 证据边界

| 现象 | 能直接证明 | 不能自动证明 |
|------|------------|--------------|
| binary 文件存在 | payload artifact 存在 | 已被打包、加载或启动 |
| payload 出现在 boot image 中 | packaging 成立 | 目标核已运行 |
| 启动命令返回成功 | 某个 starter 发起过动作 | firmware 主逻辑正常 |
| Linux 出现 remoteproc 节点 | Linux 有管理入口 | 当前 payload 由 Linux 加载 |
| M 核串口有输出 | M 核执行到可观察位置 | 通信和资源契约正常 |
| RPMsg channel 出现 | 部分 runtime contract 已建立 | suspend/resume 等生命周期正常 |
| resume 后通信仍正常 | 当前周期的生命周期和通信恢复成立 | 所有低功耗路径都成立 |

### 将运行观察归因于目标 payload

运行态、firmware 文件名和加载日志中的名字，不单独证明已加载内容的身份。
应把加载时的内容证据（如校验值或可追溯的部署记录）、对应加载事件和后续
运行观察关联起来；当前磁盘文件的 hash 不能追溯证明此前加载的字节。
mtime 晚于加载只提示时间关系，touch 或相同字节覆盖也会更新时间，不能单独
证明运行内容不同；已知加载后替换了不同内容，则不能把新文件归因到旧运行结果。

已有可信加载绑定，且没有后续替换运行载荷的事件时，可以复用该证据继续验证，
不因新会话、文件时间变化或文件同名就强制重载。证据缺失时先补最小来源/时序
证据；若需受控重载，仍由执行 owner 核对当前控制权、授权和可用路径。

## 路由

根据当前 unresolved step：

- 查 payload、板型约束、已有日志和固件来源：`support`
- 构建 payload、修改链接、打包 boot image 或实现运行契约：`compile`
- 执行加载启动、观察串口、操作 remoteproc 或验证运行态：`board-exec`
- 四个维度仍被混为一个 owner：
  继续由 `understanding` 拆分问题

## 常见误判

- 把 `flash.bin` 当成 M 核运行时 owner
- 把 packaging 成功当成 loading 或 running 成功
- 根据 loader 路径推断是否需要 resource table
- 看到串口输出就认为 RPMsg、资源权限和低功耗路径都正常
- 未确认保留核和板级资源边界就尝试接管目标核
