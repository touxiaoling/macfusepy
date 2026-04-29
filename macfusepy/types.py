class FileInfo:
    """libfuse3 ``fuse_file_info`` 的 Python 视图。

    当 ``FUSE(..., raw_fi=True)`` 时，打开、创建、读写和释放等操作会接收这个
    对象。操作方法也可以返回 ``FileInfo``，回调桥会把字段写回 libfuse。
    """

    __slots__ = (
        "flags",
        "fh",
        "direct_io",
        "keep_cache",
        "cache_readdir",
        "nonseekable",
        "noflush",
        "parallel_direct_writes",
    )

    flags: int
    fh: int
    direct_io: bool
    keep_cache: bool
    cache_readdir: bool
    nonseekable: bool
    noflush: bool
    parallel_direct_writes: bool

    def __init__(
        self,
        flags: int = 0,
        fh: int = 0,
        direct_io: bool = False,
        keep_cache: bool = False,
        cache_readdir: bool = False,
        nonseekable: bool = False,
        noflush: bool = False,
        parallel_direct_writes: bool = False,
    ) -> None:
        """创建文件句柄信息包装器。"""
        self.flags = flags
        self.fh = fh
        self.direct_io = bool(direct_io)
        self.keep_cache = bool(keep_cache)
        self.cache_readdir = bool(cache_readdir)
        self.nonseekable = bool(nonseekable)
        self.noflush = bool(noflush)
        self.parallel_direct_writes = bool(parallel_direct_writes)


class IoctlData:
    """low-level ``ioctl`` 请求携带的输入和输出缓冲区信息。"""

    __slots__ = ("input", "out_size")

    input: bytes
    out_size: int

    def __init__(self, input: bytes = b"", out_size: int = 0) -> None:
        """创建 ``ioctl`` 数据视图。"""
        self.input = input
        self.out_size = out_size


class ConnectionInfo:
    """libfuse3 连接能力信息的 Python 快照。"""

    __slots__ = (
        "proto_major",
        "proto_minor",
        "max_write",
        "max_read",
        "max_readahead",
        "capable",
        "want",
        "max_background",
        "congestion_threshold",
        "time_gran",
        "max_backing_stack_depth",
        "capable_ext",
        "want_ext",
        "capable_darwin",
        "want_darwin",
        "request_timeout",
    )

    proto_major: int
    proto_minor: int
    max_write: int
    max_read: int
    max_readahead: int
    capable: int
    want: int
    max_background: int
    congestion_threshold: int
    time_gran: int
    max_backing_stack_depth: int
    capable_ext: int
    want_ext: int
    capable_darwin: int
    want_darwin: int
    request_timeout: int

    def __init__(
        self,
        proto_major: int = 0,
        proto_minor: int = 0,
        max_write: int = 0,
        max_read: int = 0,
        max_readahead: int = 0,
        capable: int = 0,
        want: int = 0,
        max_background: int = 0,
        congestion_threshold: int = 0,
        time_gran: int = 0,
        max_backing_stack_depth: int = 0,
        capable_ext: int = 0,
        want_ext: int = 0,
        capable_darwin: int = 0,
        want_darwin: int = 0,
        request_timeout: int = 0,
    ) -> None:
        """创建连接信息包装器。"""
        self.proto_major = proto_major
        self.proto_minor = proto_minor
        self.max_write = max_write
        self.max_read = max_read
        self.max_readahead = max_readahead
        self.capable = capable
        self.want = want
        self.max_background = max_background
        self.congestion_threshold = congestion_threshold
        self.time_gran = time_gran
        self.max_backing_stack_depth = max_backing_stack_depth
        self.capable_ext = capable_ext
        self.want_ext = want_ext
        self.capable_darwin = capable_darwin
        self.want_darwin = want_darwin
        self.request_timeout = request_timeout


class Config:
    """libfuse3 挂载配置的 Python 视图。"""

    __slots__ = (
        "entry_timeout",
        "negative_timeout",
        "attr_timeout",
        "use_ino",
        "direct_io",
        "kernel_cache",
        "auto_cache",
        "nullpath_ok",
        "show_help",
    )

    entry_timeout: float
    negative_timeout: float
    attr_timeout: float
    use_ino: bool
    direct_io: bool
    kernel_cache: bool
    auto_cache: bool
    nullpath_ok: bool
    show_help: bool

    def __init__(self) -> None:
        """使用 libfuse 默认值创建可修改配置。"""
        self.entry_timeout = 0.0
        self.negative_timeout = 0.0
        self.attr_timeout = 0.0
        self.use_ino = False
        self.direct_io = False
        self.kernel_cache = False
        self.auto_cache = False
        self.nullpath_ok = False
        self.show_help = False
