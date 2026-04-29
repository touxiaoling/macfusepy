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


def _root_attrs(path: str) -> StatResult:
    if path != "/":
        raise FuseOSError(errno.ENOENT)
    return {"st_mode": S_IFDIR | 0o755, "st_nlink": 2}


class Operations:
    """高级 libfuse3 path-based 同步操作基类。"""

    def __call__(self, op: str, *args: object) -> object:
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
        pass

    def destroy(self) -> None:
        pass

    def getattr(self, path: str, fh: FileHandle = None) -> StatResult:
        return _root_attrs(path)

    def opendir(self, path: str, flags: int | FileInfo = 0) -> OpenResult:
        return 0

    def readdir(
        self, path: str, fh: FileHandle, flags: int = 0
    ) -> Iterable[DirEntry]:
        return [".", ".."]

    def releasedir(self, path: str, fh: FileHandle) -> OperationStatus:
        return 0

    def fsyncdir(
        self, path: str, datasync: int, fh: FileHandle
    ) -> OperationStatus:
        return 0

    def statfs(self, path: str) -> StatVfsResult:
        return {}

    def access(self, path: str, amode: int) -> OperationStatus:
        return 0

    def open(self, path: str, flags: int | FileInfo) -> OpenResult:
        return 0

    def read(
        self, path: str, size: int, offset: int, fh: FileHandle
    ) -> bytes | str:
        raise FuseOSError(errno.EIO)

    def flush(self, path: str, fh: FileHandle) -> OperationStatus:
        return 0

    def fsync(self, path: str, datasync: int, fh: FileHandle) -> OperationStatus:
        return 0

    def lock(
        self, path: str, fh: FileHandle, cmd: int, lock: dict[str, int]
    ) -> dict[str, int] | None:
        """macFUSE VFS 不支持 POSIX GETLK/SETLK；该方法只可能接收 BSD flock。"""
        raise FuseOSError(ENOTSUP)

    def release(self, path: str, fh: FileHandle) -> OperationStatus:
        return 0

    def create(
        self, path: str, mode: int, fi: FileInfo | None = None
    ) -> OpenResult:
        raise FuseOSError(errno.EROFS)

    def write(
        self, path: str, data: bytes, offset: int, fh: FileHandle
    ) -> int | None:
        raise FuseOSError(errno.EROFS)

    def truncate(
        self, path: str, length: int, fh: FileHandle = None
    ) -> OperationStatus:
        raise FuseOSError(errno.EROFS)

    def unlink(self, path: str) -> OperationStatus:
        raise FuseOSError(errno.EROFS)

    def rename(self, old: str, new: str, flags: int) -> OperationStatus:
        raise FuseOSError(errno.EROFS)

    def mkdir(self, path: str, mode: int) -> OperationStatus:
        raise FuseOSError(errno.EROFS)

    def rmdir(self, path: str) -> OperationStatus:
        raise FuseOSError(errno.EROFS)

    def mknod(self, path: str, mode: int, dev: int) -> OperationStatus:
        raise FuseOSError(errno.EROFS)

    def utimens(
        self, path: str, times: TimespecPair, fh: FileHandle
    ) -> OperationStatus:
        return 0

    def chmod(
        self, path: str, mode: int, fh: FileHandle = None
    ) -> OperationStatus:
        raise FuseOSError(errno.EROFS)

    def chown(
        self, path: str, uid: int, gid: int, fh: FileHandle = None
    ) -> OperationStatus:
        raise FuseOSError(errno.EROFS)

    def readlink(self, path: str) -> bytes | str:
        raise FuseOSError(errno.ENOENT)

    def symlink(self, target: str, source: str) -> OperationStatus:
        raise FuseOSError(errno.EROFS)

    def link(self, target: str, source: str) -> OperationStatus:
        raise FuseOSError(errno.EROFS)

    def listxattr(self, path: str) -> Iterable[str | bytes]:
        return []

    def getxattr(self, path: str, name: str, position: int) -> XAttrValue:
        raise FuseOSError(ENOTSUP)

    def setxattr(
        self, path: str, name: str, value: bytes, options: int, position: int
    ) -> OperationStatus:
        raise FuseOSError(ENOTSUP)

    def removexattr(self, path: str, name: str) -> OperationStatus:
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
