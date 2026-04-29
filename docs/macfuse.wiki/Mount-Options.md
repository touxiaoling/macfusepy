### allow_other

默认情况下，macFUSE **仅允许挂载该卷的用户**访问卷；其他任何用户——包括 root——都无法访问他人的卷。这项全面拒绝是一道防线，对抗行为异常（无论有意无意）的用户态文件系统可能导致系统程序「卡死」（hang）。若你信任某一文件系统，或确信可以放开限制，可使用 `allow_other` 关闭该限制。例如，若要在 macFUSE 卷上使用 Spotlight，就需要 `allow_other`。

启用 `allow_other` 后，卷对所有用户的访问表现为正常，仍会照常进行权限检查。注意：`allow_other` 属于特权选项——**仅** `root`，或属于 **macFUSE admin group**（管理员组）的用户可使用。加载 macFUSE 内核扩展时，装载器会将该组的 ID 设为 macOS 上的 admin group ID。root 可通过 `sysctl` 接口修改该 ID（macFUSE 允许你指定任意 group ID，包括不存在的组）：

查看 admin group ID：

```
% sudo sysctl vfs.generic.macfuse.tunables.admin_group
vfs.generic.macfuse.tunables.admin_group: 80
```

设置 admin group ID：

```
% sudo sysctl -w vfs.generic.macfuse.tunables.admin_group=81
vfs.generic.macfuse.tunables.admin_group: 80 -> 81
```

### allow_recursion

默认情况下，不允许在**自身已位于某一 macFUSE 卷内的目录上**再次挂载 macFUSE 卷。此类递归挂载在部分情形下可能在卸载（unmount）时引发问题。与多数其他 macFUSE 限制不同，此项为「软」检查，仅由挂载工具执行。`allow_recursion` 可关闭该限制。

### allow_root

请先阅读上文 `allow_other` 说明。`allow_root` 与之类似，但「其他用户」集合**仅包含** root。使用 `allow_root` 需要你是 macFUSE admin group 的成员。

### auto_cache

默认情况下，若 macFUSE 在 `getattr()` 检测到文件大小变化，会丢弃该文件的缓冲区缓存（buffer cache）。启用 `auto_cache` 后，还会在 `getattr()` 与 `open()` 中检测修改时间变化，并在必要时自动清理缓冲区缓存及/或文件属性，并生成相应的 kqueue 消息。`auto_cache` 默认**不**启用，需显式选择。若想主动告知内核远端变更，建议使用非请求式 notification API，而不要依赖 `auto_cache`。

### auto_xattr

默认情况下，macFUSE 以灵活自适应的方式处理扩展属性（extended attributes），包括 Finder Info、Resource Fork、ACL 等：起初会把扩展属性相关调用转发给用户态文件系统；若后者未实现相应函数，macFUSE 会记住并将后续调用不再上报，改为以 Apple Double（`._`）文件存储扩展属性。若用户态实现了扩展属性回调，可自行处理全部或部分属性；若有若干属性希望由 macFUSE（内核）经 `._` 文件处理，应对这些属性返回 `ENOTSUP`。`auto_xattr` 表示：**不要**再将任何扩展属性调用转发给用户态；无论用户态是否实现对应函数，内核都将**始终**使用 `._` 文件。

### daemon_timeout

`daemon_timeout=N`，其中 `N` 为超时秒数。

内核调用用户态文件系统时，后者须在合理短时间内应答，否则这些调用——以及发起调用的应用程序——会「卡住」。不能完全信任用户态程序，它们可能无意中或恶意地永不响应。典型情况包括：文件系统因缺陷崩溃而无法应答，或其中的网络操作耗时过长。内核无法获知真实原因，但必须防范挂死。

若需逐次挂载微调，可使用 `daemon_timeout` 指定上述时限（秒）。**默认超时为 60 秒**。若确实发生超时，卷会被**自动卸载**（已打开文件中的数据可能丢失）。

### debug

`debug`（或简写 `-d`）使用户态文件系统守护进程打印请求与响应的调试信息，并以**前台（foreground）**模式运行。

### default_permissions 与 defer_permissions

与扩展属性类似，macFUSE 对权限检查也采用灵活机制。默认会向用户态发送访问类消息参与权限判定（参见 `access(2)`）。若文件系统未实现 `access`，macFUSE 将**完全**依据文件系统对象属性自行做权限检查。`default_permissions` 也会启用此类行为：内核根据「可见」信息（文件系统上报的权限位）尽量做正确判断。但文件系统本身未必总能做对——例如从远程机器取回文件信息并**原样**上报 UID/GID 时，内核不会把「外来」ID 视为挂载用户（在未启用 UID 映射或 sshfs 等场景下偶发）。此时 `defer_permissions` 有用：macFUSE 假定**允许**所有访问，把所有操作都转发给文件系统，由**其他环节**最终决定允许或拒绝（对 sshfs 而言，常为远端 SFTP 服务器）。

### direct_io

部分文件系统可能无法获知所提供文件的**准确大小**：例如内容流式传输，难以定义「大小」；或内容动态变化，在 `getattr` 时公布的大小在读/写时已变。这类文件系统希望在不依赖精确文件大小的前提下读写。内核常规 I/O 路径做不到这一点。`direct_io` 让 macFUSE 在内核与用户态之间采用另一条「直通」I/O 路径，使文件大小不再参与判定，读持续到文件系统停止返回数据为止；副作用包括**完全绕过 unified buffer cache（UBC）**，因而 **不可用** `mmap(2)`，许多高层应用会出现兼容性问题。`direct_io` 为非标准运行模式；除非确有需求，不要使用。

### extended_security

macFUSE 支持访问控制列表（ACL）。`extended_security` 为该卷启用此项。要正确支持 ACL，用户态须正确处理扩展属性 `com.apple.system.Security`。也可把 ACL 存进 Apple Double（`._`）文件中凑合使用，但该做法不安全（`._` 可被直接篡改），仅能用于试验。

### -f

`-f` 使用户态文件系统以**前台**模式运行。

### fair_locking

默认 macFUSE 使用「非公平」锁机制以保证文件系统一致性；当并行操作极多时，可能导致部分实时任务耗时过长。**fair_locking** 使操作以更公平顺序处理；相比「非公平」锁略有性能开销，但在高压场景可能更合适。

### fsid

`fsid=N`，其中 `N` 为 **24 位**整数（`0` 与 `0xFFFFFF` 无效）。

默认每次挂载 macFUSE 都会生成新的文件系统 ID。**若**你希望卷在重新挂载后仍保持稳定的文件系统 ID（例如别名 alias 场景），而由于 macFUSE 卷并无真实后备设备 backing device，单凭默认行为无法实现。`fsid` 即用于指定一个 24 位数，用以生成持久化的文件系统 ID。

### fsname

`fsname=NAME`，其中 `NAME` 为字符串。

可用于指定「文件系统名称」，类比磁盘文件系统中设备（device）的概念。如下挂载信息中的 fsname 为 `sshfs#singh@127.0.0.1`：

```
% mount
...
sshfs#singh@127.0.0.1:/tmp/dir on /private/tmp/ssh (macfuse, nodev, nosuid, synchronous, mounted by singh)
...
```

注意：

* 文件系统守护进程可自行指定 `fsname`，并覆盖用户传入的 `fsname`。
* 若实现对**基于磁盘的文件系统**重命名支持，`fsname` 须指向对应后备设备，否则无法通过程序卸载卷。

### fssubtype

`fssubtype=N`，其中 `N` 为整数。

用于指定当前挂载的 macFUSE 卷的**文件系统子类型**标识。**访达（Finder）** 用该 subtype 读取文件系统的描述字符串（若有）：即在卷上执行 「显示简介」（Get Info）时，「格式:」旁的说明。该项仅对已登记在 macFUSE 安装的 `macfuse.fs` bundle 中的 subtype–字符串 对已生效。

### fstypename

`fstypename=NAME`，其中 `NAME` 为字符串。

用于指定文件系统的 **type 名称**。`NAME` 最多 **6** 个字符（若指定则至少 1 个）。内核中的文件系统类型将为 `macfuse_NAME`：`macfuse_` **前缀由内核自动添加**。此后，使用该选项的用户态文件系统在磁盘上的 bundle 须命名为 `macfuse_NAME.fs`。访达及其他会查看 bundle 的程序现会从**该** bundle（而非默认的 `macfuse.fs`）读取 subtype、描述字符串等。`fssubtype=N` 仍可使用。不需要自定义 `fstypename` 的文件系统行为与过去一致。注意：任意程序可能依赖**真实**文件系统类型，该选项的副作用**无法完全预知**——使用本选项即表示接受「可能破坏未知依赖」的一般性风险。

### iosize

`iosize=N`，其中 `N` 为挂载卷默认 **I/O 块大小**（字节）。

用于指定访问假想的 FUSE 卷后备存储时使用的 I/O 块大小。最小块大小在 **Apple Silicon** 上为 **16,384** 字节，在 **Intel** 上为 **4,096** 字节；最大为 **32 MiB**（33,554,432 字节）。**默认**为 **64 KiB**（65,536 字节）。I/O 块大小须为 2 的幂。

如何选择较优块大小：

* 若假想的后端链路**较慢**（如慢速网络），建议使用**较小** I/O 块，以保证访问大文件时卷仍响应及时。

* 若链路**较快**（如本地文件系统或高速网络），**较大** I/O 块可减少访问开销，并可能显著提升性能。

### jail_symlinks

可将符号链接「限制」在 macFUSE 卷内部。遇到**绝对路径**符号链接时，macFUSE 会在其前加上挂载路径前缀。

### local

该选项将卷标为 **本地（local）** 卷。默认 macFUSE 卷标为 **非本地**；技术上未必等同「服务器/网络」卷，但访达在多种情形下会按网络卷处理。使用 `local` 可规避该行为；但 macOS 对「本地」卷会更激进（例如创建 `.Trashes`），可能引发 **Disk Arbitration** 等组件的异常问题。该选项影响面未完全摸清，请视为**实验性**并谨慎使用。

### modules

`modules=M1[:M2...]`，其中 `Mi` 为要压入文件系统栈的模块名。

macFUSE 用户态库支持可堆叠模块；模块可以是完整文件系统或 shim。例如可通过模块做文件名字符集转换；定制卷图标通过 `volicon` 模块实现。事实上 `volicon=PATH` 即 `modules=volicon,iconpath=PATH` 的简写。每个模块可有自有参数（`volicon` 使用 `iconpath`）。

### negative_vncache

启用内核中的**负向 vnode 名称缓存**：某名称首次 lookup 不存在时，macFUSE 会记住；之后在同名对象被创建前，再次 lookup 该名称**不会**再调用用户态。负向缓存由内核按 LRU 管理。若对象可能**在 macFUSE 不知情的情况下**出现（例如网络文件系统远端新建），**不要**启用该选项。

### noappledouble

使 macFUSE **拒绝**对 Apple Double（`._`）文件及 `.DS_Store` 的一切访问；已存在文件将表现为不存在；符合规则的新建将被禁止。

### noapplexattr

使 macFUSE **拒绝**所有以 `com.apple.` 为前缀的扩展属性。若希望屏蔽 resource fork、Finder 信息等，优先选用本项。

### nobrowse

将卷标为**不可浏览**：表示该文件系统不适合作为用户数据入口，访达不会自动进入该卷。

### nolocalcaches

禁用 unified buffer cache（UBC）、vnode 名称缓存、属性缓存与 readahead；内核**每次**操作都会回调用户态。「好处」是可能更快感知远端文件变更。

例如 sshfs：若服务器上文件被他人修改，macFUSE 无从得知。使用 `nolocalcaches` 后内核不缓存，每次操作都会进入 sshfs；sshfs 另有自身缓存，也可用 `cache=no` 关闭。若全部缓存关闭，操作将直达 SFTP，所见远端视图较新。**代价**是开销巨大、可能明显变慢；且 SFTP 无同步与锁，多客户端并发写同一文件**无一致性或顺序保证**——SFTP 只是访问远端数据的工具，不是分布式共享协议。

### norm_insensitive

与**高阶**文件系统配合使用时，`norm_insensitive` 会在 lookup 前对文件名做规范化；不同规范化形式但等价的名称视为相同。

### noubc

对整个 macFUSE 卷关闭 unified buffer cache（UBC）。

### novncache

关闭内核中的 vnode 名称缓存。

### quiet

macFUSE 用户态库运行时会核对与 macFUSE 内核扩展版本是否兼容；若不匹配会弹窗并向 Distributed Notification Center 发通知。`quiet` 可抑制此类提示。

### rdonly

`rdonly`（或 `-r`）以**只读**模式挂载 macFUSE 文件系统。

### -s

默认 macFUSE 用户态库以**多线程**运行文件系统；`-s` 可改为**单线程**模式。

### slow_statfs

默认假定 `statfs()` 足够快，macOS **无需**缓存其返回信息（如卷剩余/已用空间）。若你的实现每次 `statfs()` 都必须读盘或走网络，可使用 `slow_statfs` 减少 `statfs()` 调用次数；但访达等可能显示**过时**信息。多数情况下**不推荐**启用。

### volicon

`volicon=PATH`，其中 `PATH` 为 `.icns` 图标文件路径。

用于指定挂载卷在桌面上的图标；macFUSE 会模拟根目录 Finder 信息、模拟 `/.VolumeIcon.icns` 等以使自定义卷图标生效。实现上在库层堆叠 shim 文件系统。注意 `volicon=PATH` 等价于加载 `volicon` 模块并设置 `iconpath=PATH`（参见上文 `modules`）。

### volname

`volname=NAME`，其中 `NAME` 为字符串。

指定挂载的 macFUSE 卷名；将显示在访达与桌面上。若未指定，macFUSE 会自动生成名称，通常包含 macFUSE 设备索引与用户态文件系统名，例如 sshfs 可能被命名为 `"macFUSE Volume 0 (sshfs)"`。
