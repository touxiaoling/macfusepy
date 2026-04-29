macFUSE 提供多种 API，用于开发功能完整的用户态（user space）文件系统：

* FUSE application binary interface（应用二进制接口，ABI）。
* `libfuse.dylib`：在标准 Unix FUSE API 之上提供超集。
* `macFUSE.framework`：对 libfuse C API 的高层 Objective-C 封装。

## FUSE application binary interface（ABI）

这是 macFUSE 内核层的低阶接口；**不面向**常规文件系统开发，此处仅作完整性说明。用户态库（如 `libfuse.dylib`）通过该内核接口从 macFUSE 内核扩展接收消息（文件系统操作），并将请求所需的数据回传给内核。

内核与用户态之间传递的消息定义见 [fuse_kernel.h](https://github.com/macfuse/library/blob/master/include/fuse_kernel.h)。

macFUSE 所支持的全部 FUSE ABI 消息列表见 [[FUSE Features]]。

## libfuse.dylib

`libfuse.dylib` 同时提供低阶与高阶 API，用于开发文件系统。

`libfuse.dylib` 采用 LGPL 授权；源码位于 [library](https://github.com/macfuse/library) 仓库。

## macFUSE.framework

`macFUSE.framework` 是对 `libfuse.dylib` 高阶 API 的面向对象封装。

`macFUSE.framework` 采用 [macFUSE license](https://raw.githubusercontent.com/macfuse/macfuse/release/LICENSE.txt) 授权；源码位于 [framework](https://github.com/macfuse/framework) 仓库。

## Demos

示例见 [demo](https://github.com/macfuse/demo) 仓库。
