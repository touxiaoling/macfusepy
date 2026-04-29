#!/usr/bin/env python3

import logging

from collections import defaultdict
from collections.abc import Iterable
from errno import EEXIST, EINVAL, EISDIR, ENOATTR, ENOENT, ENOTDIR, ENOTEMPTY
from stat import S_IFDIR, S_IFLNK, S_IFREG, S_ISDIR
from time import time_ns

from macfusepy import FUSE, FuseOSError, Operations, LoggingMixIn


class Memory(LoggingMixIn, Operations):
    """一个最小的内存文件系统。

    这个示例把所有元数据保存在 ``self.files``，把普通文件内容保存在
    ``self.data``，把符号链接目标保存在 ``self.links``。路径以绝对路径字符串作为键，
    目录关系在需要时从路径前缀推导出来，让新用户看清楚常见 FUSE 回调如何配合：
    ``getattr`` 提供 stat 信息，``readdir`` 列出目录项，``read``/``write`` 按偏移读写字节。

    注意事项:
        真实文件系统通常还需要处理并发访问、权限校验、持久化存储和更完整的错误处理。
        运行时会并行调用回调；生产实现应为共享内存状态加锁或改用 inode-first 设计。
    """

    def __init__(self):
        """初始化内存中的目录树。

        ``self.files`` 的键是挂载点内路径，值是返回给 ``getattr`` 的 stat 字段。
        ``self.data`` 保存普通文件内容，``self.links`` 保存符号链接的目标字符串。
        ``self.fd`` 只是演示文件句柄如何在 ``open``/``create`` 后传回后续回调；
        它不是宿主机的真实文件描述符。
        """
        self.files = {}
        self.data: defaultdict[str, bytes] = defaultdict(bytes)
        self.links: dict[str, str] = {}
        self.fd = 0
        now = time_ns()
        self.files["/"] = dict(
            st_mode=(S_IFDIR | 0o755),
            st_ctime=now,
            st_mtime=now,
            st_atime=now,
            st_nlink=2,
        )

    def _parent(self, path):
        parent, _, _ = path.rstrip("/").rpartition("/")
        return parent or "/"

    def _is_dir(self, path):
        return S_ISDIR(self.files[path]["st_mode"])

    def _require_parent_dir(self, path):
        parent = self._parent(path)
        if parent not in self.files:
            raise FuseOSError(ENOENT)
        if not self._is_dir(parent):
            raise FuseOSError(ENOTDIR)
        return parent

    def _require_dir(self, path):
        if path not in self.files:
            raise FuseOSError(ENOENT)
        if not self._is_dir(path):
            raise FuseOSError(ENOTDIR)

    def _is_descendant(self, parent, path):
        return path.startswith(parent.rstrip("/") + "/")

    def _direct_child_name(self, parent, path):
        if path == parent:
            return None
        if parent == "/":
            relative = path[1:]
        else:
            prefix = parent.rstrip("/") + "/"
            if not path.startswith(prefix):
                return None
            relative = path[len(prefix) :]
        if not relative or "/" in relative:
            return None
        return relative

    def _children(self, path):
        return [
            child
            for current in self.files
            if (child := self._direct_child_name(path, current)) is not None
        ]

    def _remove_entry(self, path):
        if self._is_dir(path):
            self.files[self._parent(path)]["st_nlink"] -= 1
        self.data.pop(path, None)
        self.links.pop(path, None)
        self.files.pop(path)

    def chmod(self, path, mode, fh=None):
        """修改文件权限位。

        FUSE 在用户执行 ``chmod`` 或应用调用 ``chmod(2)`` 时调用它。``mode`` 包含
        新权限位；这里保留原来的文件类型位，只替换权限位。真实实现还要检查调用者
        是否有权限修改，并在只读文件系统中抛出 ``EROFS``。
        """
        self.files[path]["st_mode"] &= 0o770000
        self.files[path]["st_mode"] |= mode
        return 0

    def chown(self, path, uid, gid, fh=None):
        """修改文件所有者和所属组。

        ``uid`` 或 ``gid`` 可能为 ``-1``，表示那一项不需要修改。这个示例直接保存
        传入值，方便观察回调效果；真实文件系统需要处理权限、用户映射以及只修改其中
        一项的情况。
        """
        self.files[path]["st_uid"] = uid
        self.files[path]["st_gid"] = gid

    def create(self, path, mode, fi=None):
        """创建普通文件并返回一个文件句柄。

        当用户以会创建文件的方式打开路径，例如 ``open("x", "w")``，libfuse 会调用
        ``create``。这里同时创建元数据和空内容，然后返回递增的整数句柄。后续
        ``read``、``write``、``flush``、``release`` 会收到这个句柄，所以真实实现
        通常会在这里打开底层资源并保存或返回它。
        """
        if path in self.files:
            raise FuseOSError(EEXIST)
        self._require_parent_dir(path)

        now = time_ns()
        self.files[path] = dict(
            st_mode=(S_IFREG | mode),
            st_nlink=1,
            st_size=0,
            st_ctime=now,
            st_mtime=now,
            st_atime=now,
        )
        self.data[path] = b""

        self.fd += 1
        return self.fd

    def getattr(self, path, fh=None):
        """返回路径的 stat 元数据。

        这是任何 FUSE 文件系统都必须认真实现的核心回调之一。内核会频繁调用它来判断
        路径是否存在、是文件还是目录、大小是多少、时间戳是什么。返回值至少要包含
        ``st_mode`` 和 ``st_nlink``；普通文件还应提供 ``st_size``。找不到路径时必须
        抛出 ``ENOENT``，否则内核会以为文件存在。
        """
        if path not in self.files:
            raise FuseOSError(ENOENT)

        return dict(self.files[path])

    def getxattr(self, path, name, position):
        """读取扩展属性值。

        macOS 会用扩展属性保存 Finder 标签、隔离标记等元数据。这里把属性字典存在
        ``self.files[path]["attrs"]`` 里；属性不存在时抛出 ``ENOATTR``。``position``
        是 macOS 扩展属性接口的偏移参数，普通文件系统通常可以忽略。
        """
        attrs = self.files[path].get("attrs", {})

        try:
            return attrs[name]
        except KeyError:
            raise FuseOSError(ENOATTR)

    def listxattr(self, path):
        """列出路径上已有的扩展属性名。

        ``xattr -l`` 或 Finder 查询扩展属性时会触发它。返回值只包含属性名，不包含
        属性值；每个属性值会在之后通过 ``getxattr`` 单独读取。
        """
        attrs = self.files[path].get("attrs", {})
        return list(attrs)

    def mkdir(self, path, mode):
        """创建目录。

        目录的 ``st_nlink`` 通常至少是 2，表示它自己和 ``.``；父目录还要因为新的
        ``..`` 引用增加链接数。这个示例通过路径前缀推导目录树，所以只需要保存新目录
        自己的 stat 字段并更新直接父目录。
        """
        if path in self.files:
            raise FuseOSError(EEXIST)
        parent = self._require_parent_dir(path)

        now = time_ns()
        self.files[path] = dict(
            st_mode=(S_IFDIR | mode),
            st_nlink=2,
            st_size=0,
            st_ctime=now,
            st_mtime=now,
            st_atime=now,
        )

        self.files[parent]["st_nlink"] += 1

    def open(self, path, flags):
        """打开已有文件并返回文件句柄。

        ``open`` 不负责创建文件；创建场景走 ``create``。这里不检查 ``flags``，只返回
        一个新的演示句柄。真实实现要根据 ``flags`` 检查读写权限、拒绝不支持的打开
        模式，并把底层文件描述符或内部句柄返回给后续读写回调。
        """
        self.fd += 1
        return self.fd

    def read(self, path, size, offset, fh):
        """从文件内容中按偏移读取最多 ``size`` 字节。

        FUSE 的读取不是“从当前文件位置继续读”，而是每次都显式给出 ``offset``。因此
        实现不能依赖全局游标，必须按传入偏移切片。返回少于 ``size`` 字节表示读到了
        文件末尾，返回空字节串表示没有更多数据。
        """
        return self.data[path][offset : offset + size]

    def readdir(self, path, fh, flags=0) -> Iterable[str]:
        """列出目录项。

        这是另一个基础回调。内核读取目录时需要它返回 ``.``、``..`` 和子项名称。这里
        只返回该目录的直接子项，不能把整棵树都列出来。
        """
        self._require_dir(path)
        return [".", ".."] + sorted(self._children(path))

    def readlink(self, path):
        """返回符号链接中保存的目标字符串。

        注意返回的是链接本身存储的目标，例如 ``"docs"`` 或 ``"/tmp/x"``，不是解析后
        的真实路径。这里把符号链接目标和普通文件内容分开保存，避免混用字节内容和
        文本目标。
        """
        return self.links[path]

    def removexattr(self, path, name):
        """删除扩展属性。

        属性存在时从属性字典里移除；不存在时抛出 ``ENOATTR``，让调用者知道删除目标
        并不存在。真实实现还应处理只读属性、权限和命名空间规则。
        """
        attrs = self.files[path].get("attrs", {})

        try:
            del attrs[name]
        except KeyError:
            raise FuseOSError(ENOATTR)

    def rename(self, old, new, flags):
        """重命名或移动一个路径。

        libfuse3 会把重命名扩展语义放在 ``flags`` 中，例如原子交换等。这个示例只支持
        普通 rename，所以任何非零 ``flags`` 都返回 ``EINVAL``。除了移动元数据，还要
        同步移动文件内容或符号链接目标，否则新路径会丢失数据。
        """
        if flags:
            raise FuseOSError(EINVAL)
        if old not in self.files:
            raise FuseOSError(ENOENT)
        if old == "/":
            raise FuseOSError(EINVAL)
        if old == new:
            return
        if new in self.files and self._is_dir(new):
            if not self._is_dir(old):
                raise FuseOSError(EISDIR)
            if self._children(new):
                raise FuseOSError(ENOTEMPTY)
        elif new in self.files and self._is_dir(old):
            raise FuseOSError(ENOTDIR)
        new_parent = self._require_parent_dir(new)
        old_parent = self._parent(old)
        moving_dir = self._is_dir(old)
        if moving_dir and self._is_descendant(old, new):
            raise FuseOSError(EINVAL)

        if new in self.files:
            self._remove_entry(new)

        paths: list[str] = [
            current
            for current in self.files
            if current == old or self._is_descendant(old, current)
        ]
        if moving_dir and old_parent != new_parent:
            self.files[old_parent]["st_nlink"] -= 1
            self.files[new_parent]["st_nlink"] += 1
        for current in paths:
            renamed = new + current[len(old) :]
            self.files[renamed] = self.files.pop(current)
        if old in self.data:
            self.data[new] = self.data.pop(old)
        if old in self.links:
            self.links[new] = self.links.pop(old)
        for current in list(self.data):
            if self._is_descendant(old, current):
                renamed = new + current[len(old) :]
                self.data[renamed] = self.data.pop(current)
        for current in list(self.links):
            if self._is_descendant(old, current):
                renamed = new + current[len(old) :]
                self.links[renamed] = self.links.pop(current)

    def rmdir(self, path):
        """删除空目录。

        如果目录包含任何文件或子目录，必须抛出 ``ENOTEMPTY``，否则调用者会以为删除
        成功并造成目录树状态错误。
        """
        if path == "/":
            raise FuseOSError(EINVAL)
        self._require_dir(path)
        if self._children(path):
            raise FuseOSError(ENOTEMPTY)
        self._remove_entry(path)

    def setxattr(self, path, name, value, options, position):
        """设置扩展属性。

        ``value`` 已经是字节串。``options`` 在 macOS 上可表达“必须新建”或“必须替换”
        等语义；这里为了保持示例短小没有实现这些检查。真实实现需要根据 options 在
        属性已存在或不存在时返回正确 errno。
        """
        attrs = self.files[path].setdefault("attrs", {})
        attrs[name] = value

    def statfs(self, path):
        """返回文件系统容量信息。

        ``df``、Finder 和很多程序会查询它来估算可用空间。这个内存示例返回固定值，
        因为没有真实块设备。真实文件系统应返回和底层存储一致的 ``statvfs`` 字段，
        至少包括块大小、总块数和可用块数。
        """
        return dict(f_bsize=512, f_blocks=4096, f_bavail=2048)

    def symlink(self, target, source):
        """创建符号链接。

        参数名容易让新手困惑：``target`` 是新建的链接路径，``source`` 是写进链接里的
        目标字符串。符号链接的大小通常等于目标字符串的字节长度；这里按 UTF-8 计算，
        并把目标字符串保存到 ``self.links[target]`` 供 ``readlink`` 返回。
        """
        now = time_ns()
        if target in self.files:
            raise FuseOSError(EEXIST)
        self._require_parent_dir(target)
        self.files[target] = dict(
            st_mode=(S_IFLNK | 0o777),
            st_nlink=1,
            st_size=len(source.encode("utf-8")),
            st_ctime=now,
            st_mtime=now,
            st_atime=now,
        )

        self.links[target] = source

    def truncate(self, path, length, fh=None):
        """把文件截断或扩展到指定长度。

        缩短文件时丢弃尾部数据；扩展文件时新增区域必须表现为零字节。这里用
        ``ljust`` 填充零字节，并同步更新 ``st_size``。真实实现如果有稀疏文件或块存储，
        可以不实际写入所有零字节，但读出来必须等价。
        """
        self.data[path] = self.data[path][:length].ljust(length, b"\x00")
        self.files[path]["st_size"] = length

    def unlink(self, path):
        """删除普通文件或符号链接目录项。

        ``unlink`` 不用于删除目录，目录删除走 ``rmdir``。这里同时删除元数据和内容；
        如果路径不存在则抛出 ``ENOENT``。真实 POSIX 文件系统还要考虑“文件已 unlink
        但仍被打开”的情况，此时数据通常要等最后一个句柄释放后才能真正回收。
        """
        if path not in self.files:
            raise FuseOSError(ENOENT)
        if self._is_dir(path):
            raise FuseOSError(EISDIR)
        self.data.pop(path, None)
        self.links.pop(path, None)
        self.files.pop(path)

    def utimens(self, path, times, fh):
        """更新访问时间和修改时间。

        ``times`` 为 ``(atime_ns, mtime_ns)`` 时使用调用者给出的纳秒时间戳；为 ``None``
        时表示使用当前时间。这个项目的示例统一使用纳秒整数，避免浮点秒带来的精度
        损失。
        """
        now = time_ns()
        atime, mtime = times if times else (now, now)
        self.files[path]["st_atime"] = atime
        self.files[path]["st_mtime"] = mtime

    def write(self, path, data, offset, fh):
        """把 ``data`` 写入文件的指定偏移。

        和 ``read`` 一样，写入也由内核显式给出 ``offset``。实现必须覆盖
        ``offset`` 开始的旧字节，而不是总是追加；如果 offset 超过当前文件大小，中间
        的空洞读出来应是零字节。返回值是实际写入的字节数，通常就是 ``len(data)``。
        """
        current = self.data[path]
        self.data[path] = (
            current[:offset].ljust(offset, b"\x00")
            + data
            + current[offset + len(data) :]
        )
        self.files[path]["st_size"] = len(self.data[path])
        return len(data)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("mount")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG)
    FUSE(Memory(), args.mount, foreground=True, allow_other=True)
