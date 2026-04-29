import macfusepy as fuse


def test_file_info_wrapper():
    info = fuse.FileInfo(
        flags=1,
        fh=42,
        direct_io=True,
        keep_cache=True,
        cache_readdir=True,
        nonseekable=True,
        noflush=True,
        parallel_direct_writes=True,
    )

    assert info.flags == 1
    assert info.fh == 42
    assert info.direct_io
    assert info.keep_cache
    assert info.cache_readdir
    assert info.nonseekable
    assert info.noflush
    assert info.parallel_direct_writes


def test_connection_info_wrapper():
    info = fuse.ConnectionInfo(
        proto_major=7,
        proto_minor=35,
        max_write=131072,
        max_read=65536,
        max_readahead=4096,
        capable=0b101,
        want=0b001,
        max_background=12,
        congestion_threshold=6,
        time_gran=1,
        max_backing_stack_depth=1,
        capable_ext=0x100000000,
        want_ext=0x100000000,
        capable_darwin=0x20,
        want_darwin=0x20,
        request_timeout=60,
    )

    assert info.proto_major == 7
    assert info.proto_minor == 35
    assert info.max_write == 131072
    assert info.max_read == 65536
    assert info.max_readahead == 4096
    assert info.capable == 0b101
    assert info.want == 0b001
    assert info.max_background == 12
    assert info.congestion_threshold == 6
    assert info.time_gran == 1
    assert info.max_backing_stack_depth == 1
    assert info.capable_ext == 0x100000000
    assert info.want_ext == 0x100000000
    assert info.capable_darwin == 0x20
    assert info.want_darwin == 0x20
    assert info.request_timeout == 60


def test_config_defaults_are_falsey():
    config = fuse.Config()

    assert config.entry_timeout == 0.0
    assert config.negative_timeout == 0.0
    assert config.attr_timeout == 0.0
    assert not config.use_ino
    assert not config.direct_io
    assert not config.kernel_cache
    assert not config.auto_cache
    assert not config.nullpath_ok
    assert not config.show_help
    assert not hasattr(config, "parallel_direct_writes")
