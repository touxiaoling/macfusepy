from __future__ import annotations

import errno
import logging
from collections.abc import Iterable, Mapping
from inspect import isawaitable
from stat import S_IFDIR
from typing import ClassVar, TypeAlias

from macfusepy.errors import FuseOSError
from macfusepy.lowlevel_async import LowLevelAttr
from macfusepy.types import Config, ConnectionInfo, FileInfo, IoctlData


log = logging.getLogger("macfusepy")
ENOTSUP = errno.ENOTSUP

OperationStatus: TypeAlias = int | None
FileHandle: TypeAlias = int | FileInfo | None
OpenResult: TypeAlias = int | FileInfo | None
StatResult: TypeAlias = Mapping[str, int] | LowLevelAttr
StatVfsResult: TypeAlias = Mapping[str, int]
DirEntryName: TypeAlias = str | bytes
DirEntry: TypeAlias = (
    DirEntryName
    | tuple[DirEntryName, StatResult | None]
    | tuple[DirEntryName, StatResult | None, int]
)
TimespecPair: TypeAlias = tuple[int, int] | None
XAttrValue: TypeAlias = bytes | str
IoctlValue: TypeAlias = int | bytes | str | tuple[int, bytes | str | None] | None
CreateResult: TypeAlias = OpenResult | tuple[OpenResult, StatResult]
PathEntryAttrsResult: TypeAlias = OperationStatus | StatResult


def _root_attrs(path: str) -> StatResult:
    if path != "/":
        raise FuseOSError(errno.ENOENT)
    return {"st_mode": S_IFDIR | 0o755, "st_nlink": 2}


class Operations:
    """基于路径的高级 FUSE 操作基类（与 libfuse3 语义对齐的同步回调）。

    继承本类并实现所需方法后，可交给 :class:`macfusepy.FUSE` 挂载。运行时会把本
    接口适配为内部的 :class:`macfusepy.InodeOperations`（维护 inode、lookup
    计数、目录项 offset 等），因此只需处理 UTF-8（或由挂载 ``encoding`` 指定）
    的 ``path`` 字符串。

    **同步模型**：所有方法必须是普通 ``def``，禁止返回 awaitable。未实现的操作
    可保持基类默认实现（多数会抛出 :exc:`macfusepy.FuseOSError`），或删除方法
    并由 :meth:`__call__` 转为 ``ENOSYS``。

    **raw_fi**：为 ``False``（默认）时，:meth:`open` / :meth:`opendir` 的打开标志
    由 ``int`` 传入；为 ``True`` 时由 :class:`macfusepy.types.FileInfo` 传入，且
    :meth:`create` 会收到带 ``flags`` 的 ``FileInfo``。读写等回调中的 ``fh`` 在
    ``raw_fi=True`` 时也可为 ``FileInfo``，否则多为内核分配的整数句柄。

    **错误**：失败时应抛出 :exc:`macfusepy.FuseOSError`，参数为 errno 整数值，
    运行时会将其转为对 libfuse 的负 errno 回复。

    **线程**：底层使用多线程 low-level session，各方法可能被并发调用，共享状态
    需自行同步。

    另见 :class:`LoggingMixIn`（在 :meth:`__call__` 层记录调用与返回值）。
    """

    def __call__(self, op: str, *args: object) -> object:
        """按操作名动态分发到同名方法（与内部适配器调用约定一致）。

        Args:
            op: 方法名字符串，例如 ``\"getattr\"``、``\"readdir\"``。
            *args: 透传给目标方法的 positional 参数。

        Returns:
            各操作对应的返回值，语义与同名的显式方法一致。

        Raises:
            FuseOSError: 目标方法抛出时原样传播。
            FuseOSError(ENOSYS): 不存在名为 ``op`` 的方法时。
            TypeError: 目标方法返回 awaitable 时（禁止使用异步操作）。
        """
        method = getattr(self, op, None)
        if method is None:
            raise FuseOSError(errno.ENOSYS)
        result = method(*args)
        if isawaitable(result):
            close = getattr(result, "close", None)
            if close is not None:
                close()
            raise TypeError(f"{type(self).__name__}.{op}() must be a sync operation")
        return result

    def init(
        self, conn: ConnectionInfo | None = None, cfg: Config | None = None
    ) -> None:
        """挂载会话初始化（libfuse ``init`` 钩子）。

        Args:
            conn: 内核连接能力快照；可能为 ``None``（取决于调用路径）。
            cfg: 可修改的挂载配置视图；可能为 ``None``。

        Note:
            在 ``FUSE`` 构造并进入 multithreaded loop 后由底层调用；可根据
            ``conn.max_write`` 等调整行为。
        """
        pass

    def destroy(self) -> None:
        """挂载结束、会话销毁前调用；用于释放进程内资源。"""
        pass

    def getattr(self, path: str, fh: FileHandle = None) -> StatResult:
        """查询路径 ``path`` 的属性（``stat`` / ``getattr``）。

        Args:
            path: 绝对路径，根为 ``\"/\"``。
            fh: 若内核在已打开文件上查询属性，会传入打开时的文件句柄；否则为
                ``None``。``setattr`` 分解出的 ``chmod``/``truncate``/``utimens``
                等调用也可能携带句柄。

        Returns:
            ``st_mode``、``st_ino``、``st_size``、时间戳等键的映射，或
            :class:`macfusepy.lowlevel_async.LowLevelAttr`。时间戳建议使用纳秒
            （与 libfuse3 / 示例一致）。适配层会把 ``st_ino`` 校正为内部 inode。

        Raises:
            FuseOSError: 常见如 ``ENOENT``、``EACCES``。
        """
        return _root_attrs(path)

    def opendir(self, path: str, flags: int | FileInfo = 0) -> OpenResult:
        """打开目录以供 :meth:`readdir` 使用。

        Args:
            path: 目录绝对路径。
            flags: ``raw_fi=False`` 时为打开标志（``int``）；``raw_fi=True`` 时为
                :class:`macfusepy.types.FileInfo`。

        Returns:
            ``0`` 或 ``None`` 表示成功；或返回 ``FileInfo`` / ``int`` 作为目录句柄
            ``fh``（由后续 ``readdir`` / ``releasedir`` 原样传回）。
        """
        return 0

    def readdir(
        self, path: str, fh: FileHandle, flags: int = 0
    ) -> Iterable[DirEntry]:
        """列出目录内容（不含 ``.`` / ``..`` 时适配层仍会补全并处理 offset）。

        Args:
            path: 目录路径。
            fh: :meth:`opendir` 返回的句柄。
            flags: libfuse3 ``readdir`` 标志（如 ``FUSE_READDIR_PLUS``）；多数实现
                可忽略。

        Returns:
            可迭代序列，元素可为：

            - 单一名称：``str`` 或 ``bytes``（相对名，非绝对路径）。
            - ``(name, attrs)``：``attrs`` 为 ``None`` 时适配层会对该子路径再调
              ``getattr``；否则应为属性映射或 :class:`macfusepy.lowlevel_async.LowLevelAttr`。
            - ``(name, attrs, next_id)``：显式指定目录游标 ``next_id``；整数须大于
              low-level 传入的 ``offset`` 才会进入本批回复。

        Note:
            适配层会把名称编码为 ``bytes`` 并合成
            :class:`macfusepy.lowlevel_async.LowLevelEntry`；不必自行构造该类型。
        """
        return [".", ".."]

    def releasedir(self, path: str, fh: FileHandle) -> OperationStatus:
        """关闭 :meth:`opendir` 打开的目录句柄。"""
        return 0

    def fsyncdir(
        self, path: str, datasync: int, fh: FileHandle
    ) -> OperationStatus:
        """目录 ``fsync`` / ``fdatasync``；``datasync`` 非零表示仅数据同步。"""
        return 0

    def statfs(self, path: str) -> StatVfsResult:
        """返回文件系统统计（``statvfs``），键名与 ``os.statvfs_result`` 对齐。

        Args:
            path: 任意已存在路径；适配层会传当前查询上下文路径。

        Returns:
            例如 ``f_blocks``、``f_bfree``、``f_bavail``、``f_files`` 等；空映射
            表示使用内核默认。
        """
        return {}

    def access(self, path: str, amode: int) -> OperationStatus:
        """POSIX ``access``；``amode`` 为 ``R_OK``/``W_OK``/``X_OK``/``F_OK`` 的组合。

        Returns:
            ``0``/``None`` 表示允许；抛出 ``FuseOSError(EACCES)`` 等表示拒绝。

        Note:
            ``FUSE(..., kernel_permissions=True)`` 时会禁用 ``access`` 回调。
        """
        return 0

    def open(self, path: str, flags: int | FileInfo) -> OpenResult:
        """打开已存在文件（非 :meth:`create` 创建新文件路径）。

        Args:
            path: 文件绝对路径。
            flags: ``raw_fi=False`` 时为 ``open(2)`` 风格标志；``raw_fi=True`` 时为
                ``FileInfo``（含 ``flags``）。

        Returns:
            成功时返回 ``0``、``None``、整数 ``fh`` 或 ``FileInfo``（可写回
            ``direct_io``、``keep_cache`` 等字段）。
        """
        return 0

    def read(
        self, path: str, size: int, offset: int, fh: FileHandle
    ) -> bytes | str:
        """从已打开文件读取最多 ``size`` 字节（自 ``offset`` 起）。

        Note:
            路径层适配器将返回值视为字节负载；实现上应优先返回 ``bytes``。
        """
        raise FuseOSError(errno.EIO)

    def flush(self, path: str, fh: FileHandle) -> OperationStatus:
        """关闭描述符前刷新（每个 ``dup`` 后的描述符关闭时可能调用）。"""
        return 0

    def fsync(self, path: str, datasync: int, fh: FileHandle) -> OperationStatus:
        """刷盘；``datasync`` 非零表示 ``fdatasync`` 语义。"""
        return 0

    def lock(
        self, path: str, fh: FileHandle, cmd: int, lock: dict[str, int]
    ) -> dict[str, int] | OperationStatus:
        """文件锁：在 macFUSE 上由适配层转发 ``flock`` 与 ``fcntl`` 锁请求。

        ``cmd`` 可能为 ``F_GETLK``、``F_SETLK``、``F_SETLKW`` 等；``lock`` 为
        ``flock`` 结构字段的字典（如 ``l_type``、``l_whence``、``l_start``、
        ``l_len``、``l_pid``）。

        Returns:
            ``F_GETLK`` 时返回描述冲突锁的字典；其它命令常返回 ``0``/``None``。

        Raises:
            FuseOSError(ENOTSUP): 基类默认；若实现 POSIX/BSD 锁语义可覆盖。

        Note:
            内部 :class:`macfusepy.InodeOperations` 的 ``getlk`` / ``setlk`` / ``flock``
            会映射到本方法。
        """
        raise FuseOSError(ENOTSUP)

    def release(self, path: str, fh: FileHandle) -> OperationStatus:
        """``open`` / ``create`` 对应句柄最后一次关闭时调用。"""
        return 0

    def create(
        self, path: str, mode: int, fi: FileInfo | None = None
    ) -> CreateResult:
        """创建并打开新文件（``O_CREAT`` 语义路径）。

        Args:
            path: 将创建的文件绝对路径。
            mode: 创建模式（含类型位，如 ``S_IFREG``）。
            fi: 仅 ``raw_fi=True`` 时传入，含打开 ``flags``；可原地修改 ``fh``、
                ``direct_io`` 等写回 libfuse。

        Returns:
            单独 :data:`OpenResult`；或二元组 ``(OpenResult, StatResult)``，第二
            个元素为新文件的完整属性（避免适配层再 ``getattr``）。

        Raises:
            FuseOSError: 如 ``EEXIST``、``EROFS``。
        """
        raise FuseOSError(errno.EROFS)

    def write(
        self, path: str, data: bytes, offset: int, fh: FileHandle
    ) -> int | None:
        """写入 ``data`` 到 ``offset``；返回写入字节数，或 ``None`` 表示按长度成功。"""
        raise FuseOSError(errno.EROFS)

    def truncate(
        self, path: str, length: int, fh: FileHandle = None
    ) -> OperationStatus:
        """截断为 ``length``；``fh`` 非空表示 ``ftruncate`` 语义。"""
        raise FuseOSError(errno.EROFS)

    def unlink(self, path: str) -> OperationStatus:
        """删除文件（非目录）。"""
        raise FuseOSError(errno.EROFS)

    def rename(self, old: str, new: str, flags: int) -> OperationStatus:
        """重命名；``flags`` 为 libfuse3 ``rename`` 标志（如 ``RENAME_EXCHANGE``）。"""
        raise FuseOSError(errno.EROFS)

    def mkdir(self, path: str, mode: int) -> PathEntryAttrsResult:
        """创建目录。

        Returns:
            ``0``/``None`` 等表示成功，属性由后续 ``getattr`` 补全；或返回
            :data:`StatResult`，适配层直接用于构造目录项。
        """
        raise FuseOSError(errno.EROFS)

    def rmdir(self, path: str) -> OperationStatus:
        """删除空目录。"""
        raise FuseOSError(errno.EROFS)

    def mknod(self, path: str, mode: int, dev: int) -> PathEntryAttrsResult:
        """创建设备节点等特殊文件；``dev`` 为主次设备号打包值。

        Returns:
            语义同 :meth:`mkdir`。
        """
        raise FuseOSError(errno.EROFS)

    def utimens(
        self, path: str, times: TimespecPair, fh: FileHandle
    ) -> OperationStatus:
        """设置访问/修改时间；``times`` 为 ``(atime_ns, mtime_ns)`` 或 ``None``。"""
        return 0

    def chmod(
        self, path: str, mode: int, fh: FileHandle = None
    ) -> OperationStatus:
        """修改权限；``fh`` 非空表示 ``fchmod`` 语义。"""
        raise FuseOSError(errno.EROFS)

    def chown(
        self, path: str, uid: int, gid: int, fh: FileHandle = None
    ) -> OperationStatus:
        """修改属主；未设置位时 ``uid``/``gid`` 可能为 ``-1``。"""
        raise FuseOSError(errno.EROFS)

    def readlink(self, path: str) -> bytes | str:
        """读取符号链接目标内容（链接本身的路径为 ``path``）。"""
        raise FuseOSError(errno.ENOENT)

    def symlink(self, target: str, source: str) -> PathEntryAttrsResult:
        """在路径 ``target`` 处创建指向 ``source`` 的符号链接。

        Note:
            参数顺序与内部适配器一致：第一个参数为新 symlink 的路径，第二个为
            链接目标字符串。

        Returns:
            成功状态或 :data:`StatResult`（返回映射 / ``LowLevelAttr`` 时适配层
            用于构造 lookup 结果）。
        """
        raise FuseOSError(errno.EROFS)

    def link(self, target: str, source: str) -> OperationStatus:
        """创建硬链接：``target`` 为新路径，``source`` 为已存在文件路径。"""
        raise FuseOSError(errno.EROFS)

    def listxattr(self, path: str) -> Iterable[str | bytes]:
        """列出扩展属性名；空序列表示无 xattr。"""
        return []

    def getxattr(self, path: str, name: str, position: int) -> XAttrValue:
        """读取扩展属性 ``name``；``position`` 为 macOS 资源分叉常用偏移。"""
        raise FuseOSError(ENOTSUP)

    def setxattr(
        self, path: str, name: str, value: bytes, options: int, position: int
    ) -> OperationStatus:
        """设置扩展属性；``options``/``position`` 语义同平台 xattr API。"""
        raise FuseOSError(ENOTSUP)

    def removexattr(self, path: str, name: str) -> OperationStatus:
        """删除扩展属性。"""
        raise FuseOSError(ENOTSUP)

    def ioctl(
        self,
        path: str,
        cmd: int,
        arg: int,
        fh: FileHandle,
        flags: int,
        data: int | IoctlData,
    ) -> IoctlValue:
        """``ioctl`` 请求；``data`` 为指针整型或 :class:`macfusepy.types.IoctlData`。

        Returns:
            整数、字节串、字符串或 ``(返回值, 输出负载)`` 等，由 low-level 桥解释。

        Raises:
            FuseOSError: 常见 ``ENOTTY``、``EINVAL``。
        """
        raise FuseOSError(errno.ENOTTY)

    # macFUSE VFS 当前不支持 BMAP，运行时不会注册该回调。
    bmap: ClassVar[None] = None


class LoggingMixIn:
    """记录每次 FUSE 操作调用和返回值的 mixin。"""

    def __call__(self, op: str, *args: object) -> object:
        log.debug("%s%s", op, repr(args))
        try:
            result = getattr(super(), "__call__")(op, *args)
            log.debug("%s%s -> %r", op, repr(args), result)
            return result
        except OSError as exc:
            log.debug("%s%s -> OSError(%s)", op, repr(args), exc.errno)
            raise
