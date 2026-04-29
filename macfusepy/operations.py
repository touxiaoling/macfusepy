"""操作基类和相关类型的兼容导入路径。"""

from macfusepy.inode_operations import InodeOperations
from macfusepy.path_operations import (
    DirEntry,
    DirEntryName,
    FileHandle,
    IoctlValue,
    LoggingMixIn,
    OpenResult,
    OperationStatus,
    Operations,
    StatResult,
    StatVfsResult,
    TimespecPair,
    XAttrValue,
)


__all__: tuple[str, ...] = (
    "DirEntry",
    "DirEntryName",
    "FileHandle",
    "InodeOperations",
    "IoctlValue",
    "LoggingMixIn",
    "OpenResult",
    "OperationStatus",
    "Operations",
    "StatResult",
    "StatVfsResult",
    "TimespecPair",
    "XAttrValue",
)
