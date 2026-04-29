import errno
import os
from contextlib import contextmanager

import pytest

from examples.context import Context
from macfusepy._runtime import _OperationsAdapter


@contextmanager
def adapted(operations):
    adapter = _OperationsAdapter(operations)
    try:
        yield adapter
    finally:
        adapter.close()


@pytest.fixture
def context_fs(monkeypatch):
    monkeypatch.setattr("examples.context.fuse_get_context", lambda: (501, 20, 1234))
    with adapted(Context()) as fs:
        yield fs


@pytest.mark.parametrize(
    ("path", "content"),
    [
        ("/uid", b"501\n"),
        ("/gid", b"20\n"),
        ("/pid", b"1234\n"),
    ],
)
def test_context_example_exposes_request_identity(context_fs, path, content):
    attrs = context_fs("getattr", path)

    assert attrs["st_size"] == len(content)
    assert attrs["st_atime"] > 10**18
    assert context_fs("read", path, 64, 0, 1) == content
    assert context_fs("read", path, 2, 1, 1) == content[1:3]


def test_context_example_exposes_request_identity_when_mounted(mounted_fuse):
    mountpoint = mounted_fuse(Context(), ro=True)

    assert sorted(os.listdir(mountpoint)) == ["gid", "pid", "uid"]
    assert (mountpoint / "uid").read_text() == f"{os.getuid()}\n"
    assert (mountpoint / "gid").read_text() == f"{os.getgid()}\n"
    assert (mountpoint / "pid").read_text() == f"{os.getpid()}\n"


def test_context_example_lists_identity_files(context_fs):
    assert context_fs("getattr", "/")["st_nlink"] == 2
    assert context_fs("readdir", "/", None) == [".", "..", "uid", "gid", "pid"]


def test_context_example_rejects_unknown_paths(context_fs, assert_fuse_errno):
    assert_fuse_errno(lambda: context_fs("getattr", "/missing"), errno.ENOENT)
    assert_fuse_errno(lambda: context_fs("read", "/missing", 64, 0, 1), errno.ENOENT)
    assert_fuse_errno(lambda: context_fs("readdir", "/missing", None), errno.ENOENT)


def test_context_example_disables_unused_operations(context_fs, assert_fuse_errno):
    assert_fuse_errno(
        lambda: context_fs("getxattr", "/uid", "com.example.key", 0), errno.ENOSYS
    )
