from typing import Any


def _capture_request_context() -> tuple[int, int, int, int] | None: ...


def _set_request_context(context: object) -> Any: ...


def _reset_request_context(token: object) -> None: ...


def fuse_get_context() -> tuple[int, int, int]:
    """返回发起当前请求进程的 ``uid``、``gid`` 和 ``pid``。"""
    ...


def fuse_exit() -> None:
    """请求 libfuse 停止当前事件循环。"""
    ...


def libfuse_version() -> int:
    """返回运行时加载的 libfuse 版本号。"""
    ...
