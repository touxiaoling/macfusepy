#!/usr/bin/env python3

import logging
import os

from errno import EACCES, EINVAL, ENOSYS
from pathlib import Path
from stat import S_ISREG

from macfusepy import FUSE, FileInfo, FuseOSError, Operations, LoggingMixIn


class Loopback(LoggingMixIn, Operations):
    """把一个真实目录“映射”成 FUSE 文件系统。

    FUSE 传给回调的 ``path`` 都是挂载点内的绝对路径，例如 ``/note.txt``。这个
    示例在 ``__call__`` 里先把它转换成宿主机真实路径，再调用对应操作。因此除
    了 ``rename``、``link``、``symlink`` 这类含有第二个路径的回调，其他方法里
    看到的 ``path`` 已经是可以直接交给 ``os`` 模块的真实路径。

    学习重点:
        这个例子不是自己存储文件内容，而是把 FUSE 操作翻译成宿主机目录上的
        ``os`` 调用。它适合用来理解“回调参数如何映射到 POSIX 系统调用”：``open``
        返回真实文件描述符，后续 ``read``/``write``/``release`` 都通过同一个 ``fh``
        操作底层文件。
    """

    def __init__(self, root):
        """保存被映射的真实根目录。

        ``root`` 是宿主机上的目录，不是挂载点。``resolve`` 会把相对路径转为绝对路径，
        便于后续拼接。
        """
        self.root = Path(root).resolve()

    def _full_path(self, path):
        """把挂载点内路径转换成宿主机真实路径。

        libfuse 传入的路径总是以 ``/`` 开头，例如 ``/dir/a.txt``。这里去掉开头斜杠后
        拼到 ``self.root`` 下。真实文件系统还要特别注意路径穿越、符号链接逃逸和权限
        边界；这个教学示例假设传入路径已经由内核规范化。
        """
        if path == "/":
            return os.fspath(self.root)
        return os.fspath(self.root / path.lstrip("/"))

    def _fd(self, fh: int | FileInfo | None) -> int:
        """提取真实文件描述符；loopback 示例不会把 ``None`` 当作有效句柄。"""
        if isinstance(fh, FileInfo):
            return fh.fh
        if fh is None:
            raise FuseOSError(EINVAL)
        return fh

    def _open_flags(self, flags: int | FileInfo) -> int:
        """兼容普通 flags 和 ``raw_fi=True`` 时的 ``FileInfo``。"""
        if isinstance(flags, FileInfo):
            return flags.flags
        return flags

    def __call__(self, op, *args):
        """在分发到具体回调前统一转换第一个路径参数。

        ``Operations.__call__`` 会按操作名调用同名方法。loopback 文件系统的大多数
        方法都只需要处理一个路径，所以这里先把第一个参数转成真实路径，再交给父类
        分发。``init`` 和 ``destroy`` 这类生命周期回调没有路径参数，直接交给基类。
        含有第二个路径的 ``rename``、``link``、``symlink`` 会在各自方法里手动转换
        第二个路径或保留原始目标字符串。
        """
        if op in {"init", "destroy"}:
            return super().__call__(op, *args)
        path, *rest = args
        return super().__call__(op, self._full_path(path), *rest)

    def access(self, path, amode):
        """检查调用者请求的访问权限。

        ``amode`` 与 ``os.access`` 一样，是读、写、执行权限的位组合。这里把检查转发
        给宿主机；如果目标尚不存在但调用者是在检查写权限，则检查父目录是否可写，
        这样创建新文件前的访问检查可以通过。
        """
        if not os.path.exists(path):
            parent = os.path.dirname(path)
            if amode == os.W_OK and os.access(parent, os.W_OK):
                return None
            raise FuseOSError(EACCES)
        if not os.access(path, amode):
            raise FuseOSError(EACCES)

    def chmod(self, path, mode, fh=None):
        """修改真实文件的权限位。

        FUSE 的 ``chmod`` 对应 POSIX ``chmod(2)``。因为 ``path`` 已经在 ``__call__``
        中转换成真实路径，这里可以直接调用 ``os.chmod``。``fh`` 是可选文件句柄，本
        示例没有用它。
        """
        return os.chmod(path, mode)

    def chown(self, path, uid, gid, fh=None):
        """修改真实文件的所有者和所属组。

        ``uid`` 或 ``gid`` 为 ``-1`` 时，底层 ``os.chown`` 会按平台规则保持该字段不变。
        真实文件系统如果有自己的用户映射，应在这里把 FUSE 传入的 ID 转成底层存储
        认识的身份。
        """
        return os.chown(path, uid, gid)

    def create(self, path: str, mode: int, fi=None) -> int:
        """创建并打开真实文件。

        返回的整数是真实文件描述符，会成为后续 ``read``、``write``、``flush`` 和
        ``release`` 收到的 ``fh``。这里使用写入、创建、截断标志，模拟常见的
        ``open(..., "w")`` 行为。更完整的实现可以从 ``fi`` 或 flags 中读取调用者的
        精确打开模式。
        """
        return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)

    def flush(self, path: str, fh: int | FileInfo | None):
        """刷新打开文件的脏数据。

        ``flush`` 可能在同一个文件句柄生命周期内被调用多次，也可能因为复制的文件
        描述符而出现多次；因此不要在这里关闭 ``fh``。关闭真实描述符应放在
        ``release``。这个示例用 ``fsync`` 保证数据落到宿主机。
        """
        return os.fsync(self._fd(fh))

    def fsync(self, path: str, datasync: int, fh: int | FileInfo | None):
        """按调用者要求同步文件数据或元数据。

        ``datasync`` 非零时只要求同步数据，类似 ``fdatasync``；为零时还要同步元数据，
        类似 ``fsync``。macOS 上如果没有 ``fdatasync``，示例退回到 ``fsync``。
        """
        fd = self._fd(fh)
        if datasync != 0:
            sync_data = getattr(os, "fdatasync", os.fsync)
            return sync_data(fd)
        return os.fsync(fd)

    def getattr(
        self, path: str, fh: int | FileInfo | None = None
    ) -> dict[str, int]:
        """返回真实路径的 stat 元数据。

        这是 FUSE 能否看见文件的基础。这里使用 ``os.lstat`` 而不是 ``os.stat``，这样
        符号链接会作为链接本身暴露，而不是被跟随到目标文件。返回给本项目 API 的
        时间戳使用纳秒整数，所以取 ``st_atime_ns`` 等字段。
        """
        st = os.lstat(path)
        return {
            "st_atime": st.st_atime_ns,
            "st_ctime": st.st_ctime_ns,
            "st_gid": st.st_gid,
            "st_mode": st.st_mode,
            "st_mtime": st.st_mtime_ns,
            "st_nlink": st.st_nlink,
            "st_size": st.st_size,
            "st_uid": st.st_uid,
        }

    def getxattr(self, path: str, name: str, position: int):
        raise FuseOSError(ENOSYS)

    def link(self, target, source):
        """创建硬链接。

        经过 ``__call__`` 后，``target`` 已经是真实的新链接路径；``source`` 仍是挂载点
        内路径，需要手动转换。硬链接要求源和目标位于同一个支持硬链接的底层文件
        系统，失败时底层 ``os.link`` 会抛出对应 ``OSError``。
        """
        return os.link(self._full_path(source), target)

    def listxattr(self, path: str):
        raise FuseOSError(ENOSYS)

    def mkdir(self, path, mode):
        """创建真实目录。

        ``mode`` 是调用者请求的新目录权限位。实际权限还会受到进程 umask 和底层文件
        系统策略影响，这一点和普通 ``mkdir(2)`` 一致。
        """
        return os.mkdir(path, mode)

    def mknod(self, path, mode, dev):
        """创建文件系统节点。

        macOS 上普通应用最常见的是创建普通文件。这里对普通文件使用
        ``os.open(..., O_CREAT | O_EXCL)``，因为某些平台的 ``mknod`` 对普通文件支持
        有限制；其他类型交给 ``os.mknod``。真实文件系统可以只支持自己需要的节点类型。
        """
        if S_ISREG(mode):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode & 0o777)
            os.close(fd)
            return None
        return os.mknod(path, mode, dev)

    def open(self, path: str, flags: int | FileInfo) -> int:
        """打开真实文件并返回真实文件描述符。

        ``flags`` 与 ``os.open`` 的 flags 相同，包含只读、只写、追加等打开模式。返回
        的 fd 会作为 ``fh`` 传给后续读写和关闭回调。真实实现如果返回自定义句柄，也
        要保证能在后续回调中找到对应资源。
        """
        return os.open(path, self._open_flags(flags))

    def read(
        self, path: str, size: int, offset: int, fh: int | FileInfo | None
    ) -> bytes:
        """从真实文件描述符读取数据。

        FUSE 每次读取都会给出明确 ``offset``，不能依赖文件描述符当前的位置。``pread``
        会按指定偏移读取且不移动共享 fd 位置。
        """
        return os.pread(self._fd(fh), size, offset)

    def readdir(self, path, fh, flags=0):
        """列出真实目录中的目录项。

        FUSE 期望目录列表包含 ``.`` 和 ``..``，所以这里手动加上，再拼接
        ``os.listdir`` 的结果。``flags`` 可用于 readdir-plus 等优化，本示例忽略它。
        """
        return [".", ".."] + os.listdir(path)

    def readlink(self, path):
        """读取符号链接目标。

        ``os.readlink`` 返回链接里存放的原始目标字符串。不要在这里解析成绝对路径；
        调用者需要看到的就是符号链接自身保存的内容。
        """
        return os.readlink(path)

    def release(self, path: str, fh: int | FileInfo | None):
        """关闭 ``open`` 或 ``create`` 返回的真实文件描述符。

        ``release`` 是文件句柄生命周期的结束点。和 ``flush`` 不同，它通常只会在内核
        不再使用该句柄时调用一次，所以适合在这里关闭 fd 或释放自定义资源。
        """
        return os.close(self._fd(fh))

    def rename(self, old, new, flags):
        """重命名或移动真实路径。

        ``old`` 已经是真实路径，``new`` 仍是挂载点内路径，需要转换。libfuse3 的
        ``flags`` 可以表示扩展 rename 语义；本示例只支持普通 rename，遇到非零 flags
        返回 ``EINVAL``，避免假装支持没有实现的原子交换等行为。
        """
        if flags:
            raise FuseOSError(EINVAL)
        return os.rename(old, self._full_path(new))

    def rmdir(self, path):
        """删除真实空目录。

        底层 ``os.rmdir`` 会负责在目录不存在、不是目录或目录非空时给出正确 errno。
        FUSE 回调只需要让这些 ``OSError`` 继续向上抛出即可。
        """
        return os.rmdir(path)

    def statfs(self, path):
        """返回底层文件系统的容量信息。

        loopback 文件系统没有自己的存储容量，所以直接把宿主机 ``statvfs`` 的关键字段
        透传给 FUSE。调用 ``df`` 或 Finder 查看容量时会用到这些值。
        """
        stv = os.statvfs(path)
        return {
            key: getattr(stv, key)
            for key in (
                "f_bavail",
                "f_bfree",
                "f_blocks",
                "f_bsize",
                "f_ffree",
                "f_files",
                "f_flag",
            )
        }

    def symlink(self, target, source):
        """创建符号链接。

        ``target`` 是新链接的真实路径；``source`` 是要写进符号链接的原始目标字符串。
        这里故意不把 ``source`` 拼接到 root 下，因为相对链接和绝对链接都应按用户
        输入原样保存。
        """
        return os.symlink(source, target)

    def truncate(self, path: str, length: int, fh: int | FileInfo | None = None):
        """截断或扩展真实文件。

        如果 libfuse 提供了已打开文件句柄，就优先用 ``ftruncate``，这样可以避免再按
        路径打开一次文件；否则用 Python 文件对象按路径截断。扩展文件时底层文件系统
        会负责让新增区域读起来像零字节。
        """
        if fh is not None:
            os.ftruncate(self._fd(fh), length)
            return None
        with open(path, "r+b") as f:
            f.truncate(length)
        return None

    def unlink(self, path):
        """删除真实文件或符号链接。

        目录不能用 ``unlink`` 删除，目录删除会走 ``rmdir``。底层 ``os.unlink`` 会在
        目标不存在、权限不足或目标是目录时抛出正确错误。
        """
        return os.unlink(path)

    def utimens(self, path, times, fh):
        """更新真实路径的访问时间和修改时间。

        ``times`` 为 ``None`` 时表示使用当前时间；否则是 ``(atime_ns, mtime_ns)``。
        本项目约定 FUSE 回调中的时间戳都是纳秒整数，所以直接传给
        ``os.utime(ns=...)``。
        """
        if times is None:
            return os.utime(path, None)
        return os.utime(path, ns=times)

    def write(
        self, path: str, data: bytes, offset: int, fh: int | FileInfo | None
    ) -> int:
        """向真实文件描述符指定偏移写入数据。

        FUSE 写入同样不是“从当前 fd 位置继续写”，而是每次给出明确 ``offset``。``pwrite``
        不移动共享 fd 位置，并返回底层实际写入的字节数。真实实现要正确处理短写、
        空间不足和并发写入的语义。
        """
        return os.pwrite(self._fd(fh), data, offset)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("root")
    parser.add_argument("mount")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG)
    FUSE(Loopback(args.root), args.mount, foreground=True, allow_other=True)
