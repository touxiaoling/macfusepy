#!/usr/bin/env python3

import ctypes
import logging
import struct

from collections import defaultdict
from errno import ENOENT, ENOTTY
from stat import S_IFDIR, S_IFREG
from time import time_ns

from macfusepy import FUSE, FuseOSError, IoctlData, Operations, LoggingMixIn


_IOC_IN = 0x80000000
_IOC_OUT = 0x40000000
_IOCPARM_MASK = 0x1FFF


def _iowr(group, number, ctype):
    """按 macOS ``_IOWR`` 宏编码 ioctl 命令号，避免依赖额外 Python 包。"""
    size = ctypes.sizeof(ctype) & _IOCPARM_MASK
    return _IOC_IN | _IOC_OUT | (size << 16) | (group << 8) | number


M_IOWR = _iowr(ord("M"), 1, ctypes.c_uint32)


class Ioctl(LoggingMixIn, Operations):
    """基于 ``memory.py`` 的示例文件系统，用于演示 ``ioctl``。

    普通文件系统很少需要实现 ``ioctl``。当用户进程对文件描述符调用
    ``fcntl.ioctl`` 或 C 语言的 ``ioctl(2)`` 时，libfuse 会把命令号和数据缓冲区
    指针交给这个回调。这里约定一个自定义命令：读取 4 字节无符号整数，给它加
    1，再写回同一个缓冲区。

    注意：当前 macFUSE 5.2/libfuse3 真实挂载路径不会把这个普通文件上的自定义
    ``_IOWR('M', 1, uint32_t)`` 请求转发给高层 ``ioctl`` 回调，客户端会直接收到
    ``ENOTTY``。下面的用法保留为接口示例，相关集成测试以 xfail 记录该行为。

    用法::

        mkdir test

        python ioctl.py test
        touch test/test

        gcc -o ioctl_test ioctl.c
        ./ioctl_test 100 test/test
    """

    def __init__(self):
        self.files = {}
        self.data = defaultdict(bytes)
        self.fd = 0
        now = time_ns()
        self.files["/"] = dict(
            st_mode=(S_IFDIR | 0o755),
            st_ctime=now,
            st_mtime=now,
            st_atime=now,
            st_nlink=2,
        )

    def create(self, path, mode, fi=None):
        now = time_ns()
        self.files[path] = dict(
            st_mode=(S_IFREG | mode),
            st_nlink=1,
            st_size=0,
            st_ctime=now,
            st_mtime=now,
            st_atime=now,
        )

        self.fd += 1
        return self.fd

    def getattr(self, path, fh=None):
        if path not in self.files:
            raise FuseOSError(ENOENT)

        return self.files[path]

    def ioctl(self, path, cmd, arg, fh, flags, data):
        if cmd == M_IOWR:
            if isinstance(data, IoctlData):
                data_in = struct.unpack("<I", data.input[:4])[0]
                return struct.pack("<I", data_in + 1)
            inbuf = ctypes.create_string_buffer(4)
            ctypes.memmove(inbuf, data, 4)
            data_in = struct.unpack("<I", inbuf.raw)[0]
            data_out = data_in + 1
            outbuf = struct.pack("<I", data_out)
            ctypes.memmove(data, outbuf, 4)
        else:
            raise FuseOSError(ENOTTY)
        return 0

    def open(self, path, flags):
        self.fd += 1
        return self.fd

    def read(self, path, size, offset, fh):
        return self.data[path][offset : offset + size]

    def readdir(self, path, fh, flags=0):
        return [".", ".."] + [x[1:] for x in self.files if x != "/"]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("mount")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG)
    FUSE(Ioctl(), args.mount, foreground=True, allow_other=True)
