import errno
import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from examples.memory import Memory
from macfusepy._runtime import _OperationsAdapter


@contextmanager
def adapted(operations: Any) -> Iterator[Any]:
    adapter = _OperationsAdapter(operations)
    try:
        yield adapter
    finally:
        adapter.close()


def test_memory_example_uses_nanosecond_timestamps():
    with adapted(Memory()) as fs:
        attrs = fs("getattr", "/")

    assert isinstance(attrs["st_atime"], int)
    assert attrs["st_atime"] > 10**18


def test_memory_example_creates_reads_writes_and_truncates_files():
    with adapted(Memory()) as fs:
        fh = fs("create", "/hello.txt", 0o644)
        assert fh == 1
        assert fs("write", "/hello.txt", b"hello", 0, fh) == 5
        assert fs("write", "/hello.txt", b"!", 5, fh) == 1
        assert fs("read", "/hello.txt", 64, 0, fh) == b"hello!"
        assert fs("getattr", "/hello.txt")["st_size"] == 6

        fs("write", "/hello.txt", b"y", 2, fh)
        assert fs("read", "/hello.txt", 64, 0, fh) == b"heylo!"

        fs("truncate", "/hello.txt", 8)
        assert fs("read", "/hello.txt", 64, 0, fh) == b"heylo!\x00\x00"
        assert fs("getattr", "/hello.txt")["st_size"] == 8


def test_memory_example_updates_modes_owners_and_statfs():
    with adapted(Memory()) as fs:
        fs("create", "/file.txt", 0o600)

        fs("chmod", "/file.txt", 0o644)
        fs("chown", "/file.txt", 501, 20)

        attrs = fs("getattr", "/file.txt")
        assert fs("statfs", "/") == {"f_bsize": 512, "f_blocks": 4096, "f_bavail": 2048}
    assert attrs["st_mode"] & 0o777 == 0o644
    assert attrs["st_uid"] == 501
    assert attrs["st_gid"] == 20


def test_memory_example_open_returns_incrementing_handles():
    with adapted(Memory()) as fs:
        fs("create", "/file.txt", 0o644)

        assert fs("open", "/file.txt", 0) == 2
        assert fs("open", "/file.txt", 0) == 3


def test_memory_example_updates_directory_entries_and_links():
    with adapted(Memory()) as fs:
        fs("mkdir", "/docs", 0o755)
        fs("symlink", "/latest", "docs")

        assert fs("getattr", "/")["st_nlink"] == 3
        assert sorted(fs("readdir", "/", None)) == [".", "..", "docs", "latest"]
        assert fs("readlink", "/latest") == "docs"

        fs("rmdir", "/docs")
        assert fs("getattr", "/")["st_nlink"] == 2
        assert "docs" not in fs("readdir", "/", None)


def test_memory_example_supports_nested_directories(assert_fuse_errno):
    with adapted(Memory()) as fs:
        fs("mkdir", "/docs", 0o755)
        fs("mkdir", "/docs/archive", 0o755)
        fh = fs("create", "/docs/archive/note.txt", 0o644)
        fs("write", "/docs/archive/note.txt", b"nested", 0, fh)
        fs("symlink", "/docs/archive/latest", "note.txt")

        assert sorted(fs("readdir", "/", None)) == [".", "..", "docs"]
        assert sorted(fs("readdir", "/docs", None)) == [".", "..", "archive"]
        assert sorted(fs("readdir", "/docs/archive", None)) == [
            ".",
            "..",
            "latest",
            "note.txt",
        ]
        assert fs("read", "/docs/archive/note.txt", 64, 0, fh) == b"nested"
        assert fs("readlink", "/docs/archive/latest") == "note.txt"
        assert fs("getattr", "/")["st_nlink"] == 3
        assert fs("getattr", "/docs")["st_nlink"] == 3

        assert_fuse_errno(lambda: fs("rmdir", "/docs"), errno.ENOTEMPTY)
        assert_fuse_errno(
            lambda: fs("readdir", "/docs/archive/note.txt", None), errno.ENOTDIR
        )


def test_memory_example_renames_nested_directory_subtrees(assert_fuse_errno):
    with adapted(Memory()) as fs:
        fs("mkdir", "/docs", 0o755)
        fs("mkdir", "/docs/archive", 0o755)
        fs("mkdir", "/target", 0o755)
        fh = fs("create", "/docs/archive/note.txt", 0o644)
        fs("write", "/docs/archive/note.txt", b"data", 0, fh)

        fs("rename", "/docs/archive", "/target/archive", 0)

        assert_fuse_errno(lambda: fs("getattr", "/docs/archive"), errno.ENOENT)
        assert fs("read", "/target/archive/note.txt", 64, 0, fh) == b"data"
        assert sorted(fs("readdir", "/docs", None)) == [".", ".."]
        assert sorted(fs("readdir", "/target", None)) == [".", "..", "archive"]
        assert fs("getattr", "/docs")["st_nlink"] == 2
        assert fs("getattr", "/target")["st_nlink"] == 3


def test_memory_example_renames_and_unlinks_files(assert_fuse_errno):
    with adapted(Memory()) as fs:
        fh = fs("create", "/old.txt", 0o644)
        fs("write", "/old.txt", b"data", 0, fh)

        fs("rename", "/old.txt", "/new.txt", 0)

        assert_fuse_errno(lambda: fs("getattr", "/old.txt"), errno.ENOENT)
        assert fs("read", "/new.txt", 64, 0, fh) == b"data"

        fs("unlink", "/new.txt")
        assert_fuse_errno(lambda: fs("getattr", "/new.txt"), errno.ENOENT)
        assert_fuse_errno(
            lambda: fs("rename", "/missing.txt", "/other.txt", 0), errno.ENOENT
        )
        assert_fuse_errno(
            lambda: fs("rename", "/missing.txt", "/other.txt", 1), errno.EINVAL
        )


def test_memory_example_extended_attributes():
    with adapted(Memory()) as fs:
        fs("create", "/file.txt", 0o644)

        fs("setxattr", "/file.txt", "com.example.key", b"value", 0, 0)

        assert list(fs("listxattr", "/file.txt")) == ["com.example.key"]
        assert fs("getxattr", "/file.txt", "com.example.key", 0) == b"value"

        fs("removexattr", "/file.txt", "com.example.key")
        assert list(fs("listxattr", "/file.txt")) == []


def test_memory_example_missing_xattr_returns_errno(assert_fuse_errno):
    with adapted(Memory()) as fs:
        fs("create", "/file.txt", 0o644)

        assert_fuse_errno(
            lambda: fs("getxattr", "/file.txt", "com.example.missing", 0),
            errno.ENOATTR,
        )
        assert_fuse_errno(
            lambda: fs("removexattr", "/file.txt", "com.example.missing"),
            errno.ENOATTR,
        )


def test_memory_example_works_when_mounted(mounted_fuse):
    mountpoint = mounted_fuse(Memory())
    path = mountpoint / "hello.txt"

    path.write_bytes(b"hello")
    with path.open("ab") as file:
        file.write(b"!")

    assert path.read_bytes() == b"hello!"
    assert path.stat().st_size == 6

    with path.open("r+b") as file:
        file.seek(2)
        file.write(b"y")

    assert path.read_bytes() == b"heylo!"
    os.truncate(path, 8)
    assert path.read_bytes() == b"heylo!\x00\x00"

    subprocess.run(
        ["/usr/bin/xattr", "-w", "com.example.key", "value", os.fspath(path)],
        check=True,
    )
    result = subprocess.run(
        ["/usr/bin/xattr", "-p", "com.example.key", os.fspath(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == "value\n"
    subprocess.run(
        ["/usr/bin/xattr", "-d", "com.example.key", os.fspath(path)], check=True
    )

    renamed = mountpoint / "renamed.txt"
    path.rename(renamed)
    assert sorted(os.listdir(mountpoint)) == ["renamed.txt"]
    renamed.unlink()
    assert os.listdir(mountpoint) == []


def test_memory_example_handles_directories_links_and_metadata_when_mounted(
    mounted_fuse,
):
    mountpoint = mounted_fuse(Memory())
    docs = mountpoint / "docs"
    docs.mkdir()

    assert docs.is_dir()
    assert sorted(os.listdir(mountpoint)) == ["docs"]

    link = mountpoint / "latest"
    link.symlink_to("docs")
    assert os.readlink(link) == "docs"
    assert link.lstat().st_size == len("docs")

    path = mountpoint / "note.txt"
    path.write_bytes(b"abc")
    path.chmod(0o600)
    os.utime(path, ns=(123_000_000_000, 456_000_000_000))

    attrs = path.stat()
    assert attrs.st_mode & 0o777 == 0o600
    assert attrs.st_atime_ns == 123_000_000_000
    assert attrs.st_mtime_ns == 456_000_000_000
    statvfs = os.statvfs(mountpoint)
    assert statvfs.f_frsize == 512
    assert statvfs.f_blocks == 4096
    assert statvfs.f_bavail == 2048

    link.unlink()
    docs.rmdir()
    path.unlink()
    assert os.listdir(mountpoint) == []


def test_memory_example_returns_real_errno_when_mounted(mounted_fuse):
    mountpoint = mounted_fuse(Memory())

    with pytest.raises(FileNotFoundError) as exc_info:
        (mountpoint / "missing.txt").read_bytes()

    assert exc_info.value.errno == errno.ENOENT


def test_memory_example_utimens_uses_supplied_or_current_nanoseconds():
    with adapted(Memory()) as fs:
        fs("create", "/file.txt", 0o644)

        fs("utimens", "/file.txt", (123_000_000_000, 456_000_000_000), 1)
        attrs = fs("getattr", "/file.txt")
        assert attrs["st_atime"] == 123_000_000_000
        assert attrs["st_mtime"] == 456_000_000_000

        fs("utimens", "/file.txt", None, 1)
        attrs = fs("getattr", "/file.txt")
        assert attrs["st_atime"] > 10**18
        assert attrs["st_mtime"] > 10**18


def test_memory_example_handles_concurrent_mutations_on_event_loop():
    with adapted(Memory()) as fs:

        def create_write(index):
            path = f"/file-{index}.txt"
            data = f"data-{index}".encode()
            fh = fs("create", path, 0o644)
            fs("write", path, data, 0, fh)
            return fh

        with ThreadPoolExecutor(max_workers=8) as executor:
            handles = list(executor.map(create_write, range(32)))

        assert sorted(handles) == list(range(1, 33))
        expected_entries = [".", "..", *[f"file-{index}.txt" for index in range(32)]]
        assert sorted(fs("readdir", "/", None)) == sorted(expected_entries)
        for index in range(32):
            assert (
                fs("read", f"/file-{index}.txt", 32, 0, None)
                == f"data-{index}".encode()
            )
