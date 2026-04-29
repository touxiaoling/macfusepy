# cython: language_level=3
# cython: binding=True
# cython: freethreading_compatible=True
# type: ignore
"""libfuse 上下文辅助。"""

import cython

from contextvars import ContextVar

from cython.cimports.macfusepy.fuse3 import (
    fuse,
    fuse_context,
    fuse_exit as _fuse_exit,
    fuse_get_context as _fuse_get_context,
    fuse_get_version,
)


_REQUEST_CONTEXT = ContextVar("macfusepy_request_context", default=None)


def _capture_request_context():
    """捕获当前 libfuse 回调上下文，供跨线程协程继续读取。"""
    ctx: cython.pointer(fuse_context)

    ctx = _fuse_get_context()
    if ctx == cython.NULL:
        return None
    return (
        ctx[0].uid,
        ctx[0].gid,
        ctx[0].pid,
        cython.cast(cython.size_t, ctx[0].fuse),
    )


def _set_request_context(context):
    """在当前 contextvars 上安装捕获到的 FUSE 请求上下文。"""
    return _REQUEST_CONTEXT.set(context)


def _reset_request_context(token) -> None:
    """恢复安装请求上下文之前的 contextvars 状态。"""
    _REQUEST_CONTEXT.reset(token)


def fuse_get_context() -> tuple[int, int, int]:
    """返回发起当前请求进程的 ``uid``、``gid`` 和 ``pid``。"""
    ctx: cython.pointer(fuse_context)
    context: object

    context = _REQUEST_CONTEXT.get()
    if context is not None:
        return int(context[0]), int(context[1]), int(context[2])
    ctx = _fuse_get_context()
    if ctx != cython.NULL:
        return ctx[0].uid, ctx[0].gid, ctx[0].pid
    raise RuntimeError("fuse_get_context() is only valid inside a FUSE callback")


def fuse_exit() -> None:
    """请求 libfuse 停止当前事件循环。"""
    ctx: cython.pointer(fuse_context)
    context: object

    context = _REQUEST_CONTEXT.get()
    if context is not None:
        if context[3]:
            _fuse_exit(
                cython.cast(
                    cython.pointer(fuse), cython.cast(cython.size_t, context[3])
                )
            )
        return
    ctx = _fuse_get_context()
    if ctx != cython.NULL and ctx[0].fuse != cython.NULL:
        _fuse_exit(ctx[0].fuse)


def libfuse_version() -> int:
    """返回运行时加载的 libfuse 版本号。"""
    return fuse_get_version()
