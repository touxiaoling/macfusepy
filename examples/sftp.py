#!/usr/bin/env python3

import logging
import paramiko  # type: ignore[unresolved-import]

from threading import Lock
from errno import EINVAL, ENOENT

from macfusepy import FUSE, FuseOSError, Operations, LoggingMixIn


class SFTP(LoggingMixIn, Operations):
    """简单的 SFTP 文件系统。需要 Paramiko：https://www.paramiko.org/

    这个示例把 FUSE 文件操作转发给远程主机的 SFTP 服务。Paramiko 是同步库，所以
    回调会在同步 FUSE 热路径中直接调用 Paramiko，并用 ``threading.Lock``
    保守串行化同一个 SFTP 客户端；生产实现通常应换成连接池。
    """

    def __init__(self, host, username=None, port=22):
        self._lock = Lock()
        self.client = paramiko.SSHClient()
        self.client.load_system_host_keys()
        self.client.connect(host, port=port, username=username)
        self.sftp = self.client.open_sftp()

    def chmod(self, path, mode, fh=None):
        with self._lock:
            return self.sftp.chmod(path, mode)

    def chown(self, path, uid, gid, fh=None):
        with self._lock:
            return self.sftp.chown(path, uid, gid)

    def create(self, path, mode, fi=None):
        with self._lock:
            self._create_sync(path, mode)
        return 0

    def destroy(self):
        with self._lock:
            self._destroy_sync()

    def getattr(self, path, fh=None):
        with self._lock:
            return self._getattr_sync(path)

    def mkdir(self, path, mode):
        with self._lock:
            return self.sftp.mkdir(path, mode)

    def read(self, path, size, offset, fh):
        with self._lock:
            return self._read_sync(path, size, offset)

    def readdir(self, path, fh, flags=0):
        with self._lock:
            return [".", ".."] + self.sftp.listdir(path)

    def readlink(self, path):
        with self._lock:
            return self.sftp.readlink(path)

    def rename(self, old, new, flags):
        if flags:
            raise FuseOSError(EINVAL)
        with self._lock:
            return self.sftp.rename(old, new)

    def rmdir(self, path):
        with self._lock:
            return self.sftp.rmdir(path)

    def symlink(self, target, source):
        with self._lock:
            return self.sftp.symlink(source, target)

    def truncate(self, path, length, fh=None):
        with self._lock:
            return self.sftp.truncate(path, length)

    def unlink(self, path):
        with self._lock:
            return self.sftp.unlink(path)

    def utimens(self, path, times, fh):
        if times is not None:
            atime, mtime = times
            converted_times = (atime / 1_000_000_000, mtime / 1_000_000_000)
        else:
            converted_times = None
        with self._lock:
            return self.sftp.utime(path, converted_times)

    def write(self, path, data, offset, fh):
        with self._lock:
            self._write_sync(path, data, offset)
        return len(data)

    def _create_sync(self, path, mode):
        with self.sftp.open(path, "w") as f:
            f.chmod(mode)

    def _destroy_sync(self):
        self.sftp.close()
        self.client.close()

    def _getattr_sync(self, path):
        try:
            st = self.sftp.lstat(path)
        except IOError:
            raise FuseOSError(ENOENT)
        attrs = {
            key: getattr(st, key) for key in ("st_gid", "st_mode", "st_size", "st_uid")
        }
        attrs["st_atime"] = int((st.st_atime or 0) * 1_000_000_000)
        attrs["st_mtime"] = int((st.st_mtime or 0) * 1_000_000_000)
        return attrs

    def _read_sync(self, path, size, offset):
        with self.sftp.open(path) as f:
            f.seek(offset, 0)
            return f.read(size)

    def _write_sync(self, path, data, offset):
        with self.sftp.open(path, "r+") as f:
            f.seek(offset, 0)
            f.write(data)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("-l", dest="login")
    parser.add_argument("host")
    parser.add_argument("mount")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG)

    if not args.login:
        if "@" in args.host:
            args.login, _, args.host = args.host.partition("@")

    FUSE(
        SFTP(args.host, username=args.login),
        args.mount,
        foreground=True,
        allow_other=True,
    )
