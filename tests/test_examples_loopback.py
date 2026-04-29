import errno
import os
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor

import pytest

from examples.loopback import Loopback
from macfusepy._runtime import _OperationsAdapter


@contextmanager
def adapted(operations):
    adapter = _OperationsAdapter(operations)
    try:
        yield adapter
    finally:
        adapter.close()


def test_loopback_example_maps_paths_and_uses_nanoseconds(tmp_path):
    with adapted(Loopback(tmp_path)) as fs:
        write_fh = fs("create", "/note.txt", 0o644)
        try:
            assert fs("write", "/note.txt", b"hello", 0, write_fh) == 5
        finally:
            fs("release", "/note.txt", write_fh)

        read_fh = fs("open", "/note.txt", os.O_RDONLY)
        try:
            assert fs("read", "/note.txt", 5, 0, read_fh) == b"hello"

            attrs = fs("getattr", "/note.txt")
            assert isinstance(attrs, dict)
            assert attrs["st_size"] == 5
            assert isinstance(attrs["st_mtime"], int)
            assert attrs["st_mtime"] > 10**18
            entries = fs("readdir", "/", None)
            assert isinstance(entries, list)
            assert "note.txt" in entries
        finally:
            fs("release", "/note.txt", read_fh)


def test_loopback_example_works_when_mounted(tmp_path, mounted_fuse):
    root = tmp_path / "root"
    root.mkdir()
    (root / "old.txt").write_bytes(b"data")

    mountpoint = mounted_fuse(Loopback(root))
    note = mountpoint / "old.txt"

    note.write_bytes(b"hello")
    assert (root / "old.txt").read_bytes() == b"hello"
    assert note.read_bytes() == b"hello"

    os.truncate(note, 3)
    assert (root / "old.txt").read_bytes() == b"hel"

    (mountpoint / "old.txt").rename(mountpoint / "new.txt")
    assert not (root / "old.txt").exists()
    assert (root / "new.txt").read_bytes() == b"hel"
    assert os.listdir(mountpoint) == ["new.txt"]


def test_loopback_example_handles_links_directories_and_metadata_when_mounted(
    tmp_path, mounted_fuse
):
    root = tmp_path / "root"
    root.mkdir()
    (root / "file.txt").write_bytes(b"data")

    mountpoint = mounted_fuse(Loopback(root))
    note = mountpoint / "file.txt"
    docs = mountpoint / "docs"
    docs.mkdir()

    note.chmod(0o600)
    os.utime(note, ns=(123_000_000_000, 456_000_000_000))
    attrs = (root / "file.txt").stat()
    assert attrs.st_mode & 0o777 == 0o600
    assert attrs.st_atime_ns == 123_000_000_000
    assert attrs.st_mtime_ns == 456_000_000_000

    symlink = mountpoint / "shortcut.txt"
    symlink.symlink_to("file.txt")
    assert os.readlink(root / "shortcut.txt") == "file.txt"
    assert symlink.read_bytes() == b"data"

    hardlink = mountpoint / "hard.txt"
    os.link(note, hardlink)
    assert (root / "hard.txt").read_bytes() == b"data"
    assert os.stat(root / "hard.txt").st_ino == os.stat(root / "file.txt").st_ino

    assert os.statvfs(mountpoint).f_bsize > 0

    hardlink.unlink()
    symlink.unlink()
    docs.rmdir()
    assert sorted(os.listdir(mountpoint)) == ["file.txt"]


def test_loopback_example_returns_real_errno_when_mounted(tmp_path, mounted_fuse):
    root = tmp_path / "root"
    root.mkdir()
    mountpoint = mounted_fuse(Loopback(root))

    with pytest.raises(FileNotFoundError) as exc_info:
        (mountpoint / "missing.txt").read_bytes()

    assert exc_info.value.errno == errno.ENOENT


def test_loopback_example_rejects_rename_flags(tmp_path, assert_fuse_errno):
    (tmp_path / "old.txt").write_bytes(b"data")

    with adapted(Loopback(tmp_path)) as fs:
        assert_fuse_errno(lambda: fs("rename", "/old.txt", "/new.txt", 1), errno.EINVAL)


def test_loopback_example_renames_paths_under_root(tmp_path):
    (tmp_path / "old.txt").write_bytes(b"data")

    with adapted(Loopback(tmp_path)) as fs:
        fs("rename", "/old.txt", "/new.txt", 0)

    assert not (tmp_path / "old.txt").exists()
    assert (tmp_path / "new.txt").read_bytes() == b"data"


def test_loopback_example_mutates_filesystem_metadata(tmp_path):
    path = tmp_path / "file.txt"
    path.write_bytes(b"abcdef")

    with adapted(Loopback(tmp_path)) as fs:
        assert fs("access", "/file.txt", os.R_OK) is None
        fs("chmod", "/file.txt", 0o600)
        fs("truncate", "/file.txt", 3, None)
        fs("utimens", "/file.txt", (1_000_000_000, 2_000_000_000), None)

        attrs = fs("getattr", "/file.txt")
        assert isinstance(attrs, dict)
        statfs = fs("statfs", "/")
        assert isinstance(statfs, dict)
        assert statfs["f_bsize"] > 0
    assert attrs["st_mode"] & 0o777 == 0o600
    assert attrs["st_size"] == 3
    assert attrs["st_atime"] == 1_000_000_000
    assert attrs["st_mtime"] == 2_000_000_000
    assert path.read_bytes() == b"abc"


def test_loopback_example_links_paths_under_root(tmp_path):
    (tmp_path / "file.txt").write_bytes(b"data")

    with adapted(Loopback(tmp_path)) as fs:
        fs("symlink", "/link.txt", "file.txt")
        fs("link", "/hard.txt", "/file.txt")

    assert os.readlink(tmp_path / "link.txt") == "file.txt"
    assert (tmp_path / "hard.txt").read_bytes() == b"data"


def test_loopback_example_rejects_failed_access(
    tmp_path, monkeypatch, assert_fuse_errno
):
    monkeypatch.setattr("examples.loopback.os.access", lambda path, mode: False)

    with adapted(Loopback(tmp_path)) as fs:
        assert_fuse_errno(lambda: fs("access", "/missing.txt", os.R_OK), errno.EACCES)


def test_loopback_example_maps_chown_path(tmp_path, monkeypatch):
    calls = []

    monkeypatch.setattr(
        "examples.loopback.os.chown",
        lambda path, uid, gid: calls.append((path, uid, gid)),
    )

    with adapted(Loopback(tmp_path)) as fs:
        fs("chown", "/file.txt", 501, 20)

    assert calls == [(f"{tmp_path.resolve()}/file.txt", 501, 20)]


def test_loopback_example_syncs_file_handles(tmp_path, monkeypatch):
    calls = []

    monkeypatch.setattr(
        "examples.loopback.os.fsync", lambda fh: calls.append(("fsync", fh))
    )

    with adapted(Loopback(tmp_path)) as fs:
        assert fs("flush", "/file.txt", 7) is None
        assert fs("fsync", "/file.txt", 1, 7) is None
        assert fs("fsync", "/file.txt", 0, 7) is None

    assert calls == [("fsync", 7), ("fsync", 7), ("fsync", 7)]


def test_loopback_example_prefers_fdatasync_when_available(tmp_path, monkeypatch):
    calls = []

    monkeypatch.setattr(
        "examples.loopback.os.fsync", lambda fh: calls.append(("fsync", fh))
    )
    monkeypatch.setattr(
        "examples.loopback.os.fdatasync",
        lambda fh: calls.append(("fdatasync", fh)),
        raising=False,
    )

    with adapted(Loopback(tmp_path)) as fs:
        assert fs("fsync", "/file.txt", 1, 7) is None

    assert calls == [("fdatasync", 7)]


def test_loopback_example_uses_positioned_writes_for_shared_fd_offsets(tmp_path):
    path = tmp_path / "file.bin"
    path.write_bytes(b"\x00" * 64)
    fh = os.open(path, os.O_RDWR)
    try:
        with adapted(Loopback(tmp_path)) as fs:
            with ThreadPoolExecutor(max_workers=8) as executor:
                list(
                    executor.map(
                        lambda index: fs(
                            "write", "/file.bin", bytes([index]), index, fh
                        ),
                        range(64),
                    )
                )
    finally:
        os.close(fh)

    assert path.read_bytes() == bytes(range(64))
