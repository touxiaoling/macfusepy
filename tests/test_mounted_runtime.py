import errno
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from stat import S_IFDIR, S_IFREG
from threading import Lock

import pytest

from macfusepy import FuseOSError, Operations


def _read_events(log_path: Path) -> list[dict[str, object]]:
    if not log_path.exists():
        return []
    return [json.loads(line) for line in log_path.read_text().splitlines() if line]


def _wait_for_event(
    log_path: Path, event_name: str, *, timeout: float = 3.0
) -> list[dict[str, object]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        events = _read_events(log_path)
        if any(event["event"] == event_name for event in events):
            return events
        time.sleep(0.05)
    return _read_events(log_path)


class MountedRuntimeProbe(Operations):
    def __init__(self, log_path: Path, *, slow_reads: bool = False):
        self.log_path = log_path
        self.slow_reads = slow_reads
        self.files = {
            "/tracked.txt": b"tracked payload",
            "/nonempty/child.txt": b"child",
            **{
                f"/paged/entry-{index:03}.txt": str(index).encode()
                for index in range(256)
            },
        }
        self.dirs = {"/", "/nonempty", "/paged"}
        self.deleted = set()
        self.handle_data = {}
        self.next_fh = 100
        self.active_reads = 0
        self._handle_lock = Lock()
        self._active_lock = Lock()

    def _record(self, event: str, **fields: object) -> None:
        payload = json.dumps({"event": event, **fields}, sort_keys=True)
        with self.log_path.open("a") as file:
            file.write(f"{payload}\n")

    def _attrs_for(self, path: str) -> dict[str, int]:
        now = time.time_ns()
        if path in self.dirs:
            return {
                "st_mode": S_IFDIR | 0o755,
                "st_nlink": 2,
                "st_size": 0,
                "st_atime": now,
                "st_mtime": now,
                "st_ctime": now,
            }
        if path in self.files and path not in self.deleted:
            return {
                "st_mode": S_IFREG | 0o644,
                "st_nlink": 1,
                "st_size": len(self.files[path]),
                "st_atime": now,
                "st_mtime": now,
                "st_ctime": now,
            }
        raise FuseOSError(errno.ENOENT)

    def _children(self, path: str) -> list[str]:
        prefix = "/" if path == "/" else f"{path}/"
        names = set()
        for directory in self.dirs:
            if directory != path and directory.startswith(prefix):
                remainder = directory.removeprefix(prefix)
                if remainder and "/" not in remainder:
                    names.add(remainder)
        for file_path in self.files:
            if file_path in self.deleted or not file_path.startswith(prefix):
                continue
            remainder = file_path.removeprefix(prefix)
            if remainder and "/" not in remainder:
                names.add(remainder)
        return sorted(names)

    def init(self, conn=None, cfg=None):
        self._record("init")

    def destroy(self):
        self._record("destroy")

    def getattr(self, path, fh=None):
        self._record("getattr", path=path, fh=fh)
        return self._attrs_for(path)

    def open(self, path, flags):
        with self._handle_lock:
            self.next_fh += 1
            fh = self.next_fh
            self.handle_data[fh] = self.files[path]
        self._record("open", path=path, flags=flags, fh=fh)
        return fh

    def read(self, path, size, offset, fh):
        with self._handle_lock:
            data = self.handle_data.get(fh, self.files.get(path, b""))
        with self._active_lock:
            self.active_reads += 1
            active_reads = self.active_reads
        self._record("read", path=path, fh=fh, active=active_reads)
        if self.slow_reads:
            time.sleep(0.05)
        with self._active_lock:
            self.active_reads -= 1
        return data[offset : offset + size]

    def flush(self, path, fh):
        self._record("flush", path=path, fh=fh)

    def release(self, path, fh):
        self._record("release", path=path, fh=fh)
        with self._handle_lock:
            self.handle_data.pop(fh, None)

    def unlink(self, path):
        self._record("unlink", path=path)
        if path not in self.files or path in self.deleted:
            raise FuseOSError(errno.ENOENT)
        self.deleted.add(path)

    def opendir(self, path, flags=0):
        self._record("opendir", path=path, fh=200)
        if path not in self.dirs:
            raise FuseOSError(errno.ENOTDIR)
        return 200

    def readdir(self, path, fh, flags=0):
        self._record("readdir", path=path, fh=fh)
        return [
            (".", self._attrs_for(path), 1),
            ("..", self._attrs_for("/"), 2),
            *[
                (name, self._attrs_for(path.rstrip("/") + "/" + name), index + 3)
                for index, name in enumerate(self._children(path))
            ],
        ]

    def releasedir(self, path, fh):
        self._record("releasedir", path=path, fh=fh)

    def fsyncdir(self, path, datasync, fh):
        self._record("fsyncdir", path=path, datasync=datasync, fh=fh)

    def rmdir(self, path):
        self._record("rmdir", path=path)
        if self._children(path):
            raise FuseOSError(errno.ENOTEMPTY)
        self.dirs.remove(path)

    def create(self, path, mode, fi=None):
        self._record("create", path=path, mode=mode)
        self.files[path] = b""
        return self.open(path, os.O_WRONLY)

    def write(self, path, data, offset, fh):
        self._record("write", path=path, fh=fh, size=len(data))
        current = self.files.get(path, b"")
        self.files[path] = current[:offset] + data + current[offset + len(data) :]
        return len(data)


def test_mounted_runtime_keeps_open_handle_readable_after_unlink(
    tmp_path, mounted_fuse
):
    log_path = tmp_path / "runtime-events.jsonl"
    mountpoint = mounted_fuse(
        MountedRuntimeProbe(log_path), attr_timeout=0, entry_timeout=0
    )
    path = mountpoint / "tracked.txt"

    fd = os.open(path, os.O_RDONLY)
    try:
        os.unlink(path)
        with pytest.raises(FileNotFoundError):
            path.stat()
        assert os.read(fd, 64) == b"tracked payload"
    finally:
        os.close(fd)

    events = _wait_for_event(log_path, "release")
    assert any(
        event["event"] == "open" and event["path"] == "/tracked.txt" for event in events
    )
    assert any(
        event["event"] == "unlink" and event["path"] == "/tracked.txt"
        for event in events
    )
    assert any(
        event["event"] == "read" and event["path"] == "/tracked.txt" for event in events
    )
    assert any(
        event["event"] == "release" and event["path"] == "/tracked.txt"
        for event in events
    )


def test_mounted_runtime_uses_directory_handles_and_stable_offsets(
    tmp_path, mounted_fuse
):
    log_path = tmp_path / "runtime-events.jsonl"
    mountpoint = mounted_fuse(
        MountedRuntimeProbe(log_path), attr_timeout=0, entry_timeout=0
    )
    paged = mountpoint / "paged"

    assert sorted(os.listdir(paged)) == [
        f"entry-{index:03}.txt" for index in range(256)
    ]

    dir_fd = os.open(paged, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)

    events = _wait_for_event(log_path, "releasedir")
    assert any(
        event["event"] == "opendir" and event["path"] == "/paged" and event["fh"] == 200
        for event in events
    )
    assert any(
        event["event"] == "readdir" and event["path"] == "/paged" and event["fh"] == 200
        for event in events
    )
    assert any(
        event["event"] == "fsyncdir"
        and event["path"] == "/paged"
        and event["fh"] == 200
        for event in events
    )
    assert any(
        event["event"] == "releasedir"
        and event["path"] == "/paged"
        and event["fh"] == 200
        for event in events
    )


def test_mounted_runtime_maps_python_errno_to_real_syscalls(tmp_path, mounted_fuse):
    log_path = tmp_path / "runtime-events.jsonl"
    mountpoint = mounted_fuse(
        MountedRuntimeProbe(log_path), attr_timeout=0, entry_timeout=0
    )

    with pytest.raises(NotADirectoryError) as not_dir:
        os.listdir(mountpoint / "tracked.txt")
    assert not_dir.value.errno == errno.ENOTDIR

    with pytest.raises(OSError) as not_empty:
        os.rmdir(mountpoint / "nonempty")
    assert not_empty.value.errno == errno.ENOTEMPTY

    events = _read_events(log_path)
    assert any(
        event["event"] == "getattr" and event["path"] == "/tracked.txt"
        for event in events
    )
    assert any(
        event["event"] == "rmdir" and event["path"] == "/nonempty" for event in events
    )


def test_mounted_runtime_honors_readonly_mount_option(tmp_path, mounted_fuse):
    log_path = tmp_path / "runtime-events.jsonl"
    mountpoint = mounted_fuse(
        MountedRuntimeProbe(log_path), ro=True, attr_timeout=0, entry_timeout=0
    )

    with pytest.raises(OSError) as exc_info:
        (mountpoint / "created.txt").write_bytes(b"blocked")

    assert exc_info.value.errno == errno.EROFS
    assert not any(event["event"] == "create" for event in _read_events(log_path))


def test_mounted_runtime_allows_parallel_sync_user_reads(tmp_path, mounted_fuse):
    log_path = tmp_path / "runtime-events.jsonl"
    mountpoint = mounted_fuse(
        MountedRuntimeProbe(log_path, slow_reads=True), attr_timeout=0, entry_timeout=0
    )
    paths = [
        mountpoint / "tracked.txt",
        *[mountpoint / "paged" / f"entry-{index:03}.txt" for index in range(8)],
    ]

    with ThreadPoolExecutor(max_workers=len(paths)) as executor:
        results = list(executor.map(lambda path: path.read_bytes(), paths))

    assert results[0] == b"tracked payload"
    assert results[1:] == [str(index).encode() for index in range(8)]
    active_counts = [
        active
        for event in _read_events(log_path)
        if isinstance(active := event.get("active"), int)
    ]
    assert max(active_counts) > 1
