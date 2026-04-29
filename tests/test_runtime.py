import errno
import fcntl

from stat import S_IFREG
from typing import cast

import pytest

import macfusepy._runtime as runtime
from macfusepy import (
    FuseOSError,
    InodeOperations,
    Operations,
)
from macfusepy._lowlevel import LowLevelFUSESession
from macfusepy._runtime import (
    _OperationsAdapter,
    _PathOperationsAdapter,
)
from macfusepy.lowlevel_async import LowLevelAttr, LowLevelEntry
from macfusepy.types import FileInfo, IoctlData


def test_operations_adapter_dispatches_sync_methods():
    class SyncFS(Operations):
        def read(self, path, size, offset, fh):
            return path.encode()

    operations = SyncFS()
    adapter = _OperationsAdapter(operations)
    try:
        results = [adapter("read", f"/f{index}", 1, 0, None) for index in range(4)]
    finally:
        adapter.close()

    assert results == [b"/f0", b"/f1", b"/f2", b"/f3"]


def test_operations_adapter_preserves_fuse_errors():
    class SyncFS(Operations):
        def getattr(self, path, fh=None):
            raise FuseOSError(errno.ENOENT)

    adapter = _OperationsAdapter(SyncFS())
    try:
        with pytest.raises(FuseOSError) as exc_info:
            adapter("getattr", "/missing", None)
    finally:
        adapter.close()

    assert exc_info.value.errno == errno.ENOENT


def test_operations_adapter_requires_operations_base_class():
    class PlainFS:
        def getattr(self, path, fh=None):
            return {}

    with pytest.raises(TypeError, match="must inherit macfusepy.Operations"):
        _OperationsAdapter(cast(Operations, PlainFS()))


def test_operations_adapter_rejects_async_operation_methods():
    class AsyncFS(Operations):
        async def getattr(self, path, fh=None):
            return {}

    adapter = _OperationsAdapter(AsyncFS())
    with pytest.raises(
        TypeError, match=r"AsyncFS\.getattr\(\) must be a sync operation"
    ):
        adapter("getattr", "/", None)


def test_path_operations_adapter_preserves_create_signature_without_raw_fi():
    class AsyncFS(Operations):
        def __init__(self):
            self.calls = []

        def __call__(self, op, *args):
            if op == "getattr":
                return {"st_mode": S_IFREG | 0o644, "st_nlink": 1, "st_size": 0}
            if op == "create":
                self.calls.append(args)
                return 7
            return super().__call__(op, *args)

    def exercise():
        operations = AsyncFS()
        adapter = _PathOperationsAdapter(operations, raw_fi=False)
        entry, handle = adapter.create(1, b"created.txt", 0o644, 0, None)
        return operations.calls, entry.name, handle

    calls, name, handle = exercise()

    assert calls == [("/created.txt", 0o644)]
    assert name == b"created.txt"
    assert handle == 7


def test_inode_operations_call_methods_directly():
    class InodeFS(InodeOperations):
        def __init__(self):
            self.calls = []

        def lookup(self, parent, name):
            self.calls.append(("lookup", parent, name))
            attrs = {"st_mode": S_IFREG | 0o644, "st_nlink": 1, "st_size": 3}
            return LowLevelEntry(name, 42, {**attrs, "st_ino": 42}, 1)

        def getattr(self, ino, fh=None):
            self.calls.append(("getattr", ino, fh))
            return {"st_ino": ino, "st_mode": S_IFREG | 0o644, "st_nlink": 1, "st_size": 3}

        def read(self, ino, size, offset, fh):
            self.calls.append(("read", ino, size, offset, fh))
            return b"abc"[offset : offset + size]

    def exercise():
        operations = InodeFS()
        entry = operations.lookup(1, b"direct.txt")
        attrs = operations.getattr(entry.ino)
        data = operations.read(entry.ino, 2, 1, 7)
        return operations.calls, entry, attrs, data

    calls, entry, attrs, data = exercise()

    assert calls == [
        ("lookup", 1, b"direct.txt"),
        ("getattr", 42, None),
        ("read", 42, 2, 1, 7),
    ]
    assert entry.ino == 42
    assert attrs["st_ino"] == 42
    assert data == b"bc"


def test_inode_operations_readdir_receives_size_and_flags():
    class InodeFS(InodeOperations):
        def readdir(self, ino, offset, size, fh, flags=0):
            assert (ino, offset, size, fh, flags) == (1, 3, 4096, 9, 0)
            return ()

    def exercise():
        operations = InodeFS()
        return operations.readdir(1, 3, 4096, 9, 0)

    assert exercise() == ()


def test_inode_operations_opendir_receives_flags_and_file_info():
    class InodeFS(InodeOperations):
        def __init__(self):
            self.calls = []

        def opendir(self, ino, flags=0, fi=None):
            self.calls.append((ino, flags, fi))
            return 7

    info = FileInfo(flags=123)
    operations = InodeFS()

    assert operations.opendir(1, 123, info) == 7
    assert operations.calls == [(1, 123, info)]


def test_path_operations_adapter_forwards_opendir_flags():
    class AsyncFS(Operations):
        def __init__(self):
            self.calls = []

        def opendir(self, path, flags=0):
            self.calls.append((path, flags))
            return 7

    operations = AsyncFS()
    adapter = _PathOperationsAdapter(operations, raw_fi=False)

    assert adapter.opendir(1, 123) == 7
    assert operations.calls == [("/", 123)]


def test_path_operations_adapter_forwards_raw_opendir_file_info():
    class AsyncFS(Operations):
        def __init__(self):
            self.calls = []

        def opendir(self, path, flags=0):
            self.calls.append((path, flags))
            return 7

    info = FileInfo(flags=123)
    operations = AsyncFS()
    adapter = _PathOperationsAdapter(operations, raw_fi=True)

    assert adapter.opendir(1, 123, info) == 7
    assert operations.calls == [("/", info)]


def test_fuse_kernel_permissions_uses_kernel_access_checks(monkeypatch):
    captured = {}

    class FakeSession:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        def close(self):
            captured["closed"] = True

    def fake_serve(self, adapter, session):
        captured["adapter"] = adapter
        captured["session"] = session

    class AsyncFS(Operations):
        pass

    monkeypatch.setattr(runtime, "LowLevelFUSESession", FakeSession)
    monkeypatch.setattr(runtime.FUSE, "_serve", fake_serve)

    runtime.FUSE(
        AsyncFS(),
        "/mnt",
        kernel_permissions=True,
        disabled_operations=("bmap",),
    )

    assert captured["kwargs"]["default_permissions"] is True
    assert captured["kwargs"]["disabled_operations"] == frozenset(
        {"access", "bmap", "getlk", "setlk"}
    )
    assert isinstance(captured["args"][0], _PathOperationsAdapter)
    assert captured["adapter"] is captured["args"][0]
    assert captured["closed"] is True


def test_fuse_uses_inode_operations_directly(monkeypatch):
    captured = {}

    class FakeSession:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        def close(self):
            captured["closed"] = True

    def fake_serve(self, adapter, session):
        captured["adapter"] = adapter
        captured["session"] = session

    class InodeFS(InodeOperations):
        pass

    monkeypatch.setattr(runtime, "LowLevelFUSESession", FakeSession)
    monkeypatch.setattr(runtime.FUSE, "_serve", fake_serve)

    operations = InodeFS()
    runtime.FUSE(operations, "/mnt")

    assert captured["args"][0] is operations
    assert captured["adapter"] is operations
    assert captured["closed"] is True


def test_fuse_threads_option_is_consumed(monkeypatch):
    captured = {}

    class FakeSession:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        def close(self):
            captured["closed"] = True

    def fake_serve(self, adapter, session):
        captured["adapter"] = adapter
        captured["session"] = session

    class InodeFS(InodeOperations):
        pass

    monkeypatch.setattr(runtime, "LowLevelFUSESession", FakeSession)
    monkeypatch.setattr(runtime.FUSE, "_serve", fake_serve)

    operations = InodeFS()
    runtime.FUSE(operations, "/mnt", threads=True)

    assert captured["args"][0] is operations
    assert "threads" not in captured["kwargs"]
    assert captured["closed"] is True


def test_fuse_forwards_loop_config_options(monkeypatch):
    captured = {}

    class FakeSession:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        def close(self):
            captured["closed"] = True

    def fake_serve(self, adapter, session):
        captured["adapter"] = adapter
        captured["session"] = session

    class InodeFS(InodeOperations):
        pass

    monkeypatch.setattr(runtime, "LowLevelFUSESession", FakeSession)
    monkeypatch.setattr(runtime.FUSE, "_serve", fake_serve)

    operations = InodeFS()
    runtime.FUSE(
        operations,
        "/mnt",
        loop_clone_fd=True,
        loop_max_idle_threads=32,
    )

    assert captured["kwargs"]["loop_clone_fd"] is True
    assert captured["kwargs"]["loop_max_idle_threads"] == 32
    assert captured["closed"] is True


def test_fuse_rejects_threads_false():
    class InodeFS(InodeOperations):
        pass

    with pytest.raises(ValueError, match="threads=False is no longer supported"):
        runtime.FUSE(InodeFS(), "/mnt", threads=False)


def test_fuse_rejects_nothreads_option():
    class InodeFS(InodeOperations):
        pass

    with pytest.raises(ValueError, match="nothreads=True is no longer supported"):
        runtime.FUSE(InodeFS(), "/mnt", nothreads=True)


def test_fuse_serve_runs_multithreaded_session_loop():
    events = []

    class FakeSession:
        def run_multithreaded(self):
            events.append("multithreaded")

    class InodeFS(InodeOperations):
        def destroy(self):
            events.append("destroy")

    runtime.FUSE._serve(
        object.__new__(runtime.FUSE),
        InodeFS(),
        cast(LowLevelFUSESession, FakeSession()),
    )

    assert events == ["multithreaded", "destroy"]


def test_path_operations_adapter_preserves_lowlevel_attr_fast_path():
    class AsyncFS(Operations):
        def getattr(self, path, fh=None):
            return LowLevelAttr(st_ino=0, st_mode=S_IFREG | 0o644, st_nlink=1)

    def exercise():
        adapter = _PathOperationsAdapter(AsyncFS())
        entry = adapter.lookup(1, b"fast.txt")
        return entry, adapter.getattr(entry.ino)

    entry, attrs = exercise()

    assert isinstance(entry.attrs, LowLevelAttr)
    assert isinstance(attrs, LowLevelAttr)
    assert entry.attrs.st_ino == entry.ino
    assert attrs.st_ino == entry.ino


def test_path_operations_adapter_invalidates_replaced_rename_target():
    class AsyncFS(Operations):
        def getattr(self, path, fh=None):
            return {"st_mode": S_IFREG | 0o644, "st_nlink": 1, "st_size": 0}

        def rename(self, old, new, flags):
            return 0

    def exercise():
        adapter = _PathOperationsAdapter(AsyncFS())
        source = adapter.lookup(1, b"source.txt")
        replaced = adapter.lookup(1, b"target.txt")
        adapter.rename(1, b"source.txt", 1, b"target.txt", 0)
        moved_attrs = adapter.getattr(source.ino)
        with pytest.raises(FuseOSError) as exc_info:
            adapter.getattr(replaced.ino)
        return moved_attrs["st_ino"], exc_info.value.errno

    moved_ino, replaced_errno = exercise()

    assert moved_ino != 1
    assert replaced_errno == errno.ENOENT


def test_path_operations_adapter_keeps_unlinked_inode_for_handle_ops_until_forget():
    class AsyncFS(Operations):
        def getattr(self, path, fh=None):
            return {"st_mode": S_IFREG | 0o644, "st_nlink": 1, "st_size": 4}

        def unlink(self, path):
            return 0

        def read(self, path, size, offset, fh):
            return path.encode()

    def exercise():
        adapter = _PathOperationsAdapter(AsyncFS())
        entry = adapter.lookup(1, b"open.txt")
        adapter.unlink(1, b"open.txt")
        data = adapter.read(entry.ino, 1024, 0, 99)
        with pytest.raises(FuseOSError) as exc_info:
            adapter.getattr(entry.ino)
        adapter.forget(entry.ino, 1)
        return data, exc_info.value.errno, entry.ino in adapter._records

    data, getattr_errno, record_exists = exercise()

    assert data == b"/open.txt"
    assert getattr_errno == errno.ENOENT
    assert not record_exists


def test_path_operations_adapter_preserves_ioctl_data_object():
    class AsyncFS(Operations):
        def getattr(self, path, fh=None):
            return {"st_mode": S_IFREG | 0o644, "st_nlink": 1, "st_size": 4}

        def ioctl(self, path, cmd, arg, fh, flags, data):
            assert isinstance(data, IoctlData)
            return path, cmd, arg, fh, flags, data.input, data.out_size

    def exercise():
        adapter = _PathOperationsAdapter(AsyncFS())
        entry = adapter.lookup(1, b"ctl")
        return adapter.ioctl(entry.ino, 10, 20, 30, 40, IoctlData(b"input", 8))

    assert exercise() == ("/ctl", 10, 20, 30, 40, b"input", 8)


def test_path_operations_adapter_forwards_posix_locks():
    class AsyncFS(Operations):
        def __init__(self):
            self.calls = []

        def getattr(self, path, fh=None):
            return {"st_mode": S_IFREG | 0o644, "st_nlink": 1, "st_size": 4}

        def lock(self, path, fh, cmd, lock):
            self.calls.append((path, fh, cmd, dict(lock)))
            if cmd == fcntl.F_GETLK:
                lock["l_type"] = fcntl.F_UNLCK
                return lock
            return None

    def exercise():
        operations = AsyncFS()
        adapter = _PathOperationsAdapter(operations)
        entry = adapter.lookup(1, b"locked.txt")
        probe = adapter.getlk(
            entry.ino,
            7,
            {"l_type": fcntl.F_WRLCK, "l_start": 0, "l_len": 10, "l_pid": 0},
        )
        adapter.setlk(
            entry.ino,
            7,
            fcntl.F_SETLK,
            {"l_type": fcntl.F_RDLCK, "l_start": 0, "l_len": 10, "l_pid": 0},
        )
        return operations.calls, probe

    calls, probe = exercise()

    assert calls[0][0:3] == ("/locked.txt", 7, fcntl.F_GETLK)
    assert calls[1][0:3] == ("/locked.txt", 7, fcntl.F_SETLK)
    assert probe["l_type"] == fcntl.F_UNLCK
