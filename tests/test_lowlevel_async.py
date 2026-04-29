import errno
from pathlib import Path

import pytest

from macfusepy._readonly_async_tree import ReadOnlyAsyncTree
from macfusepy.lowlevel_async import (
    LowLevelAttr,
    LowLevelError,
    ROOT_INODE,
)


def test_read_only_async_tree_uses_inode_model():
    tree = ReadOnlyAsyncTree({"hello.txt": b"hello"})
    entry = tree.lookup(ROOT_INODE, b"hello.txt")
    attrs = tree.getattr(entry.ino)
    fh = tree.open(entry.ino, 0)
    data = tree.read(entry.ino, 2, 1, fh)
    entries = list(tree.readdir(ROOT_INODE))
    tree.release(entry.ino, fh)

    assert entry.name == b"hello.txt"
    assert attrs["st_size"] == 5
    assert data == b"el"
    assert entries == [entry]


def test_lowlevel_attr_keeps_mapping_compatibility():
    attrs = LowLevelAttr(st_ino=7, st_mode=0o100644, st_nlink=1, st_size=12)

    assert attrs["st_ino"] == 7
    assert attrs.get("st_size") == 12
    assert dict(attrs)["st_mode"] == 0o100644


def test_read_only_async_tree_maps_missing_nodes_to_errno():
    tree = ReadOnlyAsyncTree({"hello.txt": b"hello"})
    with pytest.raises(LowLevelError) as exc_info:
        tree.lookup(ROOT_INODE, b"missing.txt")

    assert exc_info.value.errno == errno.ENOENT


def test_read_only_async_tree_readdir_uses_stable_offsets():
    tree = ReadOnlyAsyncTree({"a.txt": b"a", "b.txt": b"b"})
    entries = list(tree.readdir(ROOT_INODE))
    after_first = list(tree.readdir(ROOT_INODE, entries[0].next_id))

    assert [entry.name for entry in entries] == [b"a.txt", b"b.txt"]
    assert entries[0].next_id == entries[0].ino
    assert after_first == entries[1:]


def test_minimal_lowlevel_declarations_are_recorded():
    declarations = (
        Path(__file__).parents[1].joinpath("macfusepy", "fuse3.pxd").read_text()
    )

    for symbol in (
        "fuse_lowlevel_ops",
        "fuse_session_fd",
        "fuse_loop_config",
        "fuse_session_loop_mt",
        "fuse_req_userdata",
        "fuse_reply_entry",
        "fuse_reply_attr",
        "fuse_reply_open",
        "fuse_reply_buf",
        "fuse_reply_ioctl",
        "setvolname",
        "statx",
    ):
        assert symbol in declarations


def test_lowlevel_backend_disables_unsupported_macos_operations():
    source = Path(__file__).parents[1].joinpath("macfusepy", "_lowlevel.py").read_text()

    unsupported = '_UNSUPPORTED_MACFUSE_OPERATIONS = frozenset({"getlk", "setlk", "bmap"})'
    assert unsupported in source
    assert 'if "getlk" not in disabled:' in source
    assert 'if "setlk" not in disabled:' in source
    assert 'if "bmap" not in disabled:' in source


def test_lowlevel_extension_exports_session_wrapper():
    lowlevel = pytest.importorskip("macfusepy._lowlevel")

    assert lowlevel.LowLevelFUSESession.__name__ == "LowLevelFUSESession"
    assert lowlevel.ReadOnlyLowLevelSession is lowlevel.LowLevelFUSESession
