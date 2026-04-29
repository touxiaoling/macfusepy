macFUSE 5.0 支持多种挂载文件系统的 API。

默认情况下，macFUSE 使用 **VFS API** 挂载文件系统。若在挂载时使用选项 `-o backend=fskit`，macFUSE 将改用 **FSKit** 挂载。

## VFS API

**VFS API** 是用于开发文件系统的内核 API。APFS 及其他 Apple 文件系统均基于 VFS API 构建；开发 VFS 文件系统需要随产品交付内核扩展（kernel extension）。

macFUSE 内核扩展的开发始于十余年前，此后持续维护、改进与优化；内核代码稳定，久经实战检验。

## FSKit API

**FSKit** 为用户态（user-space）API，在 **macOS 15.4** 中引入，可视为 **VFS API** 的现代替代方案。

### Limitations（限制）

* FSKit **不支持**在 `/Volumes` 以外的挂载点（mount point）挂载。
* 文件始终以读/写（read/write）方式打开。
* **尚不支持** FUSE notification API。
* **无法**获取 `fuse_context_t` 等上下文信息（FSKit 不提供相应数据）。
* 此前多数由内核处理的挂载选项 **尚未实现**。
* FSKit 卷的 I/O 性能尚 **不及**使用内核扩展后端的卷。
