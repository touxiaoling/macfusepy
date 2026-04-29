macFUSE 是一套软件包，让 macOS 支持第三方用户态（user space）文件系统。这些文件系统的内容可以来自本地磁盘、云存储服务或其他任意来源。大量第三方产品依赖 macFUSE 实现与文件系统的集成。

借助 macFUSE，开发者不必编写任何内核代码即可实现文件系统：文件系统逻辑在用户态运行，macFUSE 内核扩展（kernel extension）则作为与真实内核接口之间的「桥梁」。

详细安装说明见 [[Getting Started]]。

关于 macFUSE
-------------

该软件包提供多种 API，用于开发功能完整的用户态文件系统。`libfuse.dylib` 在标准 Unix FUSE API 之上提供超集；`macFUSE.framework` 则是对 libfuse C API 的高层 Objective-C 封装。

借助这些 API，开发者可以实现多种形态的文件系统，例如：落地（on-disk）文件系统、分层（layering）文件系统、网络/分布式文件系统等。三种常见用途是：访问云端文件、访问 macOS 本身不原生支持的文件系统卷，以及对文件做透明加解密。

macFUSE 文件系统与普通应用程序一样（与内核扩展相对），因此在编程语言、调试器和第三方库的选择上，与开发常规 macOS 应用同样灵活。

社区 wiki
--------------

社区 wiki 已迁移至 https://github.com/macfuse/community/wiki。
