import ctypes
import errno
import subprocess
from contextlib import contextmanager

import pytest

from examples.ioctl import Ioctl, M_IOWR
from macfusepy._runtime import _OperationsAdapter
from macfusepy.types import IoctlData


@contextmanager
def adapted(operations):
    adapter = _OperationsAdapter(operations)
    try:
        yield adapter
    finally:
        adapter.close()


def test_ioctl_example_increments_uint32_buffer():
    with adapted(Ioctl()) as fs:
        fs("create", "/test", 0o644)
        data = ctypes.c_uint32(100)

        assert fs("ioctl", "/test", M_IOWR, 0, 1, 0, ctypes.addressof(data)) == 0

    assert data.value == 101


def test_ioctl_example_rejects_unknown_command(assert_fuse_errno):
    with adapted(Ioctl()) as fs:
        fs("create", "/test", 0o644)
        data = ctypes.c_uint32(100)

        assert_fuse_errno(
            lambda: fs("ioctl", "/test", 0, 0, 1, 0, ctypes.addressof(data)),
            errno.ENOTTY,
        )


def test_ioctl_example_returns_lowlevel_output_buffer():
    with adapted(Ioctl()) as fs:
        fs("create", "/test", 0o644)

        assert fs(
            "ioctl", "/test", M_IOWR, 0, 1, 0, IoctlData((100).to_bytes(4, "little"), 4)
        ) == (101).to_bytes(4, "little")


# 诊断结论：macFUSE 5.2/libfuse3 当前不会把这个普通文件上的自定义
# ``_IOWR('M', 1, uint32_t)`` 请求转发给高层 ``fuse_operations.ioctl`` 回调；
# 失败发生在进入 Python 文件系统之前，客户端直接收到 ``ENOTTY``。
@pytest.mark.xfail(reason="macFUSE 真实挂载未转发自定义 ioctl 到高层回调", strict=True)
def test_ioctl_example_increments_buffer_when_mounted(tmp_path, mounted_fuse):
    mountpoint = mounted_fuse(Ioctl())
    path = mountpoint / "test"
    path.touch()

    binary = tmp_path / "ioctl_test"
    subprocess.run(["cc", "-o", binary, "examples/ioctl.c"], check=True)
    result = subprocess.run(
        [binary, "100", path],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == "M_IOWR successful, data = 101\n"
