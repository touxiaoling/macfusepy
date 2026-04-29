import errno
from collections.abc import Iterable, Mapping
from typing import TypeAlias

from macfusepy.errors import FuseOSError
from macfusepy.lowlevel_async import LowLevelAttr, LowLevelEntry
from macfusepy.path_operations import ENOTSUP, IoctlValue
from macfusepy.types import Config, ConnectionInfo, FileInfo, IoctlData


OperationStatus: TypeAlias = int | None
FileHandle: TypeAlias = int | FileInfo | None
OpenResult: TypeAlias = int | FileInfo | None
StatResult: TypeAlias = Mapping[str, int] | LowLevelAttr
StatVfsResult: TypeAlias = Mapping[str, int]
XAttrValue: TypeAlias = bytes | str


class InodeOperations:
    """inode-first 的高性能 low-level 同步操作基类。"""

    def init(
        self, conn: ConnectionInfo | None = None, cfg: Config | None = None
    ) -> None:
        pass

    def destroy(self) -> None:
        pass

    def lookup(self, parent: int, name: bytes) -> LowLevelEntry:
        raise FuseOSError(errno.ENOENT)

    def forget(self, ino: int, nlookup: int) -> None:
        pass

    def getattr(self, ino: int, fh: FileHandle = None) -> StatResult:
        raise FuseOSError(errno.ENOENT)

    def setattr(
        self, ino: int, attrs: StatResult, to_set: int, fh: FileHandle = None
    ) -> StatResult:
        raise FuseOSError(errno.EROFS)

    def readlink(self, ino: int) -> bytes | str:
        raise FuseOSError(errno.ENOENT)

    def mknod(
        self, parent: int, name: bytes, mode: int, dev: int
    ) -> LowLevelEntry:
        raise FuseOSError(errno.EROFS)

    def mkdir(self, parent: int, name: bytes, mode: int) -> LowLevelEntry:
        raise FuseOSError(errno.EROFS)

    def unlink(self, parent: int, name: bytes) -> OperationStatus:
        raise FuseOSError(errno.EROFS)

    def rmdir(self, parent: int, name: bytes) -> OperationStatus:
        raise FuseOSError(errno.EROFS)

    def symlink(
        self, link: bytes, parent: int, name: bytes
    ) -> LowLevelEntry:
        raise FuseOSError(errno.EROFS)

    def rename(
        self, parent: int, name: bytes, newparent: int, newname: bytes, flags: int
    ) -> OperationStatus:
        raise FuseOSError(errno.EROFS)

    def link(self, ino: int, newparent: int, newname: bytes) -> LowLevelEntry:
        raise FuseOSError(errno.EROFS)

    def open(self, ino: int, flags: int, fi: FileHandle = None) -> OpenResult:
        return 0

    def read(self, ino: int, size: int, offset: int, fh: FileHandle) -> bytes:
        raise FuseOSError(errno.EIO)

    def write(
        self, ino: int, data: bytes, offset: int, fh: FileHandle
    ) -> int | None:
        raise FuseOSError(errno.EROFS)

    def flush(self, ino: int, fh: FileHandle) -> OperationStatus:
        return 0

    def release(self, ino: int, fh: FileHandle) -> OperationStatus:
        return 0

    def fsync(self, ino: int, datasync: int, fh: FileHandle) -> OperationStatus:
        return 0

    def getlk(
        self, ino: int, fh: FileHandle, lock: dict[str, int]
    ) -> dict[str, int] | None:
        """macFUSE VFS 当前不支持 POSIX GETLK；运行时不会注册该回调。"""
        raise FuseOSError(ENOTSUP)

    def setlk(
        self, ino: int, fh: FileHandle, cmd: int, lock: dict[str, int]
    ) -> OperationStatus:
        """macFUSE VFS 当前不支持 POSIX SETLK/SETLKW；运行时不会注册该回调。"""
        raise FuseOSError(ENOTSUP)

    def flock(self, ino: int, fh: FileHandle, op: int) -> OperationStatus:
        raise FuseOSError(ENOTSUP)

    def opendir(
        self, ino: int, flags: int = 0, fi: FileHandle = None
    ) -> OpenResult:
        return 0

    def readdir(
        self, ino: int, offset: int, size: int, fh: FileHandle, flags: int = 0
    ) -> Iterable[LowLevelEntry]:
        raise FuseOSError(errno.ENOTDIR)

    def releasedir(self, ino: int, fh: FileHandle) -> OperationStatus:
        return 0

    def fsyncdir(
        self, ino: int, datasync: int, fh: FileHandle
    ) -> OperationStatus:
        return 0

    def statfs(self, ino: int) -> StatVfsResult:
        return {}

    def setxattr(
        self, ino: int, name: bytes, value: bytes, options: int, position: int
    ) -> OperationStatus:
        raise FuseOSError(ENOTSUP)

    def getxattr(self, ino: int, name: bytes, position: int) -> XAttrValue:
        raise FuseOSError(ENOTSUP)

    def listxattr(self, ino: int) -> Iterable[str | bytes]:
        return []

    def removexattr(self, ino: int, name: bytes) -> OperationStatus:
        raise FuseOSError(ENOTSUP)

    def access(self, ino: int, amode: int) -> OperationStatus:
        return 0

    def create(
        self, parent: int, name: bytes, mode: int, flags: int, fi: FileHandle
    ) -> tuple[LowLevelEntry, OpenResult]:
        raise FuseOSError(errno.EROFS)

    def bmap(self, ino: int, blocksize: int, idx: int) -> object:
        """macFUSE VFS 当前不支持 BMAP；运行时不会注册该回调。"""
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
        raise FuseOSError(errno.ENOTTY)
