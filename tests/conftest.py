import logging
import os
import subprocess
import time
from collections.abc import Callable, Iterator
from multiprocessing import get_context
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Any

import pytest

import macfusepy as fuse


BENCHMARK_ONLY_HELP = (
    "benchmark 默认跳过；只跑 benchmark 用："
    "uv run pytest --run-benchmarks -m benchmark tests/test_benchmarks.py"
)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-benchmarks",
        action="store_true",
        default=False,
        help="运行默认跳过的 benchmark 用例。",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--run-benchmarks"):
        return

    skip_benchmark = pytest.mark.skip(reason=BENCHMARK_ONLY_HELP)
    for item in items:
        if item.get_closest_marker("benchmark"):
            item.add_marker(skip_benchmark)


def _serve_fuse(operations: object, mountpoint: str, options: dict[str, Any]) -> None:
    if os.environ.get("macfusepy_TEST_DEBUG"):
        logging.basicConfig(level=logging.DEBUG)
    fuse_class = options.pop("_fuse_class", fuse.FUSE)
    fuse_class(operations, mountpoint, foreground=True, **options)


def _is_mounted(mountpoint: Path) -> bool:
    mountpoint_text = os.fspath(mountpoint)
    if os.path.ismount(mountpoint_text):
        return True

    result = subprocess.run(
        ["/sbin/mount"],
        check=False,
        capture_output=True,
        text=True,
    )
    return f" on {mountpoint_text} " in result.stdout


def _wait_for_mount(mountpoint: Path, process: BaseProcess) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if _is_mounted(mountpoint):
            return
        if process.exitcode is not None:
            raise RuntimeError(
                f"FUSE mount process exited with status {process.exitcode}"
            )
        time.sleep(0.05)

    raise TimeoutError(f"Timed out waiting for FUSE mount at {mountpoint}")


def _unmount(mountpoint: Path) -> None:
    if not _is_mounted(mountpoint):
        return

    commands = (
        ["/sbin/umount", os.fspath(mountpoint)],
        ["/usr/sbin/diskutil", "unmount", "force", os.fspath(mountpoint)],
    )
    last_error = ""
    for command in commands:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if result.returncode == 0 or not _is_mounted(mountpoint):
            return
        last_error = result.stderr.strip() or result.stdout.strip()

    raise RuntimeError(f"Unable to unmount {mountpoint}: {last_error}")


@pytest.fixture
def mounted_fuse(tmp_path: Path) -> Iterator[Callable[..., Path]]:
    """在子进程中挂载 FUSE 文件系统，并返回挂载点路径。"""
    context = get_context("fork")
    mounts: list[tuple[Path, BaseProcess]] = []

    def mount(operations: object, **options: object) -> Path:
        mountpoint = tmp_path / f"mnt-{len(mounts)}"
        mountpoint.mkdir()
        options.setdefault("defer_permissions", True)
        process = context.Process(
            target=_serve_fuse,
            args=(operations, os.fspath(mountpoint), options),
        )
        process.start()
        _wait_for_mount(mountpoint, process)
        mounts.append((mountpoint, process))
        return mountpoint

    yield mount

    errors = []
    for mountpoint, process in reversed(mounts):
        try:
            _unmount(mountpoint)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

        process.join(5)
        if process.is_alive():
            process.terminate()
            process.join(5)

    if errors:
        raise errors[0]


@pytest.fixture
def assert_fuse_errno():
    def _assert_fuse_errno(call, expected_errno):
        with pytest.raises(fuse.FuseOSError) as exc_info:
            call()
        assert exc_info.value.errno == expected_errno

    return _assert_fuse_errno
