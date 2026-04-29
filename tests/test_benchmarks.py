"""真实挂载性能基准。

默认测试套件会跳过本文件中的 benchmark；只跑 benchmark 用：
uv run pytest --run-benchmarks -m benchmark tests/test_benchmarks.py
"""

import errno
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from stat import S_IFDIR, S_IFREG
from threading import Lock

import pytest

from examples.loopback import Loopback
from examples.memory import Memory
from macfusepy import FuseOSError, InodeOperations, Operations
from macfusepy._lowlevel import FUSE_SET_ATTR_SIZE
from macfusepy._runtime import _PathOperationsAdapter
from macfusepy.lowlevel_async import ROOT_INODE, LowLevelEntry


PAYLOAD = b"x" * 4096
ENTRY_COUNT = 32
CONCURRENCY = 8
SLOW_IO_DELAY = 0.002
WRITE_PAYLOAD_SIZES = (4096, 65536, 1048576)


@dataclass
class BenchmarkCase:
    run: Callable[[], object]
    cleanup: Callable[[], None] = lambda: None


class SlowMemory(Memory):
    """用阻塞 sleep 模拟错误写法中的远程存储延迟。"""

    def read(self, path, size, offset, fh):
        time.sleep(SLOW_IO_DELAY)
        return super().read(path, size, offset, fh)

    def write(self, path, data, offset, fh):
        time.sleep(SLOW_IO_DELAY)
        return super().write(path, data, offset, fh)


class ThreadedSlowMemory(Memory):
    """用阻塞 sleep 模拟另一个慢速 FUSE 后端。"""

    def read(self, path, size, offset, fh):
        time.sleep(SLOW_IO_DELAY)
        return super().read(path, size, offset, fh)

    def write(self, path, data, offset, fh):
        time.sleep(SLOW_IO_DELAY)
        return super().write(path, data, offset, fh)


class MountedInodeBenchmarkFS(InodeOperations):
    """真实挂载基准使用的最小 inode-first 内存文件系统。"""

    def __init__(self) -> None:
        self._lock = Lock()
        self._next_ino = ROOT_BENCH_INO
        self._names: dict[bytes, int] = {}
        self._data: dict[int, bytearray] = {}

    def _attrs(self, ino: int) -> dict[str, int]:
        if ino == ROOT_INODE:
            return {"st_ino": ino, "st_mode": S_IFDIR | 0o755, "st_nlink": 2}
        return {
            "st_ino": ino,
            "st_mode": S_IFREG | 0o644,
            "st_nlink": 1,
            "st_size": len(self._data[ino]),
        }

    def _entry(self, name: bytes, ino: int, next_id: int = 0) -> LowLevelEntry:
        return LowLevelEntry(name, ino, self._attrs(ino), next_id or ino)

    def _create_file(self, name: bytes) -> LowLevelEntry:
        ino = self._names.get(name)
        if ino is None:
            ino = self._next_ino
            self._next_ino += 1
            self._names[name] = ino
            self._data[ino] = bytearray()
        return self._entry(name, ino)

    def lookup(self, parent, name):
        if parent != ROOT_INODE:
            raise FuseOSError(errno.ENOENT)
        with self._lock:
            try:
                return self._entry(name, self._names[name])
            except KeyError as exc:
                raise FuseOSError(errno.ENOENT) from exc

    def getattr(self, ino, fh=None):
        with self._lock:
            if ino != ROOT_INODE and ino not in self._data:
                raise FuseOSError(errno.ENOENT)
            return self._attrs(ino)

    def setattr(self, ino, attrs, to_set, fh=None):
        with self._lock:
            if ino not in self._data:
                raise FuseOSError(errno.ENOENT)
            if to_set & FUSE_SET_ATTR_SIZE:
                size = attrs["st_size"]
                data = self._data[ino]
                if size < len(data):
                    del data[size:]
                elif size > len(data):
                    data.extend(b"\0" * (size - len(data)))
            return self._attrs(ino)

    def create(self, parent, name, mode, flags, fi):
        if parent != ROOT_INODE:
            raise FuseOSError(errno.ENOENT)
        with self._lock:
            entry = self._create_file(name)
            if flags & os.O_TRUNC:
                self._data[entry.ino].clear()
            return entry, entry.ino

    def mknod(self, parent, name, mode, dev):
        if parent != ROOT_INODE:
            raise FuseOSError(errno.ENOENT)
        with self._lock:
            return self._create_file(name)

    def unlink(self, parent, name):
        if parent != ROOT_INODE:
            raise FuseOSError(errno.ENOENT)
        with self._lock:
            try:
                ino = self._names.pop(name)
            except KeyError as exc:
                raise FuseOSError(errno.ENOENT) from exc
            self._data.pop(ino, None)
        return 0

    def open(self, ino, flags, fi=None):
        with self._lock:
            if ino not in self._data:
                raise FuseOSError(errno.ENOENT)
        return ino

    def read(self, ino, size, offset, fh):
        with self._lock:
            data = self._data[ino]
            return bytes(data[offset : offset + size])

    def write(self, ino, data, offset, fh):
        with self._lock:
            file_data = self._data[ino]
            end = offset + len(data)
            if end > len(file_data):
                file_data.extend(b"\0" * (end - len(file_data)))
            file_data[offset:end] = data
        return len(data)

    def readdir(self, ino, offset, size, fh, flags=0):
        if ino != ROOT_INODE:
            raise FuseOSError(errno.ENOTDIR)
        with self._lock:
            entries = tuple(self._names.items())
            return tuple(
                self._entry(name, child_ino, index + 1)
                for index, (name, child_ino) in enumerate(
                    entries[int(offset) :], int(offset)
                )
            )


class NoopWriteInodeBenchmarkFS(MountedInodeBenchmarkFS):
    """只确认 write 数据已进入 Python，不再写入后端存储。"""

    def write(self, ino, data, offset, fh):
        with self._lock:
            if ino not in self._data:
                raise FuseOSError(errno.ENOENT)
        return len(data)


def _seed_directory(root: Path) -> None:
    for index in range(ENTRY_COUNT):
        (root / f"entry-{index}.bin").write_bytes(PAYLOAD)


def _path_case(operation: str, root: Path) -> BenchmarkCase:
    path = root / "file.bin"
    fh = os.open(path, os.O_RDWR)

    def cleanup():
        os.close(fh)

    if operation == "getattr":
        return BenchmarkCase(lambda: os.lstat(path), cleanup)

    if operation == "read_4k":
        def read_file():
            os.lseek(fh, 0, os.SEEK_SET)
            return os.read(fh, len(PAYLOAD))

        return BenchmarkCase(read_file, cleanup)

    if operation == "overwrite_4k":
        def overwrite_file():
            os.lseek(fh, 0, os.SEEK_SET)
            return os.write(fh, PAYLOAD)

        return BenchmarkCase(overwrite_file, cleanup)

    if operation == "create_write_unlink_4k":
        filenames = count()

        def create_write_unlink_file():
            file_path = root / f"created-{next(filenames)}.bin"
            new_fh = os.open(file_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
            try:
                os.write(new_fh, PAYLOAD)
            finally:
                os.close(new_fh)
            os.unlink(file_path)

        return BenchmarkCase(create_write_unlink_file, cleanup)

    if operation == "readdir_32_entries":
        return BenchmarkCase(lambda: os.listdir(root), cleanup)

    if operation == "concurrent_read_4k":
        executor = ThreadPoolExecutor(max_workers=CONCURRENCY)

        def concurrent_read():
            return list(executor.map(lambda _index: path.read_bytes(), range(CONCURRENCY)))

        def cleanup_concurrent_read():
            executor.shutdown(wait=True)
            cleanup()

        return BenchmarkCase(concurrent_read, cleanup_concurrent_read)

    if operation == "concurrent_overwrite_4k":
        paths = [root / f"worker-{index}.bin" for index in range(CONCURRENCY)]
        for worker_path in paths:
            worker_path.write_bytes(PAYLOAD)
        executor = ThreadPoolExecutor(max_workers=CONCURRENCY)

        def overwrite(worker_path: Path):
            with worker_path.open("r+b", buffering=0) as file:
                return file.write(PAYLOAD)

        def concurrent_overwrite():
            return list(executor.map(overwrite, paths))

        def cleanup_concurrent_overwrite():
            executor.shutdown(wait=True)
            for worker_path in paths:
                worker_path.unlink(missing_ok=True)
            cleanup()

        return BenchmarkCase(concurrent_overwrite, cleanup_concurrent_overwrite)

    cleanup()
    raise ValueError(operation)


def _mounted_memory_case(operation: str, _tmp_path: Path, mounted_fuse: Callable[..., Path]) -> BenchmarkCase:
    root = mounted_fuse(Memory())
    (root / "file.bin").write_bytes(PAYLOAD)
    _seed_directory(root)
    return _path_case(operation, root)


def _mounted_loopback_case(operation: str, tmp_path: Path, mounted_fuse: Callable[..., Path]) -> BenchmarkCase:
    loopback_root = tmp_path / "loopback"
    loopback_root.mkdir()
    root = mounted_fuse(Loopback(loopback_root))
    (root / "file.bin").write_bytes(PAYLOAD)
    _seed_directory(root)
    return _path_case(operation, root)


def _mounted_slow_memory_case(operation: str, _tmp_path: Path, mounted_fuse: Callable[..., Path]) -> BenchmarkCase:
    root = mounted_fuse(SlowMemory())
    (root / "file.bin").write_bytes(PAYLOAD)
    _seed_directory(root)
    return _path_case(operation, root)


def _mounted_threaded_slow_memory_case(operation: str, _tmp_path: Path, mounted_fuse: Callable[..., Path]) -> BenchmarkCase:
    root = mounted_fuse(ThreadedSlowMemory())
    (root / "file.bin").write_bytes(PAYLOAD)
    _seed_directory(root)
    return _path_case(operation, root)


def _mounted_inode_case(operation: str, _tmp_path: Path, mounted_fuse: Callable[..., Path]) -> BenchmarkCase:
    root = mounted_fuse(MountedInodeBenchmarkFS())
    (root / "file.bin").write_bytes(PAYLOAD)
    _seed_directory(root)
    return _path_case(operation, root)


def _native_case(operation: str, tmp_path: Path, _mounted_fuse: Callable[..., Path]) -> BenchmarkCase:
    root = tmp_path / "native"
    root.mkdir()
    (root / "file.bin").write_bytes(PAYLOAD)
    _seed_directory(root)
    return _path_case(operation, root)


def _overwrite_payload_case(root: Path, payload: bytes) -> BenchmarkCase:
    path = root / "file.bin"
    fh = os.open(path, os.O_RDWR)

    def cleanup():
        os.close(fh)

    def overwrite_file():
        os.lseek(fh, 0, os.SEEK_SET)
        return os.write(fh, payload)

    return BenchmarkCase(overwrite_file, cleanup)


BACKENDS: dict[str, Callable[[str, Path, Callable[..., Path]], BenchmarkCase]] = {
    "mounted-memory": _mounted_memory_case,
    "mounted-inode": _mounted_inode_case,
    "mounted-loopback": _mounted_loopback_case,
    "mounted-slow-memory": _mounted_slow_memory_case,
    "mounted-threaded-slow-memory": _mounted_threaded_slow_memory_case,
    "native": _native_case,
}

OPERATIONS = (
    "getattr",
    "read_4k",
    "overwrite_4k",
    "create_write_unlink_4k",
    "readdir_32_entries",
    "concurrent_read_4k",
    "concurrent_overwrite_4k",
)


@pytest.mark.parametrize("backend", BACKENDS, ids=str)
@pytest.mark.parametrize("operation", OPERATIONS, ids=str)
@pytest.mark.benchmark(group="mounted-filesystems")
def test_filesystem_backend_benchmark(benchmark, tmp_path, mounted_fuse, backend, operation):
    """对比真实挂载路径和不经过 FUSE 的原生文件系统操作成本。"""
    case = BACKENDS[backend](operation, tmp_path, mounted_fuse)
    benchmark.extra_info["backend"] = backend
    benchmark.extra_info["operation"] = operation

    try:
        benchmark(case.run)
    finally:
        case.cleanup()


@pytest.mark.parametrize("payload_size", WRITE_PAYLOAD_SIZES, ids=lambda size: f"{size // 1024}k")
@pytest.mark.parametrize(
    "backend",
    ["mounted-inode-store", "mounted-inode-noop", "native"],
    ids=str,
)
@pytest.mark.benchmark(group="inode-write-payload-size")
def test_inode_write_payload_size_benchmark(
    benchmark, tmp_path, mounted_fuse, backend, payload_size
):
    """观察 write 延迟是否主要随 libfuse 输入 buffer 复制成本增长。"""
    payload = b"x" * payload_size
    if backend == "native":
        root = tmp_path / "native-write-size"
        root.mkdir()
    else:
        fs = (
            MountedInodeBenchmarkFS()
            if backend == "mounted-inode-store"
            else NoopWriteInodeBenchmarkFS()
        )
        root = mounted_fuse(fs)
    (root / "file.bin").write_bytes(payload)
    case = _overwrite_payload_case(root, payload)
    benchmark.extra_info["backend"] = backend
    benchmark.extra_info["payload_size"] = payload_size

    try:
        benchmark(case.run)
    finally:
        case.cleanup()


class PathAdapterBenchmarkFS(Operations):
    def getattr(self, path, fh=None):
        return {"st_mode": 0o100644, "st_nlink": 1, "st_size": len(path)}

    def read(self, path, size, offset, fh):
        return b"x" * size


class InodeAdapterBenchmarkFS(InodeOperations):
    def lookup(self, parent, name):
        ino = int(name.rsplit(b"-", 1)[-1]) + ROOT_BENCH_INO
        attrs = {"st_ino": ino, "st_mode": 0o100644, "st_nlink": 1, "st_size": 1}
        return LowLevelEntry(name, ino, attrs, ino)

    def getattr(self, ino, fh=None):
        return {"st_ino": ino, "st_mode": 0o100644, "st_nlink": 1, "st_size": 1}

    def read(self, ino, size, offset, fh):
        return b"x" * size

    def readdir(self, ino, offset, size, fh, flags=0):
        return tuple(
            LowLevelEntry(
                f"entry-{index}".encode(),
                ROOT_BENCH_INO + index,
                {
                    "st_ino": ROOT_BENCH_INO + index,
                    "st_mode": 0o100644,
                    "st_nlink": 1,
                    "st_size": 1,
                },
                index + 1,
            )
            for index in range(offset, offset + 64)
        )


ROOT_BENCH_INO = 1000


@pytest.mark.parametrize("adapter_name", ["path", "inode"], ids=str)
@pytest.mark.benchmark(group="adapter-overhead")
def test_lowlevel_adapter_microbenchmark(benchmark, adapter_name):
    def run_path_adapter():
        adapter = _PathOperationsAdapter(PathAdapterBenchmarkFS())
        for index in range(64):
            entry = adapter.lookup(1, f"entry-{index}".encode())
            adapter.getattr(entry.ino)
            adapter.read(entry.ino, 1, 0, 0)
        adapter.readdir(1, 0, 4096, 0, 0)

    def run_inode_adapter():
        adapter = InodeAdapterBenchmarkFS()
        for index in range(64):
            entry = adapter.lookup(1, f"entry-{index}".encode())
            adapter.getattr(entry.ino)
            adapter.read(entry.ino, 1, 0, 0)
        adapter.readdir(1, 0, 4096, 0, 0)

    runner = run_inode_adapter if adapter_name == "inode" else run_path_adapter
    benchmark(runner)
