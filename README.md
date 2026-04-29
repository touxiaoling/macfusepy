面向 macFUSE 的 macfusepy
=====================

[macfusepy](https://github.com/touxiaoling/macfusepy) 是 macOS 上为 macFUSE
5.2+ 提供的 libfuse3 小型 Python 绑定。核心用 Cython 3 的纯 Python 语法
编写，链接系统中的 libfuse3 头文件与库，向应用层暴露同步、可预期的
`FUSE` 运行时和两套操作模型：路径式 `Operations` 与 inode 式
`InodeOperations`。

---

## 一、介绍说明

### 1.1 这是什么

如果你只想知道一句话：**macfusepy 让你用 Python 写 macOS 上的用户态文件
系统**。在它之前你可能听说过 `fusepy`、`pyfuse3` 这些项目，但它们要么
只服务 Linux，要么强依赖 trio 异步框架，要么停留在 FUSE 2.x。
macfusepy 重新聚焦在以下假设上：

- 平台只考虑 macOS（依赖 macFUSE 内核模块）。
- libfuse 只考虑 3.x（macFUSE 5.2+ 已经原生提供）。
- Python 只考虑 3.14+。
- 回调模型只支持同步 `def`，靠 libfuse 的多线程 session 跑并发。

收窄目标后，整个绑定层可以保持很薄：一段 Cython 核心负责请求上下文与
版本查询，一层 low-level 绑定把 libfuse 的 C 回调直接桥接到 Python，再
一层小型运行时负责把易用的“路径式”API 适配到 inode-first 的 low-level
请求上。这样既能让追求性能的人写 inode-first 后端，又能让只想做原型的
人继续用熟悉的路径接口。

### 1.2 一些可能用得上的背景

如果你完全没接触过 FUSE，下面这几句概念解释可以帮你理解后文示例：

- **FUSE**（Filesystem in Userspace）是一种允许用户态进程实现文件
  系统的机制。用户对挂载点的每次系统调用（`open`、`read`、`stat`……）都
  会被内核转发给你的进程，你回复的内容就是用户最终看到的“文件系统”。
- **macFUSE** 是 macOS 上提供 FUSE 内核扩展和 `libfuse` 用户态库的项目，
  当前主线版本 5.x 提供 libfuse 3.x 兼容头文件与库（以及 macOS 26 上
  新引入的 fskit 后端）。本项目要求 macFUSE 5.2 或更新。
- **libfuse low-level API** 把目录项以 inode（整数）为主键，回调里看到的
  是 `parent` inode、子项 `bytes` 名字和文件句柄；**high-level / path
  API** 则把这些 inode 映射成挂载点内的字符串路径。两种 API 等价但侧
  重不同：low-level 性能更好、语义更精确，path 写起来更直观。
- 一个挂载会话从调用 `FUSE(...)` 开始：进程进入 libfuse 多线程循环，直到
  挂载点被 `umount` 或回调里调用 `fuse_exit()`。期间所有逻辑都跑在你
  的 Python 进程里。

### 1.3 适合 / 不适合

适合：

- 在 mac 上做内存盘、回环目录、SFTP/对象存储/数据库代理 VFS。
- 把已有的远程协议（自家 RPC、自研 KV、git 树等）以文件树形式暴露给
  现成的 macOS 工具（Finder、命令行、Spotlight 测试等）。
- 教学、调研、做集成测试需要的“假文件系统”，希望同步代码、易调试。

不适合：

- Linux / FreeBSD / WSL（请直接用 `pyfuse3` 等成熟项目）。
- 仍要兼容 Python 2、FUSE 2.x、osxfuse 或基于 ctypes 的旧路径——这些
  代码已经从仓库中移除，不会再回来。
- 期望 trio / asyncio 原生 low-level 支持的项目；本项目公开 API 仅有
  同步回调。

---

## 二、给用户看的内容

> 这里的“用户”指准备引入 `macfusepy` 写自己文件系统的开发者，不是
> 拿到挂载点的最终用户。

### 2.1 环境要求

| 项目 | 最低版本 | 说明 |
|------|----------|------|
| 操作系统 | macOS 26.4 | Apple Silicon 与 Intel 都可以，没特殊指令依赖 |
| Python | 3.14 | 仅支持 3.14+，使用了较新的类型语法 |
| macFUSE | 5.2 | 必须包含 libfuse3 开发头文件与运行时库 |

只要你能运行 `pkg-config --cflags fuse3`，构建就基本无忧；构建脚本也
会在没有 `pkg-config` 时自动探测 `/usr/local/include/fuse3` 之类的
常见 macFUSE 安装位置。

### 2.2 安装 macFUSE 与 macfusepy

1. 安装 [macFUSE 官方包](https://macfuse.io/)。安装后通常会要求在“系统
   设置 → 隐私与安全性”里允许内核扩展，并按提示重启。重启后执行
   `pkgutil --pkgs | grep -i macfuse` 应能看到对应包。
2. 用 `uv` 安装 wheel：

   ```console
   uv add macfusepy
   ```

   或者把它写进项目 `pyproject.toml` 的依赖里。本项目按工作流约定优先
   使用 `uv`；如果你坚持用 `pip`，请自行处理隔离环境（不建议直接装到
   系统 Python）。

3. 准备一个挂载点：本质是一个空目录。例如：

   ```console
   mkdir -p /tmp/myfs
   ```

   挂载只能挂到“看起来空”的目录上，否则会失败或遮蔽原有内容。

### 2.3 两种操作模型怎么选

| 选 `Operations`（路径式） | 选 `InodeOperations`（inode 式） |
|--------------------------|--------------------------------|
| 想最快做出原型 | 想要最少的字符串与适配开销 |
| 用挂载点内路径作主键就够用 | 已有 inode 表 / 需要精确语义 |
| 不在乎 lookup/forget 谁来管 | 想自己掌控生命周期 |
| 示例：`memory.py`、`loopback.py`、`sftp.py` | 示例：本 README 第 2.5 节 |

无论选哪种，传给 `FUSE(...)` 的对象必须是 `Operations` 或
`InodeOperations` 的子类实例。运行时永远以 `InodeOperations` 为核心：
`Operations` 只是一个内部适配层，把路径请求翻译成 low-level 调用，并替
你维护 inode ↔ 路径映射、`lookup`/`forget` 计数、目录分页等。

### 2.4 包根公开 API

下面这些名字可从 `import macfusepy` 或 `from macfusepy import ...`
直接拿到，与 `tests/test_public_api.py` 锁定的 `__all__` 完全一致；
其他名字不在稳定面，可能随时调整。

| 符号 | 说明 |
|------|------|
| `FUSE` | 挂载入口；构造即阻塞，直到会话结束 |
| `Operations` | 路径式操作基类 |
| `InodeOperations` | inode 式操作基类 |
| `LoggingMixIn` | 可混入以打印调用的操作名与参数，调试友好 |
| `FuseOSError` | 抛出 errno 整数（例如 `errno.ENOENT`），运行时会转成负 errno 返回内核 |
| `LowLevelAttr` | inode 接口的 stat 结果包装（不可变 `Mapping[str,int]`） |
| `LowLevelEntry` | inode 接口的 lookup / readdir 返回项 |
| `Config` / `ConnectionInfo` / `FileInfo` / `IoctlData` | 与 libfuse 结构对应的轻量 Python 包装 |
| `fuse_exit` | 在回调中调用以请求退出 fuse 循环 |
| `fuse_get_context` | 当前请求的 `(uid, gid, pid)` 三元组 |
| `libfuse_version` | 运行时链接的 libfuse 版本 |

`macfusepy.operations` 子模块还导出 `DirEntry`、`TimespecPair` 等类型
别名，供进阶用法和类型标注使用；它们不在包根 `__all__` 中，按需从该
子模块显式导入。

### 2.5 完整可运行示例

下面两段代码都可以保存为单文件，`uv run python <file>.py /tmp/myfs`
直接运行。运行时进程会前台阻塞，按 `Ctrl-C` 或在另一个终端
`umount /tmp/myfs` 即可结束。

#### 2.5.1 路径式：一个能读写的极简内存盘

```python
import errno
import logging
from stat import S_IFDIR, S_IFREG
from time import time_ns

from macfusepy import FUSE, FuseOSError, LoggingMixIn, Operations


class TinyMemoryFS(LoggingMixIn, Operations):
    """挂载后能在根目录下创建、读取、写入、删除文件的最小实现。"""

    def __init__(self) -> None:
        now = time_ns()
        self._dir_attrs: dict[str, int] = {
            "st_mode": S_IFDIR | 0o755,
            "st_nlink": 2,
            "st_ctime": now,
            "st_mtime": now,
            "st_atime": now,
        }
        self._files: dict[str, dict[str, int]] = {}
        self._data: dict[str, bytes] = {}
        self._next_fh = 0

    def getattr(self, path, fh=None):
        if path == "/":
            return dict(self._dir_attrs)
        if path in self._files:
            return dict(self._files[path])
        raise FuseOSError(errno.ENOENT)

    def readdir(self, path, fh, flags=0):
        if path != "/":
            raise FuseOSError(errno.ENOTDIR)
        return [".", ".."] + [name.lstrip("/") for name in self._files]

    def create(self, path, mode, fi=None):
        now = time_ns()
        self._files[path] = {
            "st_mode": S_IFREG | mode,
            "st_nlink": 1,
            "st_size": 0,
            "st_ctime": now,
            "st_mtime": now,
            "st_atime": now,
        }
        self._data[path] = b""
        self._next_fh += 1
        return self._next_fh

    def open(self, path, flags):
        if path not in self._files:
            raise FuseOSError(errno.ENOENT)
        self._next_fh += 1
        return self._next_fh

    def read(self, path, size, offset, fh):
        return self._data.get(path, b"")[offset : offset + size]

    def write(self, path, data, offset, fh):
        current = self._data.get(path, b"")
        merged = current[:offset].ljust(offset, b"\x00") + data + current[offset + len(data) :]
        self._data[path] = merged
        self._files[path]["st_size"] = len(merged)
        self._files[path]["st_mtime"] = time_ns()
        return len(data)

    def truncate(self, path, length, fh=None):
        current = self._data.get(path, b"")
        self._data[path] = current[:length].ljust(length, b"\x00")
        self._files[path]["st_size"] = length

    def unlink(self, path):
        self._files.pop(path, None)
        self._data.pop(path, None)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("mount", help="一个空目录，例如 /tmp/myfs")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG)
    FUSE(TinyMemoryFS(), args.mount, foreground=True, allow_other=False)
```

把上面这个文件挂起来后，可以试试：

```console
$ ls /tmp/myfs              # 空
$ echo hello > /tmp/myfs/a  # 触发 create + write
$ cat /tmp/myfs/a           # 触发 open + read + release
hello
$ rm /tmp/myfs/a            # 触发 unlink
```

每个动作都会在挂载进程里产生 `LoggingMixIn` 的调试日志，可以借此观察
内核到底先后调了哪些回调。

#### 2.5.2 inode 式：相同功能的 low-level 写法

```python
import errno
import logging
from stat import S_IFDIR, S_IFREG
from time import time_ns

from macfusepy import (
    FUSE,
    FuseOSError,
    InodeOperations,
    LowLevelAttr,
    LowLevelEntry,
)


ROOT = 1


class TinyInodeFS(InodeOperations):
    """与上面 TinyMemoryFS 等价，但走 libfuse low-level 接口。"""

    def __init__(self) -> None:
        now = time_ns()
        self._next_ino = ROOT + 1
        self._attrs: dict[int, dict[str, int]] = {
            ROOT: dict(
                st_ino=ROOT,
                st_mode=S_IFDIR | 0o755,
                st_nlink=2,
                st_ctime=now,
                st_mtime=now,
                st_atime=now,
            ),
        }
        self._name_to_ino: dict[bytes, int] = {}
        self._ino_to_name: dict[int, bytes] = {}
        self._data: dict[int, bytes] = {}

    def _attr(self, ino: int) -> LowLevelAttr:
        return LowLevelAttr(**self._attrs[ino])

    def lookup(self, parent, name):
        if parent != ROOT:
            raise FuseOSError(errno.ENOENT)
        ino = self._name_to_ino.get(name)
        if ino is None:
            raise FuseOSError(errno.ENOENT)
        return LowLevelEntry(name, ino, self._attr(ino), ino)

    def getattr(self, ino, fh=None):
        if ino not in self._attrs:
            raise FuseOSError(errno.ENOENT)
        return self._attr(ino)

    def readdir(self, ino, offset, size, fh, flags=0):
        if ino != ROOT:
            raise FuseOSError(errno.ENOTDIR)
        entries = list(self._name_to_ino.items())
        return [
            LowLevelEntry(name, child, self._attr(child), index + 1)
            for index, (name, child) in enumerate(entries[int(offset) :], int(offset))
        ]

    def create(self, parent, name, mode, flags, fi):
        if parent != ROOT:
            raise FuseOSError(errno.ENOTDIR)
        if name in self._name_to_ino:
            raise FuseOSError(errno.EEXIST)
        now = time_ns()
        ino = self._next_ino
        self._next_ino += 1
        self._attrs[ino] = dict(
            st_ino=ino,
            st_mode=S_IFREG | mode,
            st_nlink=1,
            st_size=0,
            st_ctime=now,
            st_mtime=now,
            st_atime=now,
        )
        self._name_to_ino[name] = ino
        self._ino_to_name[ino] = name
        self._data[ino] = b""
        entry = LowLevelEntry(name, ino, self._attr(ino), ino)
        return entry, ino

    def open(self, ino, flags, fi=None):
        return ino

    def read(self, ino, size, offset, fh):
        return self._data.get(ino, b"")[offset : offset + size]

    def write(self, ino, data, offset, fh):
        current = self._data.get(ino, b"")
        merged = (
            current[:offset].ljust(offset, b"\x00")
            + data
            + current[offset + len(data) :]
        )
        self._data[ino] = merged
        self._attrs[ino]["st_size"] = len(merged)
        self._attrs[ino]["st_mtime"] = time_ns()
        return len(data)

    def setattr(self, ino, attrs, to_set, fh=None):
        if ino not in self._attrs:
            raise FuseOSError(errno.ENOENT)
        if "st_size" in attrs:
            length = int(attrs["st_size"])
            current = self._data.get(ino, b"")
            self._data[ino] = current[:length].ljust(length, b"\x00")
            self._attrs[ino]["st_size"] = length
        for key in ("st_mode", "st_uid", "st_gid", "st_atime", "st_mtime"):
            if key in attrs:
                self._attrs[ino][key] = int(attrs[key])
        return self._attr(ino)

    def unlink(self, parent, name):
        if parent != ROOT:
            raise FuseOSError(errno.ENOTDIR)
        ino = self._name_to_ino.pop(name, None)
        if ino is None:
            raise FuseOSError(errno.ENOENT)
        self._ino_to_name.pop(ino, None)
        self._attrs.pop(ino, None)
        self._data.pop(ino, None)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("mount")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG)
    FUSE(TinyInodeFS(), args.mount, foreground=True)
```

两段代码功能等价，但 inode 版本完全不需要拼接路径字符串，所有索引都
是整数键，更适合后端本来就用 inode/对象 ID 寻址的场景。

### 2.6 `FUSE` 构造函数详解

签名（位置参数和最常用的关键字参数）：

```text
FUSE(operations, mountpoint, raw_fi=False, encoding="utf-8", **kwargs)
```

| 参数 | 含义 |
|------|------|
| `operations` | `Operations` 或 `InodeOperations` 实例 |
| `mountpoint` | 挂载点路径（必须存在且可挂载） |
| `raw_fi` | 为 `True` 时，路径层 `create`/`open`/`opendir` 等会与 `FileInfo` 对象交互，能拿到 `flags`、`fh`、`direct_io` 等字段 |
| `encoding` | 路径与文件名字符串的编解码（路径式适配器在内核 ↔ Python 之间转码时使用） |

下列关键字由 `FUSE` 自身解释，不会原样作为未知 fuse 选项传给底层：

| 关键字 | 作用 |
|--------|------|
| `attr_timeout` / `entry_timeout` | 属性 / 目录项缓存超时（秒，浮点），默认 `1.0`，传给 low-level 会话 |
| `kernel_permissions` | 为 `True` 时启用 libfuse 的 `default_permissions`：内核按 inode 做权限检查；此时 `access` 不会被注册 |
| `disabled_operations` | 一组操作名字符串，额外禁用对应 low-level 回调（与内部禁用集合 `getlk` / `setlk` / `bmap` 合并） |
| `threads` / `nothreads` | 不再支持单线程模式；传 `threads=False` 或 `nothreads=True` 直接抛 `ValueError` |
| `foreground` / `debug` | 当前被静默接受但忽略：运行时永远以前台、多线程方式运行；`debug` 暂未接通 libfuse 调试日志 |

剩下的 `**kwargs` 会按 libfuse 挂载选项规则传给底层会话：布尔
`True` 展开为选项名，否则按 `name=value` 写入（与
`FUSE._normalize_fuse_options` 行为一致）。常见例子：

| 选项 | 用途 |
|------|------|
| `allow_other=True` | 允许其他用户访问挂载点（macOS 上常用，需 macFUSE 配置允许） |
| `fsname="myfs"` | 在 `mount` 输出与 Finder 中显示的卷名；不传时默认取 operations 的类名 |
| `volname="My FS"` | macFUSE 自定义卷标 |
| `local=True` | 提示 macOS 把卷视作本地卷 |
| `backend="fskit"` | macFUSE 5.2+ 的 fskit 后端选择（仅在你确实想用 fskit 时再加） |
| `ro=True` | 只读挂载 |

具体可用选项以本机 `man mount_macfuse` / macFUSE 文档为准。`encoding`
之外的所有路径都假设为 UTF-8；如果你的后端使用别的编码，建议显式
设置以避免错位。

### 2.7 错误、时间戳、libfuse3 签名

- **抛错**：失败要 `raise FuseOSError(errno_value)`，例如
  `FuseOSError(errno.ENOENT)`。**不要**直接返回负 errno；运行时只承认
  异常这一种通道。
- **时间戳**：所有示例都使用纳秒整数（`time.time_ns()` /
  `os.stat_result.st_atime_ns` 等）。不要混用浮点秒，否则在精度敏感的
  应用里会出现舍入错位。
- **libfuse3 签名**：`getattr`、`chmod`、`chown`、`truncate`、
  `utimens`、`rename` 等都和 libfuse3 一致，多数会带文件句柄或
  flags 参数。如果你从老的 fusepy / fuse 2.x 迁移过来，请按当前
  类定义重新对齐参数。
- **路径 vs inode**：路径 API 里的 `path` 一定是挂载点内绝对路径
  （以 `/` 开头），inode API 里的名字是 `bytes`。两者各自的语义不要
  互相借用。

### 2.8 并发与线程安全

运行时只使用多线程 low-level session（`fuse_session_loop_mt`）：多个
请求可能**同时进入**你的 `Operations` / `InodeOperations` 方法。

- 共享可变状态（字典、缓存、连接池等）必须自己加锁或使用线程安全
  结构。绑定层不会替你串行化业务逻辑。
- 如果你的后端本身是单线程的（例如 Paramiko 单连接），请像
  `examples/sftp.py` 那样用 `threading.Lock` 把每个回调串成临界区，
  或者改用连接池。
- 不要假设 `lookup` → `getattr` → `read` → `release` 一定按这种顺序、
  在同一线程上发生；它们可能交错。

### 2.9 macFUSE 平台限制

- macFUSE VFS 当前不支持 Linux 侧常见的 POSIX `GETLK` / `SETLK` /
  `SETLKW` 以及 `BMAP`。`InodeOperations` 上的 `getlk`、`setlk`、
  `bmap` 仅作为签名占位存在，运行时不会注册这些 low-level 回调。
  路径 API 中的 `lock` 仅在对端仍下发 BSD `flock` 语义时可能有关；
  跨机锁需在应用协议层自己实现。
- 需要细粒度权限模型（动态 ACL、远端权限查询等）时，**勿与**
  `kernel_permissions=True` 叠加：内核已替你裁决，`access` 也不再
  生效。
- 自定义 `ioctl`：`examples/ioctl.py` 里的 `_IOWR('M', 1, uint32_t)`
  在当前 macFUSE 5.2 真实挂载路径上不会被高层 `ioctl` 回调收到，相关
  集成测试以 xfail 记录该行为；这块只能当作接口示例。

### 2.10 卸载与排查

- 正常停止：在另一个终端 `umount /path/to/mount`。
- 强制卸载（macOS）：`/usr/sbin/diskutil unmount force /path/to/mount`。
- 测试时如果挂载子进程异常残留，可设置环境变量
  `macfusepy_TEST_DEBUG=1`，框架在 teardown 中会输出更多挂载/卸载
  细节。
- 能 `mount` 看到自己的卷但 `ls` 立刻报错时，先回去看挂载进程的日志：
  通常是 `getattr` 没返回 `st_mode` 或某次抛了未捕获异常。
- 想从挂载进程内部主动退出时调用 `fuse_exit()`，配合外层 `umount`
  使用更稳妥。

### 2.11 仓库内更多示例

| 文件 | 内容 |
|------|------|
| `examples/memory.py` | 完整内存单层文件系统，演示路径式 API 与并发说明 |
| `examples/loopback.py` | 把一个真实目录“映射”成 FUSE 文件系统，逐个回调讲解如何转译到 `os` 调用 |
| `examples/ioctl.py` | `ioctl` 请求处理示例（包含 `_IOWR` 编码和 `IoctlData` 用法） |
| `examples/sftp.py` | 同步 SFTP 后端示例，展示如何用单连接 + Lock 适配同步 FUSE 热路径 |
| `examples/context.py` | `fuse_get_context` 与请求上下文，三个伪文件 `/uid` `/gid` `/pid` |

运行示例前需要先完成下文「开发与构建」中的 `build_ext --inplace`，并
准备好挂载点与 macFUSE。

---

## 三、给开发者看的内容

> 这里的“开发者”指要修改 `macfusepy` 自身、或者深入理解其内部以排查
> 行为差异的人。

### 3.1 从源码构建与本地开发

克隆仓库后：

```console
uv sync
uv run python setup.py build_ext --inplace
```

- `uv sync`：安装构建依赖（Cython、setuptools 等）与开发依赖
  （pytest 等）。
- `build_ext --inplace`：在当前工作树内编译 `macfusepy._core` /
  `macfusepy._lowlevel` 等扩展；任何会导入这些模块的测试或示例都需要
  先完成这一步。修改 `.pyx`、`.pxd` 或 `setup.py` 后请重新执行。

### 3.2 运行测试

```console
uv run pytest
```

- 基准测试默认跳过；仅跑性能基准用：

  ```console
  uv run pytest --run-benchmarks -m benchmark tests/test_benchmarks.py
  ```

- 部分用例会真实挂载文件系统并在 teardown 中执行 `/sbin/umount`、
  `/usr/sbin/diskutil unmount force` 等，需要可用的 macFUSE。
- 调试挂载子进程时可设置 `macfusepy_TEST_DEBUG=1`。
- 公共 API 改动需同步更新 `tests/test_public_api.py` 里锁定的
  `__all__`。

### 3.3 仓库结构

| 路径 | 作用 |
|------|------|
| `macfusepy/_core.py` | 极薄 Cython 纯 Python 扩展：保留 libfuse 请求上下文、`fuse_exit`、版本查询 |
| `macfusepy/_lowlevel.py` | 绑定 libfuse low-level API，创建 session、处理请求并调用 `fuse_reply_*` 回复 |
| `macfusepy/_runtime.py` | 公开 `FUSE` 运行时；以 `InodeOperations` 为核心，把路径式 `Operations` 适配到 inode 请求 |
| `macfusepy/fuse3.pxd` | libfuse3 C API 的 Cython 声明 |
| `macfusepy/inode_operations.py` | `InodeOperations` 基类 |
| `macfusepy/path_operations.py` | 路径式 `Operations` 基类、`LoggingMixIn`、相关类型别名 |
| `macfusepy/operations.py` | 兼容导入面，重新导出上面两组 |
| `macfusepy/lowlevel_async.py` | low-level 支撑（内部）；`LowLevelAttr`、`LowLevelEntry` 通过包根导出 |
| `macfusepy/types.py` | `Config`、`ConnectionInfo`、`FileInfo`、`IoctlData` 等轻量包装 |
| `macfusepy/errors.py` | `FuseOSError` |
| `examples/` | 路径式示例文件系统集合 |
| `tests/` | pytest 用例，覆盖公共 API 行为、运行时、示例与基准 |

### 3.4 公开约定与边界

- 公开 API 仅同步回调（普通 `def`）。**不要**为用户暴露异步操作兼容
  层，也不要把 `_lowlevel.py` 或整个 `lowlevel_async.py` 当作稳定公共
  API 导出；只通过包根暴露经过测试的轻量 low-level 类型。
- `InodeOperations` 是一等核心接口，性能敏感路径优先走 inode；
  `Operations` 只是易用层适配，由运行时维护 lookup/forget、inode 生命
  周期、目录分页和请求回复状态。
- 操作签名应遵循 libfuse3/macFUSE 5.2+ 行为，包括 libfuse3 提供的文件
  句柄和 flags 参数。围绕 Cython 边界做聚焦修改，更新单个操作或
  结构体映射时避免大范围重构。
- 公开模型当前建立在 libfuse low-level session 之上：low-level 回调
  同步执行用户方法并立即用 `fuse_reply_*` 回复。
- 文档与代码注释使用中文；shell 命令、上游 API 名称、错误字符串、
  协议术语等保留原文更清晰时可保留原文。

### 3.5 PR 与变更建议

- 改公共 API：先看 `tests/test_public_api.py` 决定是不是真的要改，并
  在 PR 里说明影响。
- 改 low-level：尽量本地跑 `uv run pytest tests/test_runtime.py
  tests/test_mounted_runtime.py`，再视情况加挂载用例。
- 性能敏感路径修改：跑一次 `--run-benchmarks` 防止回退。
- 与 libfuse 直接相关的字段添加：同步更新 `fuse3.pxd` 和 `_lowlevel.py`，
  注意保持 Cython 端类型与 libfuse 头一致。

---

## 四、其他

- 项目许可证：见 `pyproject.toml`，当前为 ISC。
- 项目主页与作者：[https://github.com/touxiaoling/macfusepy](https://github.com/touxiaoling/macfusepy)。
- 历史与设计参考：如果你想了解曾经基于 trio 的 low-level 异步设计，
  可以阅读其它项目（例如 `pyfuse3`）；本项目公开 API 仅支持同步回调
  模型，未来也不会回到异步 low-level。
- 命名说明：`macfusepy` 与历史上的 `fusepy`、`pyfuse3` 没有继承关系，
  仅在 API 形态上有部分相似，迁移时请按本 README 与示例为准，不要照
  搬旧文档。
