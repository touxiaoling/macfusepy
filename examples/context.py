#!/usr/bin/env python3

import logging

from errno import ENOENT
from stat import S_IFDIR, S_IFREG
from time import time_ns

from macfusepy import FUSE, FuseOSError, Operations, LoggingMixIn, fuse_get_context


class Context(LoggingMixIn, Operations):
    """展示如何读取当前 FUSE 请求的调用者身份。

    这个文件系统只暴露三个只读文件：``/uid``、``/gid`` 和 ``/pid``。每次
    ``getattr`` 或 ``read`` 回调发生时，libfuse 都会把发起请求的进程身份放在
    当前回调上下文里，``fuse_get_context()`` 可以把它取出来。
    """

    def getattr(self, path, fh=None):
        uid, gid, pid = fuse_get_context()
        if path == "/":
            st = dict(st_mode=(S_IFDIR | 0o755), st_nlink=2)
        elif path == "/uid":
            size = len("%s\n" % uid)
            st = dict(st_mode=(S_IFREG | 0o444), st_size=size)
        elif path == "/gid":
            size = len("%s\n" % gid)
            st = dict(st_mode=(S_IFREG | 0o444), st_size=size)
        elif path == "/pid":
            size = len("%s\n" % pid)
            st = dict(st_mode=(S_IFREG | 0o444), st_size=size)
        else:
            raise FuseOSError(ENOENT)
        st["st_ctime"] = st["st_mtime"] = st["st_atime"] = time_ns()
        return st

    def read(self, path, size, offset, fh):
        uid, gid, pid = fuse_get_context()

        def encoded(x):
            return f"{x}\n".encode("utf-8")

        if path == "/uid":
            data = encoded(uid)
        elif path == "/gid":
            data = encoded(gid)
        elif path == "/pid":
            data = encoded(pid)
        else:
            raise FuseOSError(ENOENT)

        # read 回调必须尊重 offset 和 size；内核可能分多次读取同一个文件。
        return data[offset : offset + size]

    def readdir(self, path, fh, flags=0):
        if path != "/":
            raise FuseOSError(ENOENT)
        return [".", "..", "uid", "gid", "pid"]

    # 保留 open/opendir/release/releasedir 的默认实现；真实挂载路径会调用它们。
    getxattr = None
    listxattr = None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("mount")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG)
    FUSE(Context(), args.mount, foreground=True, ro=True, allow_other=True)
