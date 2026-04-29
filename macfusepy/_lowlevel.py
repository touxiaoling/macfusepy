# cython: language_level=3
# cython: binding=True
# cython: freethreading_compatible=True
# type: ignore
"""不公开的 libfuse low-level 会话桥。"""

from __future__ import annotations

from inspect import isawaitable
import errno
import fcntl
import logging
import sys

import cython

from cython.cimports.cpython.bytes import PyBytes_AsString, PyBytes_FromStringAndSize
from cython.cimports.macfusepy.fuse3 import (
    c_stat,
    c_statvfs,
    fuse_ctx,
    fuse_add_direntry,
    fuse_args,
    fuse_conn_info,
    fuse_entry_param,
    fuse_file_info,
    fuse_loop_config,
    fuse_ino_t,
    fuse_lowlevel_ops,
    flock,
    fuse_reply_attr,
    fuse_reply_bmap,
    fuse_reply_buf,
    fuse_reply_create,
    fuse_reply_entry,
    fuse_reply_err,
    fuse_reply_ioctl,
    fuse_reply_lock,
    fuse_reply_none,
    fuse_reply_open,
    fuse_reply_readlink,
    fuse_reply_statfs,
    fuse_reply_write,
    fuse_reply_xattr,
    fuse_req_ctx,
    fuse_req_t,
    fuse_req_userdata,
    fuse_session,
    fuse_session_destroy,
    fuse_session_exited,
    fuse_session_exit,
    fuse_session_fd,
    fuse_session_mount,
    fuse_session_new,
    fuse_session_loop_mt,
    fuse_session_unmount,
    timespec,
)
from cython.cimports.libc.stdlib import free, malloc
from cython.cimports.libc.string import memset
from cython.cimports.posix.types import dev_t, mode_t, off_t

from macfusepy._core import _reset_request_context, _set_request_context
from macfusepy.errors import FuseOSError
from macfusepy.lowlevel_async import LowLevelAttr, LowLevelEntry, LowLevelError
from macfusepy.types import ConnectionInfo, FileInfo, IoctlData


log = logging.getLogger("macfusepy.lowlevel")
_DEFAULT_TIMEOUT = 1.0
_UNSUPPORTED_MACFUSE_OPERATIONS = frozenset({"getlk", "setlk", "bmap"})
FUSE_SET_ATTR_MODE = 1 << 0
FUSE_SET_ATTR_UID = 1 << 1
FUSE_SET_ATTR_GID = 1 << 2
FUSE_SET_ATTR_SIZE = 1 << 3
FUSE_SET_ATTR_ATIME = 1 << 4
FUSE_SET_ATTR_MTIME = 1 << 5
F_GETLK = fcntl.F_GETLK
F_SETLK = fcntl.F_SETLK
F_SETLKW = getattr(fcntl, "F_SETLKW", fcntl.F_SETLK)


def _ensure_macos() -> None:
    if sys.platform != "darwin":
        raise EnvironmentError(
            "This low-level backend only supports macOS with macFUSE 5.2 or newer."
        )


@cython.cfunc
def _set_timespec(ts: cython.pointer(timespec), value: object) -> cython.void:
    sec: cython.long
    nsec: cython.long

    if value is None:
        return
    sec, nsec = divmod(int(value), 10**9)
    ts[0].tv_sec = sec
    ts[0].tv_nsec = nsec


@cython.cfunc
def _apply_stat(st: cython.pointer(c_stat), attrs: object) -> cython.void:
    memset(st, 0, cython.sizeof(c_stat))
    if attrs is None:
        return
    if isinstance(attrs, LowLevelAttr):
        st[0].ino = attrs.st_ino
        st[0].mode = attrs.st_mode
        st[0].nlink = attrs.st_nlink
        st[0].uid = attrs.st_uid
        st[0].gid = attrs.st_gid
        st[0].rdev = attrs.st_rdev
        st[0].size = attrs.st_size
        st[0].blocks = attrs.st_blocks
        st[0].blksize = attrs.st_blksize
        st[0].flags = attrs.st_flags
        _set_timespec(cython.address(st[0].atimespec), attrs.st_atime)
        _set_timespec(cython.address(st[0].mtimespec), attrs.st_mtime)
        _set_timespec(cython.address(st[0].ctimespec), attrs.st_ctime)
        _set_timespec(cython.address(st[0].btimespec), attrs.st_birthtime)
        return
    if "st_ino" in attrs:
        st[0].ino = attrs["st_ino"]
    if "st_mode" in attrs:
        st[0].mode = attrs["st_mode"]
    if "st_nlink" in attrs:
        st[0].nlink = attrs["st_nlink"]
    if "st_uid" in attrs:
        st[0].uid = attrs["st_uid"]
    if "st_gid" in attrs:
        st[0].gid = attrs["st_gid"]
    if "st_rdev" in attrs:
        st[0].rdev = attrs["st_rdev"]
    if "st_size" in attrs:
        st[0].size = attrs["st_size"]
    if "st_blocks" in attrs:
        st[0].blocks = attrs["st_blocks"]
    if "st_blksize" in attrs:
        st[0].blksize = attrs["st_blksize"]
    if "st_flags" in attrs:
        st[0].flags = attrs["st_flags"]
    _set_timespec(cython.address(st[0].atimespec), attrs.get("st_atime"))
    _set_timespec(cython.address(st[0].mtimespec), attrs.get("st_mtime"))
    _set_timespec(cython.address(st[0].ctimespec), attrs.get("st_ctime"))
    _set_timespec(cython.address(st[0].btimespec), attrs.get("st_birthtime"))


@cython.cfunc
def _stat_to_mapping(st: cython.pointer(c_stat)) -> object:
    if st == cython.NULL:
        return {}
    return {
        "st_ino": st[0].ino,
        "st_mode": st[0].mode,
        "st_nlink": st[0].nlink,
        "st_uid": st[0].uid,
        "st_gid": st[0].gid,
        "st_rdev": st[0].rdev,
        "st_size": st[0].size,
        "st_blocks": st[0].blocks,
        "st_blksize": st[0].blksize,
        "st_flags": st[0].flags,
        "st_atime": st[0].atimespec.tv_sec * 10**9 + st[0].atimespec.tv_nsec,
        "st_mtime": st[0].mtimespec.tv_sec * 10**9 + st[0].mtimespec.tv_nsec,
        "st_ctime": st[0].ctimespec.tv_sec * 10**9 + st[0].ctimespec.tv_nsec,
        "st_birthtime": st[0].btimespec.tv_sec * 10**9 + st[0].btimespec.tv_nsec,
    }


@cython.cfunc
def _lock_to_mapping(lock: cython.pointer(flock)) -> object:
    if lock == cython.NULL:
        return {}
    return {
        "l_type": lock[0].l_type,
        "l_whence": lock[0].l_whence,
        "l_start": lock[0].l_start,
        "l_len": lock[0].l_len,
        "l_pid": lock[0].l_pid,
    }


@cython.cfunc
def _apply_lock(lock: cython.pointer(flock), attrs: object) -> cython.void:
    if attrs is None:
        return
    if "l_type" in attrs:
        lock[0].l_type = attrs["l_type"]
    if "l_whence" in attrs:
        lock[0].l_whence = attrs["l_whence"]
    if "l_start" in attrs:
        lock[0].l_start = attrs["l_start"]
    if "l_len" in attrs:
        lock[0].l_len = attrs["l_len"]
    if "l_pid" in attrs:
        lock[0].l_pid = attrs["l_pid"]


@cython.cfunc
def _apply_statvfs(st: cython.pointer(c_statvfs), attrs: object) -> cython.void:
    memset(st, 0, cython.sizeof(c_statvfs))
    if attrs is None:
        return
    if "f_bsize" in attrs:
        st[0].f_bsize = attrs["f_bsize"]
    if "f_blocks" in attrs:
        st[0].f_blocks = attrs["f_blocks"]
    if "f_bfree" in attrs:
        st[0].f_bfree = attrs["f_bfree"]
    if "f_bavail" in attrs:
        st[0].f_bavail = attrs["f_bavail"]
    if "f_files" in attrs:
        st[0].f_files = attrs["f_files"]
    if "f_ffree" in attrs:
        st[0].f_ffree = attrs["f_ffree"]
    if "f_flag" in attrs:
        st[0].f_flags = attrs["f_flag"]
    if "f_flags" in attrs:
        st[0].f_flags = attrs["f_flags"]


@cython.cfunc
def _conn_to_info(conn: cython.pointer(fuse_conn_info)) -> object:
    if conn == cython.NULL:
        return None
    return ConnectionInfo(
        proto_major=conn[0].proto_major,
        proto_minor=conn[0].proto_minor,
        max_write=conn[0].max_write,
        max_read=conn[0].max_read,
        max_readahead=conn[0].max_readahead,
        capable=conn[0].capable,
        want=conn[0].want,
        max_background=conn[0].max_background,
        congestion_threshold=conn[0].congestion_threshold,
        time_gran=conn[0].time_gran,
        max_backing_stack_depth=conn[0].max_backing_stack_depth,
        capable_ext=conn[0].capable_ext,
        want_ext=conn[0].want_ext,
        capable_darwin=conn[0].capable_darwin,
        want_darwin=conn[0].want_darwin,
        request_timeout=conn[0].request_timeout,
    )


@cython.cfunc
def _apply_conn_info(
    conn: cython.pointer(fuse_conn_info), info: object
) -> cython.void:
    if conn == cython.NULL or info is None:
        return
    conn[0].max_write = info.max_write
    conn[0].max_read = info.max_read
    conn[0].max_readahead = info.max_readahead
    conn[0].want = info.want
    conn[0].max_background = info.max_background
    conn[0].congestion_threshold = info.congestion_threshold
    conn[0].time_gran = info.time_gran
    conn[0].max_backing_stack_depth = info.max_backing_stack_depth
    conn[0].want_ext = info.want_ext
    conn[0].want_darwin = info.want_darwin
    conn[0].request_timeout = info.request_timeout


@cython.cfunc
def _apply_entry(
    entry: cython.pointer(fuse_entry_param),
    value: object,
    attr_timeout: cython.double,
    entry_timeout: cython.double,
) -> cython.void:
    memset(entry, 0, cython.sizeof(fuse_entry_param))
    entry[0].ino = value.ino
    entry[0].generation = 1
    entry[0].attr_timeout = attr_timeout
    entry[0].entry_timeout = entry_timeout
    _apply_stat(cython.address(entry[0].attr), value.attrs)


def _errno_from_exception(exc: BaseException) -> int:
    if isinstance(exc, LowLevelError):
        return exc.errno
    if isinstance(exc, FuseOSError):
        return exc.errno
    if isinstance(exc, OSError) and getattr(exc, "errno", None):
        return int(exc.errno)
    log.error("Uncaught low-level FUSE operation exception", exc_info=True)
    return errno.EFAULT


@cython.cfunc
def _fill_file_info(
    fi: cython.pointer(fuse_file_info), handle: object, flags: cython.int
) -> cython.void:
    memset(fi, 0, cython.sizeof(fuse_file_info))
    fi[0].flags = flags
    if isinstance(handle, FileInfo):
        fi[0].flags = handle.flags
        fi[0].fh = handle.fh
        fi[0].direct_io = 1 if handle.direct_io else 0
        fi[0].keep_cache = 1 if handle.keep_cache else 0
        fi[0].cache_readdir = 1 if handle.cache_readdir else 0
        fi[0].nonseekable = 1 if handle.nonseekable else 0
        fi[0].noflush = 1 if handle.noflush else 0
        fi[0].parallel_direct_writes = 1 if handle.parallel_direct_writes else 0
    elif handle is not None:
        fi[0].fh = cython.cast(cython.ulonglong, int(handle))


@cython.cfunc
def _request_context(req: fuse_req_t) -> object:
    ctx: cython.pointer(cython.const[fuse_ctx])

    ctx = fuse_req_ctx(req)
    if ctx == cython.NULL:
        return None
    return (ctx[0].uid, ctx[0].gid, ctx[0].pid, 0)


@cython.cfunc
def _handle(fi: cython.pointer(fuse_file_info), raw_fi: cython.bint) -> object:
    info: FileInfo

    if fi == cython.NULL:
        return None
    if not raw_fi:
        return fi[0].fh
    info = FileInfo(
        flags=fi[0].flags,
        fh=fi[0].fh,
        direct_io=fi[0].direct_io,
        keep_cache=fi[0].keep_cache,
        cache_readdir=fi[0].cache_readdir,
        nonseekable=fi[0].nonseekable,
        noflush=fi[0].noflush,
        parallel_direct_writes=fi[0].parallel_direct_writes,
    )
    return info


@cython.cfunc
def _install_lowlevel_ops(
    ops: cython.pointer(fuse_lowlevel_ops), disabled: object
) -> cython.void:
    memset(ops, 0, cython.sizeof(fuse_lowlevel_ops))
    ops[0].init = _ll_init
    ops[0].lookup = _ll_lookup
    ops[0].forget = _ll_forget
    ops[0].getattr = _ll_getattr
    ops[0].setattr = _ll_setattr
    ops[0].readlink = _ll_readlink
    ops[0].mknod = _ll_mknod
    ops[0].mkdir = _ll_mkdir
    ops[0].unlink = _ll_unlink
    ops[0].rmdir = _ll_rmdir
    ops[0].symlink = _ll_symlink
    ops[0].rename = _ll_rename
    ops[0].link = _ll_link
    ops[0].open = _ll_open
    ops[0].read = _ll_read
    ops[0].write = _ll_write
    ops[0].flush = _ll_flush
    ops[0].release = _ll_release
    ops[0].fsync = _ll_fsync
    if "getlk" not in disabled:
        ops[0].getlk = _ll_getlk
    if "setlk" not in disabled:
        ops[0].setlk = _ll_setlk
    if "flock" not in disabled:
        ops[0].flock = _ll_flock
    ops[0].opendir = _ll_opendir
    ops[0].readdir = _ll_readdir
    ops[0].releasedir = _ll_releasedir
    ops[0].fsyncdir = _ll_fsyncdir
    ops[0].statfs = _ll_statfs
    ops[0].setxattr = _ll_setxattr
    ops[0].getxattr = _ll_getxattr
    ops[0].listxattr = _ll_listxattr
    ops[0].removexattr = _ll_removexattr
    if "access" not in disabled:
        ops[0].access = _ll_access
    ops[0].create = _ll_create
    if "bmap" not in disabled:
        ops[0].bmap = _ll_bmap
    ops[0].ioctl = _ll_ioctl


def _schedule(
    req_id: int, context: object, session: object, method: str, *args: object
) -> None:
    try:
        session._run_with_context(lambda: getattr(session, method)(req_id, *args), context)
    except BaseException:
        log.error("Unable to schedule low-level request", exc_info=True)
        fuse_reply_err(
            cython.cast(fuse_req_t, cython.cast(cython.size_t, req_id)), errno.EFAULT
        )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_init(userdata: cython.p_void, conn: cython.pointer(fuse_conn_info)) -> cython.void:
    session = cython.cast(object, userdata)
    info = _conn_to_info(conn)
    session._handle_init_sync(info)
    _apply_conn_info(conn, info)


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_lookup(
    req: fuse_req_t, parent: fuse_ino_t, name: cython.p_const_char
) -> cython.void:
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        cython.cast(object, fuse_req_userdata(req)),
        "_handle_lookup",
        parent,
        cython.cast(bytes, name),
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_forget(
    req: fuse_req_t, ino: fuse_ino_t, nlookup: cython.ulonglong
) -> cython.void:
    try:
        session = cython.cast(object, fuse_req_userdata(req))
        session._schedule(
            session._handle_forget(cython.cast(cython.size_t, req), ino, nlookup),
            _request_context(req),
        )
    except BaseException:
        log.error("Unable to schedule low-level forget", exc_info=True)
        fuse_reply_none(req)


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_getattr(
    req: fuse_req_t, ino: fuse_ino_t, fi: cython.pointer(fuse_file_info)
) -> cython.void:
    session = cython.cast(object, fuse_req_userdata(req))
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        session,
        "_handle_getattr",
        ino,
        _handle(fi, session.raw_fi),
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_setattr(
    req: fuse_req_t,
    ino: fuse_ino_t,
    attr: cython.pointer(c_stat),
    to_set: cython.int,
    fi: cython.pointer(fuse_file_info),
) -> cython.void:
    session = cython.cast(object, fuse_req_userdata(req))
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        session,
        "_handle_setattr",
        ino,
        _stat_to_mapping(attr),
        to_set,
        _handle(fi, session.raw_fi),
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_readlink(req: fuse_req_t, ino: fuse_ino_t) -> cython.void:
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        cython.cast(object, fuse_req_userdata(req)),
        "_handle_readlink",
        ino,
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_mknod(
    req: fuse_req_t,
    parent: fuse_ino_t,
    name: cython.p_const_char,
    mode: mode_t,
    dev: dev_t,
) -> cython.void:
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        cython.cast(object, fuse_req_userdata(req)),
        "_handle_mknod",
        parent,
        cython.cast(bytes, name),
        mode,
        dev,
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_mkdir(
    req: fuse_req_t, parent: fuse_ino_t, name: cython.p_const_char, mode: mode_t
) -> cython.void:
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        cython.cast(object, fuse_req_userdata(req)),
        "_handle_mkdir",
        parent,
        cython.cast(bytes, name),
        mode,
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_unlink(
    req: fuse_req_t, parent: fuse_ino_t, name: cython.p_const_char
) -> cython.void:
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        cython.cast(object, fuse_req_userdata(req)),
        "_handle_unlink",
        parent,
        cython.cast(bytes, name),
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_rmdir(
    req: fuse_req_t, parent: fuse_ino_t, name: cython.p_const_char
) -> cython.void:
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        cython.cast(object, fuse_req_userdata(req)),
        "_handle_rmdir",
        parent,
        cython.cast(bytes, name),
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_symlink(
    req: fuse_req_t,
    link: cython.p_const_char,
    parent: fuse_ino_t,
    name: cython.p_const_char,
) -> cython.void:
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        cython.cast(object, fuse_req_userdata(req)),
        "_handle_symlink",
        cython.cast(bytes, link),
        parent,
        cython.cast(bytes, name),
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_rename(
    req: fuse_req_t,
    parent: fuse_ino_t,
    name: cython.p_const_char,
    newparent: fuse_ino_t,
    newname: cython.p_const_char,
    flags: cython.uint,
) -> cython.void:
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        cython.cast(object, fuse_req_userdata(req)),
        "_handle_rename",
        parent,
        cython.cast(bytes, name),
        newparent,
        cython.cast(bytes, newname),
        flags,
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_link(
    req: fuse_req_t,
    ino: fuse_ino_t,
    newparent: fuse_ino_t,
    newname: cython.p_const_char,
) -> cython.void:
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        cython.cast(object, fuse_req_userdata(req)),
        "_handle_link",
        ino,
        newparent,
        cython.cast(bytes, newname),
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_open(
    req: fuse_req_t, ino: fuse_ino_t, fi: cython.pointer(fuse_file_info)
) -> cython.void:
    flags: cython.int = 0
    session = cython.cast(object, fuse_req_userdata(req))
    if fi != cython.NULL:
        flags = fi[0].flags
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        session,
        "_handle_open",
        ino,
        flags,
        _handle(fi, session.raw_fi),
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_read(
    req: fuse_req_t,
    ino: fuse_ino_t,
    size: cython.size_t,
    offset: off_t,
    fi: cython.pointer(fuse_file_info),
) -> cython.void:
    session = cython.cast(object, fuse_req_userdata(req))
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        session,
        "_handle_read",
        ino,
        size,
        offset,
        _handle(fi, session.raw_fi),
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_write(
    req: fuse_req_t,
    ino: fuse_ino_t,
    buf: cython.p_const_char,
    size: cython.size_t,
    offset: off_t,
    fi: cython.pointer(fuse_file_info),
) -> cython.void:
    session = cython.cast(object, fuse_req_userdata(req))
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        session,
        "_handle_write",
        ino,
        PyBytes_FromStringAndSize(buf, size),
        offset,
        _handle(fi, session.raw_fi),
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_flush(
    req: fuse_req_t, ino: fuse_ino_t, fi: cython.pointer(fuse_file_info)
) -> cython.void:
    session = cython.cast(object, fuse_req_userdata(req))
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        session,
        "_handle_flush",
        ino,
        _handle(fi, session.raw_fi),
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_release(
    req: fuse_req_t, ino: fuse_ino_t, fi: cython.pointer(fuse_file_info)
) -> cython.void:
    session = cython.cast(object, fuse_req_userdata(req))
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        session,
        "_handle_release",
        ino,
        _handle(fi, session.raw_fi),
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_fsync(
    req: fuse_req_t,
    ino: fuse_ino_t,
    datasync: cython.int,
    fi: cython.pointer(fuse_file_info),
) -> cython.void:
    session = cython.cast(object, fuse_req_userdata(req))
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        session,
        "_handle_fsync",
        ino,
        datasync,
        _handle(fi, session.raw_fi),
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_getlk(
    req: fuse_req_t,
    ino: fuse_ino_t,
    fi: cython.pointer(fuse_file_info),
    lock: cython.pointer(flock),
) -> cython.void:
    session = cython.cast(object, fuse_req_userdata(req))
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        session,
        "_handle_getlk",
        ino,
        _handle(fi, session.raw_fi),
        _lock_to_mapping(lock),
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_setlk(
    req: fuse_req_t,
    ino: fuse_ino_t,
    fi: cython.pointer(fuse_file_info),
    lock: cython.pointer(flock),
    sleep: cython.int,
) -> cython.void:
    session = cython.cast(object, fuse_req_userdata(req))
    cmd = F_SETLKW if sleep else F_SETLK
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        session,
        "_handle_setlk",
        ino,
        _handle(fi, session.raw_fi),
        cmd,
        _lock_to_mapping(lock),
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_flock(
    req: fuse_req_t, ino: fuse_ino_t, fi: cython.pointer(fuse_file_info), op: cython.int
) -> cython.void:
    session = cython.cast(object, fuse_req_userdata(req))
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        session,
        "_handle_flock",
        ino,
        _handle(fi, session.raw_fi),
        op,
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_opendir(
    req: fuse_req_t, ino: fuse_ino_t, fi: cython.pointer(fuse_file_info)
) -> cython.void:
    flags: cython.int = 0
    session = cython.cast(object, fuse_req_userdata(req))
    if fi != cython.NULL:
        flags = fi[0].flags
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        session,
        "_handle_opendir",
        ino,
        flags,
        _handle(fi, session.raw_fi),
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_readdir(
    req: fuse_req_t,
    ino: fuse_ino_t,
    size: cython.size_t,
    offset: off_t,
    fi: cython.pointer(fuse_file_info),
) -> cython.void:
    session = cython.cast(object, fuse_req_userdata(req))
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        session,
        "_handle_readdir",
        ino,
        size,
        offset,
        _handle(fi, session.raw_fi),
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_releasedir(
    req: fuse_req_t, ino: fuse_ino_t, fi: cython.pointer(fuse_file_info)
) -> cython.void:
    session = cython.cast(object, fuse_req_userdata(req))
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        session,
        "_handle_releasedir",
        ino,
        _handle(fi, session.raw_fi),
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_fsyncdir(
    req: fuse_req_t,
    ino: fuse_ino_t,
    datasync: cython.int,
    fi: cython.pointer(fuse_file_info),
) -> cython.void:
    session = cython.cast(object, fuse_req_userdata(req))
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        session,
        "_handle_fsyncdir",
        ino,
        datasync,
        _handle(fi, session.raw_fi),
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_statfs(req: fuse_req_t, ino: fuse_ino_t) -> cython.void:
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        cython.cast(object, fuse_req_userdata(req)),
        "_handle_statfs",
        ino,
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_setxattr(
    req: fuse_req_t,
    ino: fuse_ino_t,
    name: cython.p_const_char,
    value: cython.p_const_char,
    size: cython.size_t,
    flags: cython.int,
    position: cython.uint,
) -> cython.void:
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        cython.cast(object, fuse_req_userdata(req)),
        "_handle_setxattr",
        ino,
        cython.cast(bytes, name),
        PyBytes_FromStringAndSize(value, size),
        flags,
        position,
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_getxattr(
    req: fuse_req_t,
    ino: fuse_ino_t,
    name: cython.p_const_char,
    size: cython.size_t,
    position: cython.uint,
) -> cython.void:
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        cython.cast(object, fuse_req_userdata(req)),
        "_handle_getxattr",
        ino,
        cython.cast(bytes, name),
        size,
        position,
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_listxattr(req: fuse_req_t, ino: fuse_ino_t, size: cython.size_t) -> cython.void:
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        cython.cast(object, fuse_req_userdata(req)),
        "_handle_listxattr",
        ino,
        size,
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_removexattr(
    req: fuse_req_t, ino: fuse_ino_t, name: cython.p_const_char
) -> cython.void:
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        cython.cast(object, fuse_req_userdata(req)),
        "_handle_removexattr",
        ino,
        cython.cast(bytes, name),
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_access(req: fuse_req_t, ino: fuse_ino_t, mask: cython.int) -> cython.void:
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        cython.cast(object, fuse_req_userdata(req)),
        "_handle_access",
        ino,
        mask,
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_create(
    req: fuse_req_t,
    parent: fuse_ino_t,
    name: cython.p_const_char,
    mode: mode_t,
    fi: cython.pointer(fuse_file_info),
) -> cython.void:
    session = cython.cast(object, fuse_req_userdata(req))
    flags = fi[0].flags if fi != cython.NULL else 0
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        session,
        "_handle_create",
        parent,
        cython.cast(bytes, name),
        mode,
        flags,
        _handle(fi, session.raw_fi),
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_bmap(
    req: fuse_req_t, ino: fuse_ino_t, blocksize: cython.size_t, idx: cython.ulonglong
) -> cython.void:
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        cython.cast(object, fuse_req_userdata(req)),
        "_handle_bmap",
        ino,
        blocksize,
        idx,
    )


@cython.with_gil
@cython.cfunc
@cython.exceptval(check=False)
def _ll_ioctl(
    req: fuse_req_t,
    ino: fuse_ino_t,
    cmd: cython.uint,
    arg: cython.p_void,
    fi: cython.pointer(fuse_file_info),
    flags: cython.uint,
    in_buf: cython.p_const_void,
    in_bufsz: cython.size_t,
    out_bufsz: cython.size_t,
) -> cython.void:
    session = cython.cast(object, fuse_req_userdata(req))
    data = b""
    if in_buf != cython.NULL and in_bufsz > 0:
        data = PyBytes_FromStringAndSize(
            cython.cast(cython.p_const_char, in_buf), in_bufsz
        )
    _schedule(
        cython.cast(cython.size_t, req),
        _request_context(req),
        session,
        "_handle_ioctl",
        ino,
        cmd,
        cython.cast(cython.size_t, arg),
        _handle(fi, session.raw_fi),
        flags,
        data,
        out_bufsz,
    )


@cython.cclass
class LowLevelFUSESession:
    """真实 ``fuse_session`` 包装器，供公开运行时内部使用。"""

    handler: object
    _raw_fi: cython.bint
    attr_timeout: cython.double
    entry_timeout: cython.double
    _loop_clone_fd: cython.int
    _loop_max_idle_threads: cython.int
    _session: cython.pointer(fuse_session)
    _ops: cython.pointer(fuse_lowlevel_ops)
    _mounted: cython.bint
    _closed: cython.bint
    _disabled_operations: object
    _conn_info: object
    _init: object
    _lookup: object
    _forget: object
    _getattr: object
    _setattr: object
    _readlink: object
    _mknod: object
    _mkdir: object
    _unlink: object
    _rmdir: object
    _symlink: object
    _rename: object
    _link: object
    _open: object
    _read: object
    _write: object
    _flush: object
    _release: object
    _fsync: object
    _getlk: object
    _setlk: object
    _flock: object
    _opendir: object
    _readdir: object
    _releasedir: object
    _fsyncdir: object
    _statfs: object
    _setxattr: object
    _getxattr: object
    _listxattr: object
    _removexattr: object
    _access: object
    _create: object
    _bmap: object
    _ioctl: object

    def __init__(
        self,
        handler: object,
        mountpoint: str,
        *,
        raw_fi: bool = False,
        encoding: str = "utf-8",
        attr_timeout: float = _DEFAULT_TIMEOUT,
        entry_timeout: float = _DEFAULT_TIMEOUT,
        loop_clone_fd: bool = False,
        loop_max_idle_threads: int = 10,
        disabled_operations: object = (),
        **options: object,
    ) -> None:
        _ensure_macos()
        self.handler = handler
        self._raw_fi = raw_fi
        self.attr_timeout = attr_timeout
        self.entry_timeout = entry_timeout
        self._loop_clone_fd = int(loop_clone_fd)
        self._loop_max_idle_threads = int(loop_max_idle_threads)
        self._session = cython.NULL
        self._ops = cython.NULL
        self._mounted = False
        self._closed = False
        self._disabled_operations = frozenset(disabled_operations).union(
            _UNSUPPORTED_MACFUSE_OPERATIONS
        )
        self._conn_info = None
        self._bind_handler_methods(handler)

        args = ["macfusepy"]
        normalized_options = self._normalize_options(**options)
        if normalized_options:
            args.extend(["-o", normalized_options])
        self._create_session(args, mountpoint, encoding)

    def __dealloc__(self):
        if self._session != cython.NULL:
            fuse_session_exit(self._session)
            if self._mounted:
                fuse_session_unmount(self._session)
            fuse_session_destroy(self._session)
            self._session = cython.NULL
        if self._ops != cython.NULL:
            free(self._ops)
            self._ops = cython.NULL

    @property
    def raw_fi(self) -> bool:
        return bool(self._raw_fi)

    def _bind_handler_methods(self, handler: object) -> None:
        self._init = getattr(handler, "init")
        self._lookup = getattr(handler, "lookup")
        self._forget = getattr(handler, "forget")
        self._getattr = getattr(handler, "getattr")
        self._setattr = getattr(handler, "setattr")
        self._readlink = getattr(handler, "readlink")
        self._mknod = getattr(handler, "mknod")
        self._mkdir = getattr(handler, "mkdir")
        self._unlink = getattr(handler, "unlink")
        self._rmdir = getattr(handler, "rmdir")
        self._symlink = getattr(handler, "symlink")
        self._rename = getattr(handler, "rename")
        self._link = getattr(handler, "link")
        self._open = getattr(handler, "open")
        self._read = getattr(handler, "read")
        self._write = getattr(handler, "write")
        self._flush = getattr(handler, "flush")
        self._release = getattr(handler, "release")
        self._fsync = getattr(handler, "fsync")
        self._getlk = getattr(handler, "getlk")
        self._setlk = getattr(handler, "setlk")
        self._flock = getattr(handler, "flock")
        self._opendir = getattr(handler, "opendir")
        self._readdir = getattr(handler, "readdir")
        self._releasedir = getattr(handler, "releasedir")
        self._fsyncdir = getattr(handler, "fsyncdir")
        self._statfs = getattr(handler, "statfs")
        self._setxattr = getattr(handler, "setxattr")
        self._getxattr = getattr(handler, "getxattr")
        self._listxattr = getattr(handler, "listxattr")
        self._removexattr = getattr(handler, "removexattr")
        self._access = getattr(handler, "access")
        self._create = getattr(handler, "create")
        self._bmap = getattr(handler, "bmap")
        self._ioctl = getattr(handler, "ioctl")

    @property
    def connection_info(self) -> object:
        return self._conn_info

    def _normalize_options(self, **kwargs: object) -> str:
        parts = []
        for key, value in kwargs.items():
            option = key
            if value is True:
                parts.append(option)
            elif value not in (False, None):
                parts.append(f"{option}={value}")
        return ",".join(parts)

    def _create_session(self, args: list[str], mountpoint: str, encoding: str) -> None:
        argc: cython.int = len(args)
        argv: cython.pp_char = cython.cast(
            cython.pp_char, malloc(argc * cython.sizeof(cython.p_char))
        )
        c_args: fuse_args
        encoded_args = [arg.encode(encoding) for arg in args]
        mountpoint_bytes = mountpoint.encode(encoding)
        idx: cython.Py_ssize_t
        err: cython.int

        if argv == cython.NULL:
            raise MemoryError("Unable to allocate low-level libfuse argv")
        self._ops = cython.cast(
            cython.pointer(fuse_lowlevel_ops), malloc(cython.sizeof(fuse_lowlevel_ops))
        )
        if self._ops == cython.NULL:
            free(argv)
            raise MemoryError("Unable to allocate low-level operation table")

        for idx, value in enumerate(encoded_args):
            argv[idx] = PyBytes_AsString(value)

        _install_lowlevel_ops(self._ops, self._disabled_operations)
        c_args.argc = argc
        c_args.argv = argv
        c_args.allocated = 0
        try:
            self._session = fuse_session_new(
                cython.address(c_args),
                self._ops,
                cython.sizeof(fuse_lowlevel_ops),
                cython.cast(cython.p_void, self),
            )
        finally:
            free(argv)
        if self._session == cython.NULL:
            raise RuntimeError("Unable to create low-level libfuse session")

        err = fuse_session_mount(self._session, PyBytes_AsString(mountpoint_bytes))
        if err != 0:
            fuse_session_destroy(self._session)
            self._session = cython.NULL
            raise OSError(
                errno.EIO, f"Unable to mount low-level libfuse session at {mountpoint}"
            )
        self._mounted = True

    def fileno(self) -> int:
        if self._session == cython.NULL:
            raise RuntimeError("low-level session is closed")
        return fuse_session_fd(self._session)

    def run_multithreaded(self) -> int:
        config: fuse_loop_config
        status: cython.int

        if self._session == cython.NULL:
            return 0
        config.clone_fd = self._loop_clone_fd
        config.max_idle_threads = self._loop_max_idle_threads
        with cython.nogil:
            status = fuse_session_loop_mt(self._session, cython.address(config))
        return status

    def exited(self) -> bool:
        if self._session == cython.NULL:
            return True
        return bool(fuse_session_exited(self._session))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._session != cython.NULL:
            fuse_session_exit(self._session)
            if self._mounted:
                fuse_session_unmount(self._session)
                self._mounted = False
            fuse_session_destroy(self._session)
            self._session = cython.NULL
        if self._ops != cython.NULL:
            free(self._ops)
            self._ops = cython.NULL

    def bind_loop(self, loop: object) -> None:
        pass

    def _handle_init_sync(self, info: object) -> None:
        self._conn_info = info
        try:
            self._sync_result(self._init(info, None))
        except BaseException:
            log.error("Low-level init callback failed", exc_info=True)
            if self._session != cython.NULL:
                fuse_session_exit(self._session)

    def _schedule(self, awaitable: object, context: object = None) -> None:
        self._run_with_context(lambda: self._sync_result(awaitable), context)

    def _run_with_context(self, callback: object, context: object) -> object:
        token = None
        if context is not None:
            token = _set_request_context(context)
        try:
            return callback()
        finally:
            if token is not None:
                _reset_request_context(token)

    def _sync_result(self, result: object) -> object:
        if isawaitable(result):
            close = getattr(result, "close", None)
            if close is not None:
                close()
            raise TypeError("low-level operations must be sync methods")
        return result

    def _discard_task(self, task: object) -> None:
        try:
            task.result()
        except BaseException:
            log.error("Low-level reply task failed", exc_info=True)

    def _handle_lookup(self, req_id: int, parent: int, name: bytes) -> None:
        try:
            entry = self._lookup(parent, name)
            self._reply_entry(req_id, entry)
        except BaseException as exc:
            self._reply_error(req_id, _errno_from_exception(exc))

    def _handle_forget(self, req_id: int, ino: int, nlookup: int) -> None:
        try:
            self._forget(ino, nlookup)
        except BaseException:
            log.debug("Ignoring low-level forget failure", exc_info=True)
        self._reply_none(req_id)

    def _handle_getattr(self, req_id: int, ino: int, fh: object) -> None:
        try:
            self._reply_attr(req_id, self._getattr(ino, fh))
        except BaseException as exc:
            self._reply_error(req_id, _errno_from_exception(exc))

    def _handle_setattr(
        self, req_id: int, ino: int, attrs: object, to_set: int, fh: object
    ) -> None:
        try:
            self._reply_attr(
                req_id, self._setattr(ino, attrs, to_set, fh)
            )
        except BaseException as exc:
            self._reply_error(req_id, _errno_from_exception(exc))

    def _handle_readlink(self, req_id: int, ino: int) -> None:
        try:
            self._reply_readlink(req_id, self._readlink(ino))
        except BaseException as exc:
            self._reply_error(req_id, _errno_from_exception(exc))

    def _handle_mknod(
        self, req_id: int, parent: int, name: bytes, mode: int, dev: int
    ) -> None:
        self._entry_status(req_id, self._mknod, parent, name, mode, dev)

    def _handle_mkdir(
        self, req_id: int, parent: int, name: bytes, mode: int
    ) -> None:
        self._entry_status(req_id, self._mkdir, parent, name, mode)

    def _handle_unlink(self, req_id: int, parent: int, name: bytes) -> None:
        self._status(req_id, self._unlink, parent, name)

    def _handle_rmdir(self, req_id: int, parent: int, name: bytes) -> None:
        self._status(req_id, self._rmdir, parent, name)

    def _handle_symlink(
        self, req_id: int, link: bytes, parent: int, name: bytes
    ) -> None:
        self._entry_status(req_id, self._symlink, link, parent, name)

    def _handle_rename(
        self,
        req_id: int,
        parent: int,
        name: bytes,
        newparent: int,
        newname: bytes,
        flags: int,
    ) -> None:
        self._status(req_id, self._rename, parent, name, newparent, newname, flags)

    def _handle_link(
        self, req_id: int, ino: int, newparent: int, newname: bytes
    ) -> None:
        self._entry_status(req_id, self._link, ino, newparent, newname)

    def _handle_open(self, req_id: int, ino: int, flags: int, fi: object) -> None:
        try:
            self._reply_open(
                req_id, self._open(ino, flags, fi), flags
            )
        except BaseException as exc:
            self._reply_error(req_id, _errno_from_exception(exc))

    def _handle_read(
        self, req_id: int, ino: int, size: int, offset: int, fh: object
    ) -> None:
        try:
            self._reply_buf(
                req_id, self._read(ino, size, offset, fh)
            )
        except BaseException as exc:
            self._reply_error(req_id, _errno_from_exception(exc))

    def _handle_write(
        self, req_id: int, ino: int, data: bytes, offset: int, fh: object
    ) -> None:
        try:
            count = self._write(ino, data, offset, fh)
            self._reply_write(req_id, len(data) if count is None else int(count))
        except BaseException as exc:
            self._reply_error(req_id, _errno_from_exception(exc))

    def _handle_flush(self, req_id: int, ino: int, fh: object) -> None:
        self._status(req_id, self._flush, ino, fh)

    def _handle_release(self, req_id: int, ino: int, fh: object) -> None:
        self._status(req_id, self._release, ino, fh)

    def _handle_fsync(
        self, req_id: int, ino: int, datasync: int, fh: object
    ) -> None:
        self._status(req_id, self._fsync, ino, datasync, fh)

    def _handle_getlk(
        self, req_id: int, ino: int, fh: object, lock: object
    ) -> None:
        try:
            self._reply_lock(
                req_id, self._getlk(ino, fh, lock)
            )
        except BaseException as exc:
            self._reply_error(req_id, _errno_from_exception(exc))

    def _handle_setlk(
        self, req_id: int, ino: int, fh: object, cmd: int, lock: object
    ) -> None:
        self._status(req_id, self._setlk, ino, fh, cmd, lock)

    def _handle_flock(self, req_id: int, ino: int, fh: object, op: int) -> None:
        self._status(req_id, self._flock, ino, fh, op)

    def _handle_opendir(
        self, req_id: int, ino: int, flags: int, fi: object
    ) -> None:
        try:
            self._reply_open(req_id, self._opendir(ino, flags, fi), flags)
        except BaseException as exc:
            self._reply_error(req_id, _errno_from_exception(exc))

    def _handle_readdir(
        self, req_id: int, ino: int, size: int, offset: int, fh: object
    ) -> None:
        try:
            self._reply_readdir(
                req_id,
                self._readdir(ino, offset, size, fh, 0),
                size,
            )
        except BaseException as exc:
            self._reply_error(req_id, _errno_from_exception(exc))

    def _handle_releasedir(self, req_id: int, ino: int, fh: object) -> None:
        self._status(req_id, self._releasedir, ino, fh)

    def _handle_fsyncdir(
        self, req_id: int, ino: int, datasync: int, fh: object
    ) -> None:
        self._status(req_id, self._fsyncdir, ino, datasync, fh)

    def _handle_statfs(self, req_id: int, ino: int) -> None:
        try:
            self._reply_statfs(req_id, self._statfs(ino))
        except BaseException as exc:
            self._reply_error(req_id, _errno_from_exception(exc))

    def _handle_setxattr(
        self,
        req_id: int,
        ino: int,
        name: bytes,
        value: bytes,
        flags: int,
        position: int,
    ) -> None:
        self._status(req_id, self._setxattr, ino, name, value, flags, position)

    def _handle_getxattr(
        self, req_id: int, ino: int, name: bytes, size: int, position: int
    ) -> None:
        try:
            self._reply_xattr_value(
                req_id,
                self._getxattr(ino, name, position),
                size,
            )
        except BaseException as exc:
            self._reply_error(req_id, _errno_from_exception(exc))

    def _handle_listxattr(self, req_id: int, ino: int, size: int) -> None:
        try:
            self._reply_xattr_value(
                req_id, self._listxattr(ino), size
            )
        except BaseException as exc:
            self._reply_error(req_id, _errno_from_exception(exc))

    def _handle_removexattr(self, req_id: int, ino: int, name: bytes) -> None:
        self._status(req_id, self._removexattr, ino, name)

    def _handle_access(self, req_id: int, ino: int, mask: int) -> None:
        self._status(req_id, self._access, ino, mask)

    def _handle_create(
        self, req_id: int, parent: int, name: bytes, mode: int, flags: int, fi: object
    ) -> None:
        try:
            entry, handle = self._create(
                parent, name, mode, flags, fi
            )
            self._reply_create(req_id, entry, handle, flags)
        except BaseException as exc:
            self._reply_error(req_id, _errno_from_exception(exc))

    def _handle_bmap(
        self, req_id: int, ino: int, blocksize: int, idx: int
    ) -> None:
        try:
            self._reply_bmap(
                req_id, self._bmap(ino, blocksize, idx)
            )
        except BaseException as exc:
            self._reply_error(req_id, _errno_from_exception(exc))

    def _handle_ioctl(
        self,
        req_id: int,
        ino: int,
        cmd: int,
        arg: int,
        fh: object,
        flags: int,
        data: bytes,
        out_size: int,
    ) -> None:
        try:
            result = self._ioctl(
                ino, cmd, arg, fh, flags, IoctlData(data, out_size)
            )
            self._reply_ioctl(req_id, result, out_size)
        except BaseException as exc:
            self._reply_error(req_id, _errno_from_exception(exc))

    def _status(self, req_id: int, method: object, *args: object) -> None:
        try:
            self._sync_result(method(*args))
            self._reply_error(req_id, 0)
        except BaseException as exc:
            self._reply_error(req_id, _errno_from_exception(exc))

    def _entry_status(self, req_id: int, method: object, *args: object) -> None:
        try:
            self._reply_entry(req_id, self._sync_result(method(*args)))
        except BaseException as exc:
            self._reply_error(req_id, _errno_from_exception(exc))

    def _reply_error(self, req_id: int, err: int) -> None:
        fuse_reply_err(cython.cast(fuse_req_t, cython.cast(cython.size_t, req_id)), err)

    def _reply_none(self, req_id: int) -> None:
        fuse_reply_none(cython.cast(fuse_req_t, cython.cast(cython.size_t, req_id)))

    def _reply_entry(self, req_id: int, entry: LowLevelEntry) -> None:
        fuse_entry: fuse_entry_param

        _apply_entry(
            cython.address(fuse_entry), entry, self.attr_timeout, self.entry_timeout
        )
        fuse_reply_entry(
            cython.cast(fuse_req_t, cython.cast(cython.size_t, req_id)),
            cython.address(fuse_entry),
        )

    def _reply_create(
        self, req_id: int, entry: LowLevelEntry, handle: object, flags: int
    ) -> None:
        fuse_entry: fuse_entry_param
        fi: fuse_file_info

        _apply_entry(
            cython.address(fuse_entry), entry, self.attr_timeout, self.entry_timeout
        )
        _fill_file_info(cython.address(fi), handle, flags)
        fuse_reply_create(
            cython.cast(fuse_req_t, cython.cast(cython.size_t, req_id)),
            cython.address(fuse_entry),
            cython.address(fi),
        )

    def _reply_attr(self, req_id: int, attrs: object) -> None:
        st: c_stat

        _apply_stat(cython.address(st), attrs)
        fuse_reply_attr(
            cython.cast(fuse_req_t, cython.cast(cython.size_t, req_id)),
            cython.address(st),
            self.attr_timeout,
        )

    def _reply_readlink(self, req_id: int, target: object) -> None:
        payload = target.encode() if isinstance(target, str) else target
        fuse_reply_readlink(
            cython.cast(fuse_req_t, cython.cast(cython.size_t, req_id)),
            PyBytes_AsString(payload),
        )

    def _reply_open(self, req_id: int, handle: object, flags: int) -> None:
        fi: fuse_file_info

        _fill_file_info(cython.address(fi), handle, flags)
        fuse_reply_open(
            cython.cast(fuse_req_t, cython.cast(cython.size_t, req_id)),
            cython.address(fi),
        )

    def _reply_lock(self, req_id: int, attrs: object) -> None:
        lock: flock

        memset(cython.address(lock), 0, cython.sizeof(flock))
        _apply_lock(cython.address(lock), attrs)
        fuse_reply_lock(
            cython.cast(fuse_req_t, cython.cast(cython.size_t, req_id)),
            cython.address(lock),
        )

    def _reply_write(self, req_id: int, count: int) -> None:
        fuse_reply_write(
            cython.cast(fuse_req_t, cython.cast(cython.size_t, req_id)), count
        )

    def _reply_buf(self, req_id: int, data: object) -> None:
        payload = data if isinstance(data, bytes) else str(data).encode()
        fuse_reply_buf(
            cython.cast(fuse_req_t, cython.cast(cython.size_t, req_id)),
            PyBytes_AsString(payload),
            len(payload),
        )

    def _reply_statfs(self, req_id: int, attrs: object) -> None:
        st: c_statvfs

        _apply_statvfs(cython.address(st), attrs)
        fuse_reply_statfs(
            cython.cast(fuse_req_t, cython.cast(cython.size_t, req_id)),
            cython.address(st),
        )

    def _reply_xattr_value(self, req_id: int, value: object, size: int) -> None:
        if isinstance(value, (list, tuple, set)):
            payload = b"".join(
                (item.encode() if isinstance(item, str) else item) + b"\0"
                for item in value
            )
        else:
            payload = value if isinstance(value, bytes) else str(value).encode()
        if size == 0:
            fuse_reply_xattr(
                cython.cast(fuse_req_t, cython.cast(cython.size_t, req_id)),
                len(payload),
            )
        elif len(payload) > size:
            self._reply_error(req_id, errno.ERANGE)
        else:
            self._reply_buf(req_id, payload)

    def _reply_bmap(self, req_id: int, idx: object) -> None:
        fuse_reply_bmap(
            cython.cast(fuse_req_t, cython.cast(cython.size_t, req_id)), int(idx or 0)
        )

    def _reply_ioctl(self, req_id: int, result: object, out_size: int) -> None:
        req: fuse_req_t = cython.cast(fuse_req_t, cython.cast(cython.size_t, req_id))
        status: cython.int = 0
        data: object = b""
        payload: bytes

        if isinstance(result, tuple):
            status = int(result[0])
            data = result[1] if len(result) > 1 else b""
        elif isinstance(result, int):
            status = result
        elif result is not None:
            data = result
        if data is None:
            data = b""
        payload = data if isinstance(data, bytes) else str(data).encode()
        if len(payload) > out_size:
            fuse_reply_err(req, errno.ERANGE)
            return
        if payload:
            fuse_reply_ioctl(req, status, PyBytes_AsString(payload), len(payload))
        else:
            fuse_reply_ioctl(req, status, cython.NULL, 0)

    def _reply_readdir(self, req_id: int, entries: object, size: int) -> None:
        req: fuse_req_t = cython.cast(fuse_req_t, cython.cast(cython.size_t, req_id))
        buffer: cython.p_char = cython.NULL
        used: cython.size_t = 0
        needed: cython.size_t
        remaining: cython.size_t
        st: c_stat
        name: bytes

        if size <= 0:
            fuse_reply_buf(req, cython.NULL, 0)
            return
        buffer = cython.cast(cython.p_char, malloc(cython.cast(cython.size_t, size)))
        if buffer == cython.NULL:
            fuse_reply_err(req, errno.ENOMEM)
            return
        try:
            for entry in entries:
                name = (
                    entry.name
                    if isinstance(entry.name, bytes)
                    else str(entry.name).encode()
                )
                _apply_stat(cython.address(st), entry.attrs)
                remaining = cython.cast(cython.size_t, size) - used
                needed = fuse_add_direntry(
                    req,
                    buffer + used,
                    remaining,
                    PyBytes_AsString(name),
                    cython.address(st),
                    entry.next_id,
                )
                if needed > remaining:
                    break
                used += needed
            fuse_reply_buf(req, buffer, used)
        finally:
            free(buffer)


ReadOnlyLowLevelSession = LowLevelFUSESession
