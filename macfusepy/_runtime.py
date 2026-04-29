"""同步挂载运行时。"""

from __future__ import annotations

import errno
import fcntl
import posixpath

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, replace
from stat import S_IFDIR
from typing import Any, cast

from macfusepy._lowlevel import (
    FUSE_SET_ATTR_ATIME,
    FUSE_SET_ATTR_GID,
    FUSE_SET_ATTR_MODE,
    FUSE_SET_ATTR_MTIME,
    FUSE_SET_ATTR_SIZE,
    FUSE_SET_ATTR_UID,
    LowLevelFUSESession,
)
from macfusepy.errors import FuseOSError
from macfusepy.lowlevel_async import (
    LowLevelAttr,
    LowLevelEntry,
    ROOT_INODE,
)
from macfusepy.operations import (
    FileHandle,
    InodeOperations,
    IoctlValue,
    OpenResult,
    OperationStatus,
    Operations,
)
from macfusepy.types import FileInfo


_UNSUPPORTED_MACFUSE_OPERATIONS = frozenset({"getlk", "setlk", "bmap"})


class _OperationsAdapter:
    """内部测试和示例使用的同步 path 操作分发器。"""

    def __init__(self, operations: Operations) -> None:
        if not isinstance(operations, Operations):
            raise TypeError("FUSE operations must inherit macfusepy.Operations")
        self._operations = operations

    def __call__(self, op: str, *args: object) -> object:
        return self._operations(op, *args)

    def close(self) -> None:
        pass


@dataclass(slots=True)
class _InodeRecord:
    ino: int
    path: str
    parent: int
    name: bytes
    lookup_count: int = 0
    linked: bool = True


class _PathOperationsAdapter(InodeOperations):
    """用 inode-first 接口承载 path-based ``Operations``。"""

    def __init__(
        self, operations: Operations, *, raw_fi: bool = False, encoding: str = "utf-8"
    ) -> None:
        if not isinstance(operations, Operations):
            raise TypeError("FUSE operations must inherit macfusepy.Operations")
        self._operations = operations
        self.raw_fi = raw_fi
        self.encoding = encoding
        self._next_ino = ROOT_INODE + 1
        self._records: dict[int, _InodeRecord] = {
            ROOT_INODE: _InodeRecord(ROOT_INODE, "/", ROOT_INODE, b"", lookup_count=1),
        }
        self._paths: dict[str, int] = {"/": ROOT_INODE}

    def init(self, conn: object = None, cfg: object = None) -> None:
        self._operations("init", conn, cfg)

    def destroy(self) -> None:
        self._operations("destroy")

    def _call(self, op: str, *args: object) -> object:
        return self._operations(op, *args)

    def _decode(self, name: bytes) -> str:
        return name.decode(self.encoding)

    def _join(self, parent: int, name: bytes) -> str:
        parent_path = self._path(parent)
        child = self._decode(name)
        if parent_path == "/":
            return f"/{child}"
        return posixpath.join(parent_path, child)

    def _path(self, ino: int, *, allow_unlinked: bool = False) -> str:
        try:
            record = self._records[ino]
        except KeyError as exc:
            raise FuseOSError(errno.ENOENT) from exc
        if not record.linked and not allow_unlinked:
            raise FuseOSError(errno.ENOENT)
        return record.path

    def _parent_path(self, path: str) -> str:
        parent = posixpath.dirname(path.rstrip("/"))
        return parent or "/"

    def _remember(
        self,
        path: str,
        *,
        parent: int | None = None,
        name: bytes | None = None,
    ) -> int:
        if path in self._paths:
            return self._paths[path]
        ino = self._next_ino
        self._next_ino += 1
        if parent is None:
            parent_path = self._parent_path(path)
            parent = self._paths.get(parent_path, ROOT_INODE)
        if name is None:
            name = posixpath.basename(path).encode(self.encoding)
        self._paths[path] = ino
        self._records[ino] = _InodeRecord(ino, path, parent, name)
        return ino

    def _prune_record(self, ino: int) -> None:
        record = self._records.get(ino)
        if record is None or ino == ROOT_INODE:
            return
        if not record.linked and record.lookup_count == 0:
            self._records.pop(ino, None)

    def _forget_path(self, path: str, *, invalidate_records: bool = False) -> None:
        for child_path, child_ino in list(self._paths.items()):
            if child_path == path or child_path.startswith(path.rstrip("/") + "/"):
                self._paths.pop(child_path, None)
                record = self._records.get(child_ino)
                if record is not None and invalidate_records:
                    record.linked = False
                self._prune_record(child_ino)

    def _move_path(self, old: str, new: str) -> None:
        updates = []
        self._forget_path(new, invalidate_records=True)
        for path, ino in self._paths.items():
            if path == old or path.startswith(old.rstrip("/") + "/"):
                updates.append((path, ino, new + path[len(old) :]))
        for path, ino, new_path in updates:
            self._paths.pop(path, None)
            self._paths[new_path] = ino
            record = self._records[ino]
            record.path = new_path
            record.name = posixpath.basename(new_path).encode(self.encoding)
            record.parent = self._paths.get(self._parent_path(new_path), ROOT_INODE)
            record.linked = True

    def _attrs(self, ino: int, attrs: Mapping[str, int]) -> Mapping[str, int]:
        if isinstance(attrs, LowLevelAttr):
            return attrs if attrs.st_ino == ino else replace(attrs, st_ino=ino)
        result = dict(attrs)
        result["st_ino"] = ino
        return result

    def _entry_for_path(
        self, path: str, *, parent: int | None = None, name: bytes | None = None
    ) -> LowLevelEntry:
        attrs = cast(Mapping[str, int], self._call("getattr", path, None))
        ino = self._remember(path, parent=parent, name=name)
        return LowLevelEntry(
            name or posixpath.basename(path).encode(self.encoding),
            ino,
            self._attrs(ino, attrs),
            ino,
        )

    def _entry_from_attrs(
        self, path: str, name: bytes, attrs: Mapping[str, int], *, parent: int
    ) -> LowLevelEntry:
        ino = self._remember(path, parent=parent, name=name)
        return LowLevelEntry(name, ino, self._attrs(ino, attrs), ino)

    def lookup(self, parent: int, name: bytes) -> LowLevelEntry:
        path = self._join(parent, name)
        entry = self._entry_for_path(path, parent=parent, name=name)
        self._records[entry.ino].lookup_count += 1
        return entry

    def forget(self, ino: int, nlookup: int) -> None:
        record = self._records.get(ino)
        if record is None or ino == ROOT_INODE:
            return
        record.lookup_count = max(0, record.lookup_count - nlookup)
        self._prune_record(ino)

    def getattr(self, ino: int, fh: object = None) -> Mapping[str, int]:
        attrs = cast(
            Mapping[str, int],
            self._call(
                "getattr", self._path(ino, allow_unlinked=fh is not None), fh
            ),
        )
        return self._attrs(ino, attrs)

    def setattr(
        self, ino: int, attrs: Mapping[str, int], to_set: int, fh: object = None
    ) -> Mapping[str, int]:
        path = self._path(ino, allow_unlinked=fh is not None)
        if to_set & FUSE_SET_ATTR_MODE:
            self._call("chmod", path, attrs["st_mode"], fh)
        if to_set & (FUSE_SET_ATTR_UID | FUSE_SET_ATTR_GID):
            uid = attrs["st_uid"] if to_set & FUSE_SET_ATTR_UID else -1
            gid = attrs["st_gid"] if to_set & FUSE_SET_ATTR_GID else -1
            self._call("chown", path, uid, gid, fh)
        if to_set & FUSE_SET_ATTR_SIZE:
            self._call("truncate", path, attrs["st_size"], fh)
        if to_set & (FUSE_SET_ATTR_ATIME | FUSE_SET_ATTR_MTIME):
            current = self.getattr(ino, fh)
            atime = (
                attrs["st_atime"]
                if to_set & FUSE_SET_ATTR_ATIME
                else current.get("st_atime", 0)
            )
            mtime = (
                attrs["st_mtime"]
                if to_set & FUSE_SET_ATTR_MTIME
                else current.get("st_mtime", 0)
            )
            self._call("utimens", path, (atime, mtime), fh)
        return self.getattr(ino, fh)

    def readlink(self, ino: int) -> bytes | str:
        return cast(bytes | str, self._call("readlink", self._path(ino)))

    def mknod(
        self, parent: int, name: bytes, mode: int, dev: int
    ) -> LowLevelEntry:
        path = self._join(parent, name)
        attrs = self._call("mknod", path, mode, dev)
        if isinstance(attrs, Mapping):
            return self._entry_from_attrs(
                path, name, cast(Mapping[str, int], attrs), parent=parent
            )
        return self._entry_for_path(path, parent=parent, name=name)

    def mkdir(self, parent: int, name: bytes, mode: int) -> LowLevelEntry:
        path = self._join(parent, name)
        attrs = self._call("mkdir", path, mode)
        if isinstance(attrs, Mapping):
            return self._entry_from_attrs(
                path, name, cast(Mapping[str, int], attrs), parent=parent
            )
        return self._entry_for_path(path, parent=parent, name=name)

    def unlink(self, parent: int, name: bytes) -> None:
        path = self._join(parent, name)
        self._call("unlink", path)
        self._forget_path(path, invalidate_records=True)

    def rmdir(self, parent: int, name: bytes) -> None:
        path = self._join(parent, name)
        self._call("rmdir", path)
        self._forget_path(path, invalidate_records=True)

    def symlink(self, link: bytes, parent: int, name: bytes) -> LowLevelEntry:
        path = self._join(parent, name)
        attrs = self._call("symlink", path, self._decode(link))
        if isinstance(attrs, Mapping):
            return self._entry_from_attrs(
                path, name, cast(Mapping[str, int], attrs), parent=parent
            )
        return self._entry_for_path(path, parent=parent, name=name)

    def rename(
        self, parent: int, name: bytes, newparent: int, newname: bytes, flags: int
    ) -> None:
        old = self._join(parent, name)
        new = self._join(newparent, newname)
        self._call("rename", old, new, flags)
        self._move_path(old, new)

    def link(self, ino: int, newparent: int, newname: bytes) -> LowLevelEntry:
        source = self._path(ino)
        target = self._join(newparent, newname)
        self._call("link", target, source)
        return self._entry_for_path(target, parent=newparent, name=newname)

    def open(self, ino: int, flags: int, fi: FileHandle = None) -> OpenResult:
        return cast(
            OpenResult,
            self._call("open", self._path(ino), fi if self.raw_fi else flags),
        )

    def read(self, ino: int, size: int, offset: int, fh: object) -> bytes:
        return cast(
            bytes,
            self._call(
                "read", self._path(ino, allow_unlinked=True), size, offset, fh
            ),
        )

    def write(self, ino: int, data: bytes, offset: int, fh: object) -> int | None:
        return cast(
            int | None,
            self._call(
                "write", self._path(ino, allow_unlinked=True), data, offset, fh
            ),
        )

    def flush(self, ino: int, fh: FileHandle) -> OperationStatus:
        return cast(
            OperationStatus,
            self._call("flush", self._path(ino, allow_unlinked=True), fh),
        )

    def release(self, ino: int, fh: FileHandle) -> OperationStatus:
        return cast(
            OperationStatus,
            self._call("release", self._path(ino, allow_unlinked=True), fh),
        )

    def fsync(self, ino: int, datasync: int, fh: FileHandle) -> OperationStatus:
        return cast(
            OperationStatus,
            self._call(
                "fsync", self._path(ino, allow_unlinked=True), datasync, fh
            ),
        )

    def getlk(
        self, ino: int, fh: FileHandle, lock: dict[str, int]
    ) -> dict[str, int] | None:
        return cast(
            dict[str, int] | None,
            self._call(
                "lock",
                self._path(ino, allow_unlinked=True),
                fh,
                fcntl.F_GETLK,
                dict(lock),
            ),
        )

    def setlk(
        self, ino: int, fh: FileHandle, cmd: int, lock: dict[str, int]
    ) -> OperationStatus:
        return cast(
            OperationStatus,
            self._call(
                "lock", self._path(ino, allow_unlinked=True), fh, cmd, dict(lock)
            ),
        )

    def flock(self, ino: int, fh: FileHandle, op: int) -> OperationStatus:
        if op & fcntl.LOCK_UN:
            lock_type = fcntl.F_UNLCK
        elif op & fcntl.LOCK_EX:
            lock_type = fcntl.F_WRLCK
        else:
            lock_type = fcntl.F_RDLCK
        cmd = (
            fcntl.F_SETLK
            if op & fcntl.LOCK_NB
            else getattr(fcntl, "F_SETLKW", fcntl.F_SETLK)
        )
        lock = {
            "l_type": lock_type,
            "l_whence": 0,
            "l_start": 0,
            "l_len": 0,
            "l_pid": 0,
        }
        return cast(
            OperationStatus,
            self._call(
                "lock", self._path(ino, allow_unlinked=True), fh, cmd, lock
            ),
        )

    def opendir(
        self, ino: int, flags: int = 0, fi: FileHandle = None
    ) -> OpenResult:
        return cast(
            OpenResult,
            self._call(
                "opendir",
                self._path(ino),
                fi if self.raw_fi else flags,
            ),
        )

    def readdir(
        self, ino: int, offset: int, size: int = 0, fh: object = None, flags: int = 0
    ) -> Iterable[LowLevelEntry]:
        path = self._path(ino)
        items = cast(Iterable[object], self._call("readdir", path, fh, flags))
        entries = []
        next_id = 1
        for item in items:
            name, attrs, explicit_offset = self._parse_dir_entry(item)
            if name in (b".", b".."):
                entry_ino = ino if name == b"." else self._records[ino].parent
                entry_path = self._path(entry_ino)
            else:
                entry_path = self._join(ino, name)
                entry_ino = self._remember(entry_path, parent=ino, name=name)
            if attrs is None:
                try:
                    attrs = cast(
                        Mapping[str, int], self._call("getattr", entry_path, None)
                    )
                except FuseOSError:
                    attrs = (
                        {"st_mode": S_IFDIR | 0o755, "st_nlink": 2}
                        if name in (b".", b"..")
                        else {}
                    )
            next_id = explicit_offset or next_id
            entry = LowLevelEntry(
                name, entry_ino, self._attrs(entry_ino, attrs), next_id
            )
            if entry.next_id > offset:
                entries.append(entry)
            next_id += 1
        return tuple(entries)

    def _parse_dir_entry(
        self, item: object
    ) -> tuple[bytes, Mapping[str, int] | None, int]:
        attrs: Mapping[str, int] | None = None
        next_offset: object = 0
        if isinstance(item, tuple):
            if len(item) == 3:
                name = item[0]
                attrs = cast(Mapping[str, int] | None, item[1])
                next_offset = item[2]
            elif len(item) == 2:
                name = item[0]
                attrs = cast(Mapping[str, int] | None, item[1])
            else:
                name = item[0]
        else:
            name = item
        encoded = (
            name.encode(self.encoding) if isinstance(name, str) else cast(bytes, name)
        )
        return encoded, attrs, int(cast(Any, next_offset))

    def releasedir(self, ino: int, fh: FileHandle) -> OperationStatus:
        return cast(
            OperationStatus,
            self._call("releasedir", self._path(ino, allow_unlinked=True), fh),
        )

    def fsyncdir(
        self, ino: int, datasync: int, fh: FileHandle
    ) -> OperationStatus:
        return cast(
            OperationStatus,
            self._call(
                "fsyncdir", self._path(ino, allow_unlinked=True), datasync, fh
            ),
        )

    def statfs(self, ino: int) -> Mapping[str, int]:
        return cast(Mapping[str, int], self._call("statfs", self._path(ino)))

    def setxattr(
        self, ino: int, name: bytes, value: bytes, options: int, position: int
    ) -> OperationStatus:
        return cast(
            OperationStatus,
            self._call(
                "setxattr", self._path(ino), self._decode(name), value, options, position
            ),
        )

    def getxattr(self, ino: int, name: bytes, position: int) -> bytes | str:
        return cast(
            bytes | str,
            self._call("getxattr", self._path(ino), self._decode(name), position),
        )

    def listxattr(self, ino: int) -> Iterable[str | bytes]:
        return cast(
            Iterable[str | bytes], self._call("listxattr", self._path(ino))
        )

    def removexattr(self, ino: int, name: bytes) -> OperationStatus:
        return cast(
            OperationStatus,
            self._call("removexattr", self._path(ino), self._decode(name)),
        )

    def access(self, ino: int, amode: int) -> OperationStatus:
        return cast(OperationStatus, self._call("access", self._path(ino), amode))

    def create(
        self, parent: int, name: bytes, mode: int, flags: int, fi: FileHandle
    ) -> tuple[LowLevelEntry, OpenResult]:
        path = self._join(parent, name)
        if self.raw_fi:
            result = self._call("create", path, mode, FileInfo(flags=flags))
        else:
            result = self._call("create", path, mode)
        attrs = None
        handle = result
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], Mapping):
            handle, attrs = result
        if attrs is not None:
            return (
                self._entry_from_attrs(
                    path, name, cast(Mapping[str, int], attrs), parent=parent
                ),
                cast(OpenResult, handle),
            )
        return (
            self._entry_for_path(path, parent=parent, name=name),
            cast(OpenResult, handle),
        )

    def bmap(self, ino: int, blocksize: int, idx: int) -> object:
        return self._call("bmap", self._path(ino), blocksize, idx)

    def ioctl(
        self, ino: int, cmd: int, arg: int, fh: FileHandle, flags: int, data: object
    ) -> IoctlValue:
        return cast(
            IoctlValue,
            self._call("ioctl", self._path(ino), cmd, arg, fh, flags, data),
        )


def _as_inode_operations(
    operations: InodeOperations | Operations, *, raw_fi: bool, encoding: str
) -> InodeOperations:
    if isinstance(operations, InodeOperations):
        return operations
    if isinstance(operations, Operations):
        return _PathOperationsAdapter(operations, raw_fi=raw_fi, encoding=encoding)
    raise TypeError("FUSE operations must inherit macfusepy.InodeOperations or Operations")


class FUSE:
    """启动一个 macFUSE/libfuse3 low-level 挂载会话。"""

    OPTIONS: tuple[tuple[str, str], ...] = (
        ("foreground", "-f"),
        ("debug", "-d"),
    )

    def __init__(
        self,
        operations: InodeOperations | Operations,
        mountpoint: str,
        raw_fi: bool = False,
        encoding: str = "utf-8",
        **kwargs: object,
    ) -> None:
        kwargs.setdefault("fsname", operations.__class__.__name__)
        if kwargs.pop("threads", True) is False:
            raise ValueError("threads=False is no longer supported")
        if kwargs.pop("nothreads", False):
            raise ValueError("nothreads=True is no longer supported")
        for option, _ in self.OPTIONS:
            kwargs.pop(option, None)
        disabled_operations = set(cast(Any, kwargs.pop("disabled_operations", ())))
        disabled_operations.update(_UNSUPPORTED_MACFUSE_OPERATIONS)
        if kwargs.pop("kernel_permissions", False):
            kwargs["default_permissions"] = True
            disabled_operations.add("access")
        inode_operations = _as_inode_operations(
            operations, raw_fi=raw_fi, encoding=encoding
        )
        attr_timeout = float(cast(Any, kwargs.pop("attr_timeout", 1.0)))
        entry_timeout = float(cast(Any, kwargs.pop("entry_timeout", 1.0)))
        session = LowLevelFUSESession(
            inode_operations,
            mountpoint,
            raw_fi=raw_fi,
            encoding=encoding,
            attr_timeout=attr_timeout,
            entry_timeout=entry_timeout,
            disabled_operations=frozenset(disabled_operations),
            **kwargs,
        )
        try:
            self._serve(inode_operations, session)
        finally:
            session.close()

    def _serve(self, operations: InodeOperations, session: LowLevelFUSESession) -> None:
        try:
            session.run_multithreaded()
        finally:
            operations.destroy()

    @staticmethod
    def _normalize_fuse_options(**options: object) -> Iterator[str]:
        for key, value in options.items():
            if isinstance(value, bool):
                if value:
                    yield key
            else:
                yield f"{key}={value}"
