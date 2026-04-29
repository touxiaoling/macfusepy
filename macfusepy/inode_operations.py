from __future__ import annotations

import errno
from collections.abc import Iterable

from macfusepy.errors import FuseOSError
from macfusepy.lowlevel_async import LowLevelEntry
from macfusepy.path_operations import (
    ENOTSUP,
    FileHandle,
    IoctlValue,
    OpenResult,
    OperationStatus,
    StatResult,
    StatVfsResult,
    XAttrValue,
)
from macfusepy.types import Config, ConnectionInfo, IoctlData


class InodeOperations:
    """inode 优先的同步 FUSE 操作基类（直接对应 libfuse3 low-level 语义）。

    与 :class:`macfusepy.Operations` 不同，本类以 **inode 号**（``ino``）与 **二进制
    文件名**（``bytes``）为核心，不经过路径适配层；适合自行维护 inode 表、目录
    表或需要最低开销的实现。根目录 inode 固定为 ``1``（:data:`macfusepy.lowlevel_async.ROOT_INODE`）。

    **挂载**：将子类实例传给 :class:`macfusepy.FUSE`；勿直接实例化本基类用于生产。

    **错误**：失败时抛出 :exc:`macfusepy.FuseOSError(errno)`；运行时会转为负 errno
    回复内核。

    **线程**：底层为多线程 low-level session，回调可能并发进入；共享结构须自行
    加锁。

    **目录项**：``lookup``、``mknod``、``mkdir``、``symlink``、``link``、
    ``create`` 等须返回 :class:`macfusepy.lowlevel_async.LowLevelEntry`（``name``、
    ``ino``、``attrs``、``next_id``）；其中 ``attrs`` 可为 ``Mapping[str, int]`` 或
    :class:`macfusepy.lowlevel_async.LowLevelAttr`，时间戳建议使用纳秒。

    **forget**：当内核递减 lookup 计数时调用，用于释放你方 inode 元数据（勿在此
    调用 libfuse API）。
    """

    def init(
        self, conn: ConnectionInfo | None = None, cfg: Config | None = None
    ) -> None:
        """会话初始化；``conn`` / ``cfg`` 为连接信息与可写挂载配置，可能为 ``None``。"""
        pass

    def destroy(self) -> None:
        """挂载退出前调用，用于释放资源。"""
        pass

    def lookup(self, parent: int, name: bytes) -> LowLevelEntry:
        """在目录 ``parent`` 下查找名为 ``name`` 的子项（``lookup``）。

        Args:
            parent: 父目录 inode（根目录为 ``ROOT_INODE``）。
            name: 目录项原始字节名（不含路径分隔符）。

        Returns:
            目标项的 :class:`macfusepy.lowlevel_async.LowLevelEntry`（含属性）。

        Raises:
            FuseOSError: 常见 ``ENOENT``、``EACCES``。
        """
        raise FuseOSError(errno.ENOENT)

    def forget(self, ino: int, nlookup: int) -> None:
        """内核将 inode ``ino`` 的 lookup 计数减少 ``nlookup``。

        当计数归零且内核不再引用该 inode 时，可在此回收实现侧元数据。无返回值。
        """
        pass

    def getattr(self, ino: int, fh: FileHandle = None) -> StatResult:
        """获取 inode ``ino`` 的属性（``getattr``）。

        Args:
            ino: 目标 inode。
            fh: 若请求与已打开文件关联则可能非 ``None``（``raw_fi`` 时可为
                ``FileInfo``）。

        Returns:
            属性映射或 ``LowLevelAttr``。

        Raises:
            FuseOSError: 如 ``ENOENT``。
        """
        raise FuseOSError(errno.ENOENT)

    def setattr(
        self, ino: int, attrs: StatResult, to_set: int, fh: FileHandle = None
    ) -> StatResult:
        """设置 inode 属性；``to_set`` 为 libfuse ``fuse_set_attr`` 位掩码。

        ``attrs`` 中仅被 ``to_set`` 标明的字段有效（如 ``FUSE_SET_ATTR_MODE``、
        ``FUSE_SET_ATTR_SIZE``、``FUSE_SET_ATTR_ATIME``、``FUSE_SET_ATTR_MTIME``、
        ``FUSE_SET_ATTR_UID``、``FUSE_SET_ATTR_GID`` 等，定义见 libfuse3 头文件）。

        Returns:
            更新后的完整属性（与 :meth:`getattr` 返回形态一致）。

        Raises:
            FuseOSError: 如 ``EROFS``、``EPERM``。
        """
        raise FuseOSError(errno.EROFS)

    def readlink(self, ino: int) -> bytes | str:
        """读取符号链接 inode ``ino`` 的目标内容。"""
        raise FuseOSError(errno.ENOENT)

    def mknod(
        self, parent: int, name: bytes, mode: int, dev: int
    ) -> LowLevelEntry:
        """在 ``parent`` 下创建特殊文件节点（设备文件等）；``dev`` 为主次设备号。"""
        raise FuseOSError(errno.EROFS)

    def mkdir(self, parent: int, name: bytes, mode: int) -> LowLevelEntry:
        """在 ``parent`` 下创建子目录 ``name``，权限为 ``mode``（含 ``S_IFDIR``）。"""
        raise FuseOSError(errno.EROFS)

    def unlink(self, parent: int, name: bytes) -> OperationStatus:
        """删除 ``parent`` 下的普通文件 ``name``。"""
        raise FuseOSError(errno.EROFS)

    def rmdir(self, parent: int, name: bytes) -> OperationStatus:
        """删除空子目录 ``name``。"""
        raise FuseOSError(errno.EROFS)

    def symlink(
        self, link: bytes, parent: int, name: bytes
    ) -> LowLevelEntry:
        """在 ``parent``/``name`` 处创建指向 ``link`` 字节串所表示路径的符号链接。"""
        raise FuseOSError(errno.EROFS)

    def rename(
        self, parent: int, name: bytes, newparent: int, newname: bytes, flags: int
    ) -> OperationStatus:
        """重命名；``flags`` 为 libfuse3 ``rename`` 标志（如 ``RENAME_EXCHANGE``）。"""
        raise FuseOSError(errno.EROFS)

    def link(self, ino: int, newparent: int, newname: bytes) -> LowLevelEntry:
        """为已存在 inode ``ino`` 在 ``newparent``/``newname`` 下创建硬链接。"""
        raise FuseOSError(errno.EROFS)

    def open(self, ino: int, flags: int, fi: FileHandle = None) -> OpenResult:
        """打开文件 ``ino``；``flags`` 为 ``open(2)`` 风格。

        Args:
            fi: ``raw_fi=True`` 时为 :class:`macfusepy.types.FileInfo`，可原地写
                ``fh``、``direct_io`` 等。

        Returns:
            ``0``/``None``、整数 ``fh`` 或 ``FileInfo``。
        """
        return 0

    def read(self, ino: int, size: int, offset: int, fh: FileHandle) -> bytes:
        """自 ``offset`` 起读取最多 ``size`` 字节。"""
        raise FuseOSError(errno.EIO)

    def write(
        self, ino: int, data: bytes, offset: int, fh: FileHandle
    ) -> int | None:
        """写入数据；返回写入长度或 ``None`` 表示按 ``len(data)`` 成功。"""
        raise FuseOSError(errno.EROFS)

    def flush(self, ino: int, fh: FileHandle) -> OperationStatus:
        """描述符 flush 语义。"""
        return 0

    def release(self, ino: int, fh: FileHandle) -> OperationStatus:
        """释放 :meth:`open` / :meth:`create` 获得的句柄。"""
        return 0

    def fsync(self, ino: int, datasync: int, fh: FileHandle) -> OperationStatus:
        """``fsync``/``fdatasync``；``datasync`` 非零表示仅刷数据。"""
        return 0

    def getlk(
        self, ino: int, fh: FileHandle, lock: dict[str, int]
    ) -> dict[str, int] | None:
        """POSIX ``F_GETLK`` 语义（查询锁冲突）。

        Note:
            当前 macFUSE VFS 不支持；默认实现抛 ``ENOTSUP``，运行时**不会**注册该
            回调。保留签名供类型检查与文档。
        """
        raise FuseOSError(ENOTSUP)

    def setlk(
        self, ino: int, fh: FileHandle, cmd: int, lock: dict[str, int]
    ) -> OperationStatus:
        """POSIX ``F_SETLK`` / ``F_SETLKW`` 语义。

        Note:
            当前 macFUSE VFS 不支持；默认抛 ``ENOTSUP``，运行时**不会**注册该回调。
        """
        raise FuseOSError(ENOTSUP)

    def flock(self, ino: int, fh: FileHandle, op: int) -> OperationStatus:
        """BSD ``flock(2)`` 语义；``op`` 为 ``LOCK_EX``/``LOCK_SH``/``LOCK_UN`` 等与
        ``LOCK_NB`` 的组合。"""
        raise FuseOSError(ENOTSUP)

    def opendir(
        self, ino: int, flags: int = 0, fi: FileHandle = None
    ) -> OpenResult:
        """打开目录 ``ino``；``fi`` 在 ``raw_fi=True`` 时为 ``FileInfo``。"""
        return 0

    def readdir(
        self, ino: int, offset: int, size: int, fh: FileHandle, flags: int = 0
    ) -> Iterable[LowLevelEntry]:
        """列出目录 ``ino`` 内容。

        Args:
            offset: 目录游标；仅应返回 ``LowLevelEntry.next_id > offset`` 的项。
            size: 内核给出的回复缓冲上限提示（字节）；实现可据此截断批次。
            fh: 目录句柄。
            flags: 如 ``FUSE_READDIR_PLUS``。

        Returns:
            ``LowLevelEntry`` 的可迭代对象；每项 ``name``、``ino``、``attrs``、
            ``next_id`` 由你方填写（``next_id`` 用于后续 ``readdir`` 续读）。

        Raises:
            FuseOSError: 如 ``ENOTDIR``。
        """
        raise FuseOSError(errno.ENOTDIR)

    def releasedir(self, ino: int, fh: FileHandle) -> OperationStatus:
        """关闭 :meth:`opendir` 目录句柄。"""
        return 0

    def fsyncdir(
        self, ino: int, datasync: int, fh: FileHandle
    ) -> OperationStatus:
        """目录 fsync。"""
        return 0

    def statfs(self, ino: int) -> StatVfsResult:
        """``statvfs`` 统计；``ino`` 为上下文 inode（常为查询起点）。"""
        return {}

    def setxattr(
        self, ino: int, name: bytes, value: bytes, options: int, position: int
    ) -> OperationStatus:
        """设置扩展属性；``name``/``value`` 为字节串。"""
        raise FuseOSError(ENOTSUP)

    def getxattr(self, ino: int, name: bytes, position: int) -> XAttrValue:
        """读取扩展属性 ``name``（字节名）。"""
        raise FuseOSError(ENOTSUP)

    def listxattr(self, ino: int) -> Iterable[str | bytes]:
        """列出 ``ino`` 上的扩展属性名。"""
        return []

    def removexattr(self, ino: int, name: bytes) -> OperationStatus:
        """删除扩展属性。"""
        raise FuseOSError(ENOTSUP)

    def access(self, ino: int, amode: int) -> OperationStatus:
        """``access`` 检查；``amode`` 为 ``R_OK``/``W_OK``/``X_OK``/``F_OK`` 组合。"""
        return 0

    def create(
        self, parent: int, name: bytes, mode: int, flags: int, fi: FileHandle
    ) -> tuple[LowLevelEntry, OpenResult]:
        """在 ``parent`` 下创建并打开新文件 ``name``。

        Args:
            mode: 文件类型与权限。
            flags: 打开标志。
            fi: ``raw_fi=True`` 时为 ``FileInfo``，可写回句柄与打开行为。

        Returns:
            二元组：新项 :class:`macfusepy.lowlevel_async.LowLevelEntry` 与打开结果
            （``OpenResult``：``0``/``None``/整数 ``fh``/``FileInfo``）。
        """
        raise FuseOSError(errno.EROFS)

    def bmap(self, ino: int, blocksize: int, idx: int) -> object:
        """块映射查询（BMAP）。

        Note:
            当前 macFUSE VFS 不支持；运行时**不会**注册该回调。
        """
        raise FuseOSError(ENOTSUP)

    def ioctl(
        self,
        ino: int,
        cmd: int,
        arg: int,
        fh: FileHandle,
        flags: int,
        data: int | IoctlData,
    ) -> IoctlValue:
        """``ioctl``；``data`` 为指针整数或 :class:`macfusepy.types.IoctlData`。"""
        raise FuseOSError(errno.ENOTTY)
