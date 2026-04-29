import errno
import logging
from collections.abc import Iterable
from contextlib import contextmanager

import pytest

import macfusepy as fuse
from macfusepy._runtime import _OperationsAdapter


ENOTSUP = getattr(errno, "ENOTSUP", errno.ENOTTY)


@contextmanager
def adapted(operations):
    adapter = _OperationsAdapter(operations)
    try:
        yield adapter
    finally:
        adapter.close()


def test_default_operations(assert_fuse_errno):
    with adapted(fuse.Operations()) as ops:
        assert ops("readdir", "/", None) == [".", ".."]
        assert ops("readdir", "/", None, 1) == [".", ".."]
        attrs = ops("getattr", "/")
        assert isinstance(attrs, dict)
        assert attrs["st_nlink"] == 2
        assert_fuse_errno(lambda: ops("getattr", "/missing"), errno.ENOENT)


def test_operations_dispatches_by_name(assert_fuse_errno):
    with adapted(fuse.Operations()) as ops:
        assert ops("access", "/", 0) == 0
        assert ops("readdir", "/", None) == [".", ".."]
        assert_fuse_errno(lambda: ops("missing_operation"), errno.ENOSYS)


@pytest.mark.parametrize(
    ("method_name", "args"),
    [
        ("access", ("/", 0)),
        ("flush", ("/file", 1)),
        ("fsync", ("/file", 0, 1)),
        ("fsyncdir", ("/", 0, 1)),
        ("open", ("/file", 0)),
        ("opendir", ("/",)),
        ("release", ("/file", 1)),
        ("releasedir", ("/", 1)),
        ("utimens", ("/file", None, 1)),
    ],
)
def test_default_success_operations_return_zero(method_name, args):
    with adapted(fuse.Operations()) as ops:
        assert ops(method_name, *args) == 0


@pytest.mark.parametrize(
    ("method_name", "args"),
    [
        ("destroy", ()),
        ("init", (None, None)),
    ],
)
def test_default_lifecycle_operations_are_no_ops(method_name, args):
    with adapted(fuse.Operations()) as ops:
        assert ops(method_name, *args) is None


@pytest.mark.parametrize(
    ("method_name", "args", "expected_errno"),
    [
        ("chmod", ("/file", 0o644), errno.EROFS),
        ("chown", ("/file", 501, 20), errno.EROFS),
        ("create", ("/file", 0o644), errno.EROFS),
        ("getxattr", ("/file", "com.example.name", 0), ENOTSUP),
        ("ioctl", ("/file", 0, 0, 1, 0, 0), errno.ENOTTY),
        ("link", ("/target", "/source"), errno.EROFS),
        ("lock", ("/file", 1, 0, {"l_type": 1, "l_start": 0, "l_len": 0}), ENOTSUP),
        ("mkdir", ("/dir", 0o755), errno.EROFS),
        ("mknod", ("/file", 0o644, 0), errno.EROFS),
        ("read", ("/file", 10, 0, 1), errno.EIO),
        ("readlink", ("/link",), errno.ENOENT),
        ("removexattr", ("/file", "com.example.name"), ENOTSUP),
        ("rename", ("/old", "/new", 0), errno.EROFS),
        ("rmdir", ("/dir",), errno.EROFS),
        ("setxattr", ("/file", "com.example.name", b"value", 0, 0), ENOTSUP),
        ("symlink", ("/link", "/target"), errno.EROFS),
        ("truncate", ("/file", 0), errno.EROFS),
        ("unlink", ("/file",), errno.EROFS),
        ("write", ("/file", b"data", 0, 1), errno.EROFS),
    ],
)
def test_default_error_operations_raise_fuse_os_error(
    method_name, args, expected_errno, assert_fuse_errno
):
    with adapted(fuse.Operations()) as ops:
        assert_fuse_errno(lambda: ops(method_name, *args), expected_errno)


def test_default_operations_that_return_empty_collections():
    with adapted(fuse.Operations()) as ops:
        attrs = ops("listxattr", "/")
        assert isinstance(attrs, Iterable)
        assert list(attrs) == []
        assert ops("statfs", "/") == {}


def test_logging_mixin_logs_results_and_errors(caplog, assert_fuse_errno):
    class LoggedOperations(fuse.LoggingMixIn, fuse.Operations):
        pass

    with adapted(LoggedOperations()) as ops:
        with caplog.at_level(logging.DEBUG, logger="macfusepy"):
            assert ops("access", "/", 0) == 0
            assert_fuse_errno(lambda: ops("read", "/file", 10, 0, 1), errno.EIO)

    messages = [record.getMessage() for record in caplog.records]
    assert any("access('/', 0) -> 0" in message for message in messages)
    assert any(
        "read('/file', 10, 0, 1) -> OSError(5)" in message for message in messages
    )


def test_logging_mixin_logs_sync_results(caplog):
    class LoggedOperations(fuse.LoggingMixIn, fuse.Operations):
        def access(self, path, amode):
            return 0

    adapter = _OperationsAdapter(LoggedOperations())
    try:
        with caplog.at_level(logging.DEBUG, logger="macfusepy"):
            assert adapter("access", "/", 0) == 0
    finally:
        adapter.close()

    messages = [record.getMessage() for record in caplog.records]
    assert any("access('/', 0) -> 0" in message for message in messages)
