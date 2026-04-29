import errno
import sys
import sysconfig

import macfusepy as fuse


def test_public_api_exports_are_explicit():
    assert fuse.__all__ == (
        "Config",
        "ConnectionInfo",
        "FUSE",
        "FileInfo",
        "FuseOSError",
        "InodeOperations",
        "IoctlData",
        "LoggingMixIn",
        "LowLevelAttr",
        "LowLevelEntry",
        "Operations",
        "fuse_exit",
        "fuse_get_context",
        "libfuse_version",
    )


def test_fuse_os_error_uses_errno_message():
    error = fuse.FuseOSError(errno.ENOENT)

    assert error.errno == errno.ENOENT
    assert "No such file or directory" in str(error)


def test_fuse_normalizes_mount_options():
    options = fuse.FUSE._normalize_fuse_options(
        allow_other=True,
        nothreads=False,
        fsname="Memory",
        uid=501,
    )

    assert list(options) == ["allow_other", "fsname=Memory", "uid=501"]


def test_libfuse_version_is_available():
    assert fuse.libfuse_version() >= 300


def test_operations_module_keeps_compatibility_exports():
    from macfusepy.operations import (
        InodeOperations,
        LoggingMixIn,
        Operations,
    )

    assert Operations is fuse.Operations
    assert InodeOperations is fuse.InodeOperations
    assert LoggingMixIn is fuse.LoggingMixIn


def test_core_declares_free_threaded_compatibility_when_available():
    if not sysconfig.get_config_var("Py_GIL_DISABLED") or not hasattr(
        sys, "_is_gil_enabled"
    ):
        return

    assert not sys._is_gil_enabled()
