import platform
import os
import shlex
import subprocess
import sys

from Cython.Build import cythonize
from setuptools import Extension, setup


FUSE_USE_VERSION = "35"
os.environ.setdefault("MACOSX_DEPLOYMENT_TARGET", "12.0")
MACFUSE_INCLUDE_DIRS = (
    "/usr/local/include/fuse3",
    "/opt/homebrew/include/fuse3",
    "/Library/Filesystems/macfuse.fs/Contents/Resources/include/fuse3",
)
MACFUSE_LIBRARY_DIRS = (
    "/usr/local/lib",
    "/opt/homebrew/lib",
)


def pkg_config(*args):
    try:
        output = subprocess.check_output(
            ["pkg-config", *args, "fuse3"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return []
    return shlex.split(output)


def build_extension(name, source):
    if sys.platform != "darwin":
        raise RuntimeError(
            "This package only supports macOS with macFUSE 5.2 or newer."
        )

    include_dirs = []
    library_dirs = []
    libraries = ["fuse3"]
    extra_compile_args = [
        f"-DFUSE_USE_VERSION={FUSE_USE_VERSION}",
        "-mmacosx-version-min=12.0",
    ]
    extra_link_args = ["-mmacosx-version-min=12.0"]

    for token in pkg_config("--cflags"):
        if token.startswith("-I"):
            include_dirs.append(token[2:])
        else:
            extra_compile_args.append(token)

    for token in pkg_config("--libs"):
        if token.startswith("-L"):
            library_dirs.append(token[2:])
        elif token.startswith("-l"):
            lib = token[2:]
            if lib not in libraries:
                libraries.append(lib)
        else:
            extra_link_args.append(token)

    include_dirs.extend(
        path for path in MACFUSE_INCLUDE_DIRS if path not in include_dirs
    )
    library_dirs.extend(
        path for path in MACFUSE_LIBRARY_DIRS if path not in library_dirs
    )

    # CI / workflow：显式 -O3；Thin LTO（-flto=thin）在链接阶段跨目标文件做优化（含跨 TU 内联、DCE 等），
    # 不只是「内联」；比 full LTO 更省 CI 时间。编译与链接需同时带上。
    extra_compile_args.extend(("-O3", "-flto=thin"))
    extra_link_args.extend(("-O3", "-flto=thin"))

    return Extension(
        name,
        sources=[source],
        include_dirs=include_dirs,
        library_dirs=library_dirs,
        libraries=libraries,
        extra_compile_args=extra_compile_args,
        extra_link_args=extra_link_args,
    )


setup(
    packages=["macfusepy"],
    package_data={"macfusepy": ["*.pxd", "*.pyi", "py.typed"]},
    ext_modules=cythonize(
        [
            build_extension("macfusepy._core", "macfusepy/_core.py"),
            build_extension("macfusepy._lowlevel", "macfusepy/_lowlevel.py"),
        ],
        compiler_directives={
            "language_level": "3",
            "binding": True,
            "embedsignature": True,
            # 生成代码运行时路径：省略对 typed 缓冲/视图等的边界与负下标检查；本扩展以指针与 Python 对象为主，无 memoryview 负索引。
            "boundscheck": False,
            "wraparound": False,
            "initializedcheck": False,
        },
    ),
    options={
        "bdist_wheel": {
            "plat_name": f"macosx-12.0-{platform.machine()}",
        }
    },
)
