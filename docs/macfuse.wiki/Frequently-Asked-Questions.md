## 如何卸载 macFUSE？

卸载 macFUSE：从 https://macfuse.io 或 https://github.com/macfuse/macfuse/releases 下载当前 macFUSE 安装磁盘映像并打开，在映像的 `Extras` 文件夹中运行 Uninstaller 应用，即可完整移除 macFUSE。

## 无法在 NTFS 卷上编辑文件，或无法向该卷复制新文件，是怎么回事？

macFUSE 提供的是用于开发文件系统的 SDK，可用于开发能够访问 NTFS 卷的第三方文件系统。**仅** macFUSE 本身**并不**提供对 NTFS 卷的访问能力。

你需要的是实际的 NTFS 文件系统实现，例如 **NTFS-3G**。NTFS-3G 为跨平台软件，在 macOS 上依赖 macFUSE。请注意 NTFS-3G 与 macFUSE 是彼此独立的项目；对 NTFS 卷的访问支持不在 macFUSE 项目范围内。
