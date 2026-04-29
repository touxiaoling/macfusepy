"""最小 inode-based 只读文件系统原型（内部测试与对比用，非公开 API）。"""

from __future__ import annotations

import errno
import os

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from stat import S_IFDIR, S_IFMT, S_IFREG

from macfusepy.lowlevel_async import (
    LowLevelAttr,
    LowLevelEntry,
    LowLevelError,
    ROOT_INODE,
)


@dataclass(frozen=True, slots=True)
class _Node:
    ino: int
    attrs: LowLevelAttr
    data: bytes = b""
    entries: tuple[LowLevelEntry, ...] = ()

    @property
    def is_dir(self) -> bool:
        return S_IFMT(self.attrs["st_mode"]) == S_IFDIR

    @property
    def is_file(self) -> bool:
        return S_IFMT(self.attrs["st_mode"]) == S_IFREG


class ReadOnlyAsyncTree:
    """最小 inode-based 只读文件系统原型。"""

    def __init__(self, files: Mapping[str | bytes, bytes]) -> None:
        now = 0
        nodes: dict[int, _Node] = {}
        entries: list[LowLevelEntry] = []

        for index, (name, data) in enumerate(files.items(), start=ROOT_INODE + 1):
            encoded_name = name.encode("utf-8") if isinstance(name, str) else name
            attrs = LowLevelAttr(
                st_ino=index,
                st_mode=S_IFREG | 0o444,
                st_nlink=1,
                st_size=len(data),
                st_atime=now,
                st_mtime=now,
                st_ctime=now,
            )
            nodes[index] = _Node(index, attrs, data=data)
            entries.append(LowLevelEntry(encoded_name, index, attrs, next_id=index))

        root_attrs = LowLevelAttr(
            st_ino=ROOT_INODE,
            st_mode=S_IFDIR | 0o555,
            st_nlink=2,
            st_atime=now,
            st_mtime=now,
            st_ctime=now,
        )
        nodes[ROOT_INODE] = _Node(ROOT_INODE, root_attrs, entries=tuple(entries))
        self._nodes = nodes
        self._root_entries = {entry.name: entry for entry in entries}

    def _node(self, ino: int) -> _Node:
        try:
            return self._nodes[ino]
        except KeyError as exc:
            raise LowLevelError(errno.ENOENT) from exc

    def lookup(self, parent: int, name: bytes) -> LowLevelEntry:
        node = self._node(parent)
        if not node.is_dir:
            raise LowLevelError(errno.ENOTDIR)
        if parent == ROOT_INODE:
            try:
                return self._root_entries[name]
            except KeyError as exc:
                raise LowLevelError(errno.ENOENT) from exc
        for entry in node.entries:
            if entry.name == name:
                return entry
        raise LowLevelError(errno.ENOENT)

    def forget(self, ino: int, nlookup: int) -> None:
        self._node(ino)

    def getattr(self, ino: int) -> Mapping[str, int]:
        return self._node(ino).attrs

    def open(self, ino: int, flags: int) -> int:
        node = self._node(ino)
        if node.is_dir:
            raise LowLevelError(errno.EISDIR)
        if (flags & os.O_ACCMODE) != os.O_RDONLY:
            raise LowLevelError(errno.EROFS)
        return ino

    def read(self, ino: int, size: int, offset: int, fh: int) -> bytes:
        node = self._node(ino)
        if not node.is_file:
            raise LowLevelError(errno.EISDIR)
        return node.data[offset : offset + size]

    def readdir(self, ino: int, start_id: int = 0) -> Iterable[LowLevelEntry]:
        node = self._node(ino)
        if not node.is_dir:
            raise LowLevelError(errno.ENOTDIR)
        return tuple(entry for entry in node.entries if entry.next_id > start_id)

    def release(self, ino: int, fh: int) -> None:
        self._node(ino)
