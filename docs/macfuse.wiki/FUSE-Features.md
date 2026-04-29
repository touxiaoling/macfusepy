macFUSE 支持 FUSE ABI 版本 7.8 至 7.19，但并非所有 FUSE 操作（operations）与通知（notifications）均已实现。

## Operations（操作）

### 已支持的操作（Supported Operations）

#### 标准操作（Standard operations）

* `FUSE_LOOKUP`
* `FUSE_FORGET`
* `FUSE_GETATTR`
* `FUSE_SETATTR`
* `FUSE_READLINK`
* `FUSE_SYMLINK`
* `FUSE_MKNOD`
* `FUSE_MKDIR`
* `FUSE_UNLINK`
* `FUSE_RMDIR`
* `FUSE_RENAME`
* `FUSE_LINK`
* `FUSE_OPEN`
* `FUSE_READ`
* `FUSE_WRITE`
* `FUSE_STATFS`
* `FUSE_RELEASE`
* `FUSE_FSYNC`
* `FUSE_SETXATTR`
* `FUSE_GETXATTR`
* `FUSE_LISTXATTR`
* `FUSE_REMOVEXATTR`
* `FUSE_FLUSH`
* `FUSE_INIT`
* `FUSE_OPENDIR`
* `FUSE_READDIR`
* `FUSE_RELEASEDIR`
* `FUSE_FSYNCDIR`
* `FUSE_ACCESS`
* `FUSE_CREATE`
* `FUSE_INTERRUPT`
* `FUSE_DESTROY`        
* `FUSE_IOCTL`
* `FUSE_FALLOCATE`

#### macOS 特有操作（macOS-specific Operations）

* `FUSE_SETVOLNAME`
* `FUSE_GETXTIMES`（deprecated，已弃用）
* `FUSE_EXCHANGE`（deprecated，已弃用）

### 不支持的操作（Unsupported operations）

* `FUSE_GETLK`
* `FUSE_SETLK`
* `FUSE_SETLKW`
* `FUSE_BMAP`
* `FUSE_POLL`
* `FUSE_NOTIFY_REPLY`
* `FUSE_BATCH_FORGET`

## Notifications（通知）

### 已支持的通知（Supported notifications）

* `FUSE_NOTIFY_INVAL_INODE`
* `FUSE_NOTIFY_INVAL_ENTRY`
* `FUSE_NOTIFY_DELETE`

### 不支持的通知（Unsupported notifications）

* `FUSE_NOTIFY_POLL`
* `FUSE_NOTIFY_STORE`
* `FUSE_NOTIFY_RETRIEVE`
