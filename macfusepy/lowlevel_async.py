"""low-level FUSE 支撑（内部，非整体公开 API）。

- 公开运行时只使用 libfuse 的多线程 low-level session loop。
- inode-based 只读树原型见 ``macfusepy._readonly_async_tree``。
"""

from __future__ import annotations

import os

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import ClassVar


ROOT_INODE = 1


@dataclass(frozen=True, slots=True)
class LowLevelAttr(Mapping[str, int]):
    """面向 low-level 回复的轻量 ``stat`` 属性对象。"""

    st_ino: int
    st_mode: int
    st_nlink: int
    st_uid: int = 0
    st_gid: int = 0
    st_rdev: int = 0
    st_size: int = 0
    st_blocks: int = 0
    st_blksize: int = 0
    st_flags: int = 0
    st_atime: int = 0
    st_mtime: int = 0
    st_ctime: int = 0
    st_birthtime: int = 0

    _KEYS: ClassVar[tuple[str, ...]] = (
        "st_ino",
        "st_mode",
        "st_nlink",
        "st_uid",
        "st_gid",
        "st_rdev",
        "st_size",
        "st_blocks",
        "st_blksize",
        "st_flags",
        "st_atime",
        "st_mtime",
        "st_ctime",
        "st_birthtime",
    )

    def __getitem__(self, key: str) -> int:
        if key in self._KEYS:
            return getattr(self, key)
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(self._KEYS)

    def __len__(self) -> int:
        return len(self._KEYS)


class LowLevelError(OSError):
    """low-level 原型内部使用的 errno 异常。"""

    def __init__(self, errno_value: int) -> None:
        super().__init__(errno_value, os.strerror(errno_value))
        self.errno = errno_value


@dataclass(frozen=True, slots=True)
class LowLevelEntry:
    """只读 low-level 原型中的目录项。"""

    name: bytes
    ino: int
    attrs: Mapping[str, int] | LowLevelAttr
    next_id: int
