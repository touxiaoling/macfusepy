"""操作基类和相关类型的兼容导入路径。"""

from macfusepy.inode_operations import InodeOperations
from macfusepy.path_operations import (
    CreateResult,
    DirEntry,
    DirEntryName,
    FileHandle,
    IoctlValue,
    LoggingMixIn,
    OpenResult,
    OperationStatus,
    Operations,
    PathEntryAttrsResult,
    StatResult,
    StatVfsResult,
    TimespecPair,
    XAttrValue,
)


__all__: tuple[str, ...] = (
    "CreateResult",
    "DirEntry",
    "DirEntryName",
    "FileHandle",
    "InodeOperations",
    "IoctlValue",
    "LoggingMixIn",
    "OpenResult",
    "OperationStatus",
    "Operations",
    "PathEntryAttrsResult",
    "StatResult",
    "StatVfsResult",
    "TimespecPair",
    "XAttrValue",
)
