# macFUSE 与 libfuse3：Cython 绑定速查（相对 Linux）

面向在 **macOS** 上用 **Cython 纯 Python 语法**（`.py` 写逻辑 + `cimport`，`.pxd` 声明 libfuse3 C API，由构建配置编译）绑定 **libfuse3** 的开发者。对比对象是 **Linux 上的上游 libfuse3**；**仅考虑 macFUSE 默认的 VFS（内核扩展）路径**，不涉及 FSKit。时间范围：**当前代** macFUSE（如 5.x，与本仓库一致的 **5.2+**）及其自带的 **libfuse 3**。

---

## 1. 构建与链接（和 Linux 不一样的地方）

- **头文件与库**：以本机安装的 macFUSE 为准，常见路径包括 `/Library/Filesystems/macfuse.fs/Contents/Resources/include/fuse3`、`/opt/homebrew/include/fuse3`、`/usr/local/include/fuse3`；可用 `pkg-config fuse3` 取 flags。不要假设与某一 Linux 发行版自带的 `libfuse.so` 二进制兼容。
- **链接名**：一般为 `-lfuse3`（与 Linux 一致的是 API 名，不是 `.so` 路径）。
- **`FUSE_USE_VERSION`**：在编译参数里与 macFUSE 附带的 `fuse_lowlevel.h` 等保持一致；升级 macFUSE 后应**重编扩展**并核对 `fuse_lowlevel_ops` 等结构体是否与头文件同步。
- **运行时**：终端用户必须安装 **macFUSE**；分发物应写清最低 macFUSE 版本，而不是泛泛写「libfuse3」。

---

## 2. 权限与访问控制（默认行为与 Linux 很不同）

- **默认**：卷**只对挂载用户**开放；**其他用户含 root** 默认不能访问别人的卷（防用户态 FS 异常拖死系统组件）。
- **`allow_other`**：放开为「像普通卷一样」仍会做权限检查；属**特权选项**，仅 **root** 或 **macFUSE admin group** 成员可用。admin group ID：`sysctl vfs.generic.macfuse.tunables.admin_group`（root 可 `sysctl -w` 改）。与 Linux 上 `user_allow_other` 那套**不等价**。
- **`allow_root`**：类似 `allow_other`，但「其他用户」只含 root；同样需要 admin group 或 root。
- **`default_permissions`**：内核更多根据 inode 上可见的权限位做判断（与「是否实现 access」等组合有关）。
- **`defer_permissions`**：假定允许访问，把决定权交给用户态/远端（例如远端 UID/GID 与本地不一致的网络 FS）；常与 sshfs 类场景一起讨论。

---

## 3. 超时、线程与 I/O 块

- **`daemon_timeout=N`（秒）**：用户态长时间不答，内核会保护；**默认约 60 秒**，超时后卷可能被**自动卸载**（数据可能丢）。长 RPC 必须在绑定层拆分、异步化或调大 N。
- **`-s`**：用户态库**默认多线程**调 FS；`-s` 改为**单线程**。与 GIL、回调里是否线程安全一致。
- **`iosize=N`**：卷上默认 I/O 块大小（字节），须为 **2 的幂**。**默认 64 KiB**。**最小**：Apple Silicon **16384**，Intel **4096**；**最大 32 MiB**。慢链路可偏小，快链路可偏大。
- **`direct_io`**：走直通 I/O，**绕过 UBC**，**不能用 mmap**；非必要别开。
- **`slow_statfs`**：`statfs` 很慢时减少调用次数，但访达等可能显示**过时**卷空间信息；一般不必开。

---

## 4. 缓存与一致性（mac 上选项多、语义细）

- **`auto_cache`**：除大小变化外，还在 `getattr`/`open` 里看 mtime 变化以丢缓存；**默认关**，需显式开。
- **`nolocalcaches`**：关 UBC、vnode 名缓存、属性缓存与 readahead；每次尽量进用户态，易感知远端变更，**很慢**。
- **`noubc` / `novncache` / `negative_vncache`**：分别关 UBC、关 vnode 名缓存、开负向名缓存（lookup 失败会被内核记住；远端可能悄悄创建同名文件时**不要**开负向缓存）。
- **`fair_locking`**：公平锁，高压下延迟更均匀，略损性能。

---

## 5. 扩展属性与 Apple 元数据

- **默认**：xattr（含 Finder Info、Resource Fork、ACL 等）会先问用户态；若某类未实现，库会记住并可能改用 **Apple Double（`._` 文件）**。
- **`auto_xattr`**：内核**始终**用 `._`，不再把 xattr 请求转发给用户态。
- **`noappledouble`**：拒绝 `._` 与 `.DS_Store`（表现为不存在、禁止新建符合规则的）。
- **`noapplexattr`**：拒绝所有 `com.apple.*` 前缀的 xattr。
- **`extended_security`**：为该卷启用 ACL；用户态需正确处理 xattr `com.apple.system.Security`（别把 ACL 只放在可篡改的 `._` 里当正经安全方案）。

---

## 6. 卷外观、路径与其它挂载选项

- **`volname=NAME`**：访达/桌面显示的卷名；不设则库自动生成（常含 macFUSE 卷序号与进程名）。
- **`volicon=PATH`**：`.icns` 卷图标；等价于 `modules=volicon,iconpath=PATH`。
- **`modules=M1[:M2…]`**：用户态可堆叠模块（shim/转码/图标等）；`volicon=…` 是其中一种简写。
- **`fsname=NAME`**：类似设备名的逻辑名，会出现在 `mount` 输出里；与**卷重命名**、**程序卸载**等组合时需注意文档要求（如设备路径语义）。
- **`fssubtype=N`**：子类型，供访达「格式」描述用，依赖 `macfuse.fs` 里登记的 subtype。
- **`fstypename=NAME`**：最多 **6** 字符，内核类型为 `macfuse_NAME`；磁盘上 bundle 命名等副作用大，慎用。
- **`fsid=N`**：**24 位**整数（`0` 与 `0xFFFFFF` 无效），用于稳定文件系统 ID（如别名场景）。
- **`local`**：把卷标为**本地**；访达行为更激进，**文档称实验性**。
- **`nobrowse`**：卷标为不可浏览，访达不自动进卷。
- **`jail_symlinks`**：绝对符号链接前加挂载点前缀，限制在卷内。
- **`allow_recursion`**：允许在**已位于 macFUSE 卷内**的目录上再挂 macFUSE（默认禁，防卸载问题）。
- **`quiet`**：抑制用户态库与内核扩展版本不匹配时的弹窗/通知。
- **`rdonly` / `-r`**：只读；**`-f` / `debug`**：前台 + 调试打印。

---

## 7. 文件名与 Unicode（Finder 与长度）

- **NFC 形式**文件名总长上限 **255 字节**（与 APFS 类似）。
- **访达偏好 NFD**；向 macFUSE 报目录项名字时**优先用 NFD**，可减少显示异常。
- **`readdir` 可返回更长名**（文档允许至 **1024 字节**）以容纳长 NFD，但 **NFC 仍须满足 255 字节**。
- **`norm_insensitive`**：与高阶栈配合时，lookup 前做规范化，等价 NFC 的不同形式可视为同名。

---

## 8. FUSE 内核消息：支持 / 不支持 / mac 专有

macFUSE 支持 **FUSE ABI 7.8–7.19** 范围内的一部分消息（以本机内核与用户态库为准）。

**已实现的标准类操作（与绑定相关的常见集合）**  
`LOOKUP`、`FORGET`、`GETATTR`、`SETATTR`、`READLINK`、`SYMLINK`、`MKNOD`、`MKDIR`、`UNLINK`、`RMDIR`、`RENAME`、`LINK`、`OPEN`、`READ`、`WRITE`、`STATFS`、`RELEASE`、`FSYNC`、`SETXATTR`、`GETXATTR`、`LISTXATTR`、`REMOVEXATTR`、`FLUSH`、`INIT`、`OPENDIR`、`READDIR`、`RELEASEDIR`、`FSYNCDIR`、`ACCESS`、`CREATE`、`INTERRUPT`、`DESTROY`、`IOCTL`、`FALLOCATE`。

**macOS 侧额外消息**  
`SETVOLNAME`；`GETXTIMES`、`EXCHANGE` 在文档中为 **deprecated**（新逻辑应用 `renamex` 风格与下节能力位）。

**当前不支持（勿按 Linux 假定已实现）**  
`GETLK`、`SETLK`、`SETLKW`、`BMAP`、`POLL`、`NOTIFY_REPLY`、`BATCH_FORGET`。

**通知（notify）**  
支持：`INVAL_INODE`、`INVAL_ENTRY`、`DELETE`。  
不支持：`POLL`、`STORE`、`RETRIEVE`（不要依赖 `notify_store` 等 Linux 优化路径）。

---

## 9. `fuse_conn_info`：相对 Linux 多出来的能力位（`want`）

在 **`init`** 里只对 **`conn.capable`** 里有的位设 **`conn.want`**。macFUSE 常见扩展含义如下（名称与头文件宏一致）：

| 能力 | 含义摘要 |
|------|----------|
| `FUSE_CAP_ATOMIC_O_TRUNC` | 支持 `open` 的 `O_TRUNC`。 |
| `FUSE_CAP_XTIMES` | 扩展时间回调；可暴露 **crtime / bkptime** 等。 |
| `FUSE_CAP_CASE_INSENSITIVE` | 声明卷为大小写不敏感（默认 macFUSE 卷为大小写敏感）。 |
| `FUSE_CAP_NODE_RWLOCK` | 声明对同一 inode 的实现在多线程下安全；否则同结点操作可能串行。 |
| `FUSE_CAP_ALLOCATE` | 实现 `fallocate`；与 macOS **`fcntl` `F_PREALLOCATE`** 语义相关。 |
| `FUSE_CAP_EXCHANGE_DATA` | 旧 **`exchangedata(2)`** 路径；**已弃用**，macFUSE 在 **macOS 11+** 不再提供；应改用 **`FUSE_CAP_RENAME_SWAP`** + `renamex_np` 风格。 |
| `FUSE_CAP_RENAME_SWAP` | `rename` 带交换（`FUSE_RENAME_SWAP`）。 |
| `FUSE_CAP_RENAME_EXCL` | 独占创建式重命名（`FUSE_RENAME_EXCL`）。 |
| `FUSE_CAP_VOL_RENAME` | 重命名**已挂载卷**；与 `fsname` 等配合时常要求**设备路径**语义。 |
| `FUSE_CAP_ACCESS_EXTENDED` | `access` 可使用扩展模式位（读/写/执行/删目录项/追加/删文件/读写属性与 xattr/权限/chown 等细粒度位，见头文件注释）。 |

纯 Python 语法下对 `fuse_conn_info` 字段多为 **点号访问**，例如 `conn.want |= ...`，并与 `conn.capable` 按位与后再置位。

---

## 10. VFS 后端（本文唯一假设）

libfuse3 会话、`fuse_req_ctx`、`fuse_lowlevel_notify_*` 以及上列挂载选项，均针对 **内核扩展 + VFS** 路径。用户机器上需完成 **第三方内核扩展** 的信任与授权（Apple 芯片常见：恢复环境中允许用户管理内核扩展，再在系统设置里批准 Benjamin Fleischer / macFUSE）。

---

## 11. 从 Linux 迁到 macFUSE 的最短检查单

1. `.py` / `.pxd` / `FUSE_USE_VERSION` / 头文件路径与 **macFUSE 版本**锁死；升级 macFUSE 必重编。  
2. 删除或禁用 **lock / bmap / poll / batch_forget / notify_reply**；notify 只用 **INVAL_*** / **DELETE**。  
3. 按业务设置 **§9** 能力位；**不要**再依赖 **exchange / exchangedata** 能力。  
4. 按 **§2** 设计多用户与 **`allow_other`**；勿假设 root 总能进卷。  
5. 按 **§3** 处理 **daemon_timeout** 与线程模型 **`-s`**。  
6. 按 **§7** 处理 **NFD/NFC** 与长度。  
7. 在 mac 上实测 **xattr、访达、大文件 + iosize**（**§4–§6**）。

---

## 12. 许可（绑定工程常问一句）

动态或静态链接 **`libfuse.dylib`** 须遵守其 **LGPL** 义务。内核扩展与整体产品的商业授权以 **macFUSE 官方 `LICENSE`** 与安装包说明为准；与「仅引用头文件写开源绑定」的合规边界不同时请咨询法务。

以上均为对 macFUSE 公开文档与行为的**压缩速查**；若与**本机已安装版本**的头文件或 `mount_macfuse` 帮助不一致，以本机为准。
