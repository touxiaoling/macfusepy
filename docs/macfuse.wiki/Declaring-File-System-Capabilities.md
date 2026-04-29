文件系统可根据其构建所用 API 声明能力（capabilities）。

## libfuse3.dylib

## libfuse.dylib

### Capabilities（能力标志）

* `FUSE_CAP_ATOMIC_O_TRUNC`  
  文件系统支持 `open(2)` 标志 `O_TRUNC`。

* `FUSE_CAP_XTIMES`  
  文件系统实现了 `getxtimes()` 回调，并支持为文件返回 `crtime`（创建时间）与 `bkptime`（备份时间）。

* `FUSE_CAP_CASE_INSENSITIVE`  
  文件系统为大小写不敏感（case insensitive）。默认情况下，macFUSE 文件系统为大小写敏感（case sensitive）。

* `FUSE_CAP_NODE_RWLOCK`  
  文件系统支持对 inode 结点的读/写锁（read/write node locking）。若对涉及同一结点的文件系统操作，文件系统实现是线程安全的，则应声明该能力；否则，涉及同一结点的操作将串行处理。

* `FUSE_CAP_ALLOCATE`  
  文件系统实现了 `fallocate()` 回调，并支持预分配文件空间。详见 `fcntl(2)` 中的 `F_PREALLOCATE`。

* `FUSE_CAP_EXCHANGE_DATA`  
  文件系统原生支持 `exchangedata(2)`。`exchangedata(2)` 在 macOS 10.13 起已弃用（deprecated），macFUSE 在 macOS 11 起不再提供支持。请改为实现 `renamex_np(2)` 并声明 `FUSE_CAP_RENAME_SWAP`。

* `FUSE_CAP_RENAME_SWAP`  
  文件系统实现了 `renamex()` 回调，并支持标志 `FUSE_RENAME_SWAP`。详见 `renamex_np(2)`。

* `FUSE_CAP_RENAME_EXCL`  
  文件系统实现了 `renamex()` 回调，并支持标志 `FUSE_RENAME_EXCL`。详见 `renamex_np(2)`。

* `FUSE_CAP_VOL_RENAME`  
  文件系统支持重命名已挂载的卷。注意：使用 `fsname` 挂载选项指定卷时，需要给出设备路径（device path）。

* `FUSE_CAP_ACCESS_EXTENDED`  
  文件系统在 `access()` 回调中支持下列扩展访问模式（extended access modes）：

  ```
  _READ_OK        read file data / read directory
  _WRITE_OK       write file data / add file to directory
  _EXECUTE_OK     execute file / search in directory
  _DELETE_OK      delete file / delete directory
  _APPEND_OK      append to file / add subdirectory to directory
  _RMFILE_OK      remove file from directory
  _RATTR_OK       read basic attributes
  _WATTR_OK       write basic attributes
  _REXT_OK        read extended attributes
  _WEXT_OK        write extended attributes
  _RPERM_OK       read permissions
  _WPERM_OK       write permissions
  _CHOWN_OK       change ownership
  ```

### Example

参见示例文件系统 [LoopbackFS-C](https://github.com/macfuse/demo/tree/master/LoopbackFS-C) 中的 `loopback_init()`。

```c
void *
loopback_init(struct fuse_conn_info *conn)
{
    conn->want |= FUSE_CAP_VOL_RENAME | FUSE_CAP_XTIMES | FUSE_CAP_NODE_RWLOCK;

#ifdef FUSE_ENABLE_CASE_INSENSITIVE
    if (loopback.case_insensitive) {
        conn->want |= FUSE_CAP_CASE_INSENSITIVE;
    }
#endif

    return NULL;
}
```

## macFUSE.framework

### Capabilities

* `kGMUserFileSystemVolumeSupportsExtendedDatesKey`  
  文件系统支持属性 `NSFileCreationDate` 与 `kGMUserFileSystemFileBackupDateKey`。

* `kGMUserFileSystemVolumeSupportsCaseSensitiveNamesKey`  
  文件系统为大小写敏感。默认情况下 macFUSE 文件系统为大小写敏感。

* `kGMUserFileSystemVolumeSupportsReadWriteNodeLockingKey`  
  文件系统支持读/写结点锁。若对涉及同一结点的操作，实现是线程安全的，则应声明该能力；否则，涉及同一结点的操作将串行处理。

* `kGMUserFileSystemVolumeSupportsAllocateKey`  
  文件系统实现了委托方法 `[GMUserFileSystemOperations preallocateFileAtPath:userData:options:offset:length:error:]`，并支持预分配文件空间。详见 `fcntl(2)`（`F_PREALLOCATE`）。

* `kGMUserFileSystemVolumeSupportsExchangeDataKey`  
  文件系统实现了 `[GMUserFileSystemOperations exchangeDataOfItemAtPath:withItemAtPath:error:]`，并原生支持 `exchangedata(2)`。`exchangedata(2)` 在 macOS 10.13 起已弃用，macFUSE 在 macOS 11 起不再提供支持。请改为实现 `renamex_np(2)` 并声明 `kGMUserFileSystemVolumeSupportsSwapRenamingKey`。

* `kGMUserFileSystemVolumeSupportsSwapRenamingKey`  
  文件系统支持重命名选项 `GMUserFileSystemMoveOptionSwap`。详见 `renamex_np(2)`。

* `kGMUserFileSystemVolumeSupportsExclusiveRenamingKey`  
  文件系统支持重命名选项 `GMUserFileSystemMoveOptionExclusive`。详见 `renamex_np(2)`。

* `kGMUserFileSystemVolumeSupportsSetVolumeNameKey`  
  文件系统实现了 `[GMUserFileSystemOperations setAttributes:ofFileSystemAtPath:error:]`，并支持属性 `kGMUserFileSystemVolumeNameKey`。注意：使用 `fsname` 挂载时需要指定设备路径。

### Examples

参见 [LoopbackFS-ObjC](https://github.com/macfuse/demo/tree/master/LoopbackFS-ObjC) 示例中的 `[GMUserFileSystemOperations attributesOfFileSystemForPath:error:]`。

```Objective-C
- (NSDictionary *)attributesOfFileSystemForPath:(NSString *)path
                                          error:(NSError **)error {
    NSString *p = [rootPath_ stringByAppendingString:path];
    NSDictionary *d = [[NSFileManager defaultManager] attributesOfFileSystemForPath:p error:error];
    if (d) {
        NSMutableDictionary *attribs = [NSMutableDictionary dictionaryWithDictionary:d];
        [attribs setObject:[NSNumber numberWithBool:YES]
                    forKey:kGMUserFileSystemVolumeSupportsExtendedDatesKey];

        NSURL *URL = [NSURL fileURLWithPath:p isDirectory:YES];
        NSNumber *supportsCaseSensitiveNames = nil;
        [URL getResourceValue:&supportsCaseSensitiveNames
                       forKey:NSURLVolumeSupportsCaseSensitiveNamesKey
                        error:NULL];
        if (supportsCaseSensitiveNames == nil) {
            supportsCaseSensitiveNames = [NSNumber numberWithBool:YES];
        }
        [attribs setObject:supportsCaseSensitiveNames
                    forKey:kGMUserFileSystemVolumeSupportsCaseSensitiveNamesKey];

        [attribs setObject:[NSNumber numberWithBool:YES]
                    forKey:kGMUserFileSystemVolumeSupportsSwapRenamingKey];
        [attribs setObject:[NSNumber numberWithBool:YES]
                    forKey:kGMUserFileSystemVolumeSupportsExclusiveRenamingKey];

        [attribs setObject:[NSNumber numberWithBool:YES]
                    forKey:kGMUserFileSystemVolumeSupportsSetVolumeNameKey];

        [attribs setObject:[NSNumber numberWithBool:YES]
                    forKey:kGMUserFileSystemVolumeSupportsReadWriteNodeLockingKey];

        return attribs;
    }
    return nil;
}
```

参见 [LoopbackFS-Swift](https://github.com/macfuse/demo/tree/master/LoopbackFS-Swift) 中的 `attributesOfFileSystem(forPath:)`。

```Swift
override func attributesOfFileSystem(forPath path: String!) throws -> [AnyHashable : Any] {
    let originalPath = rootPath.appending(path)

    var attributes = try FileManager.default.attributesOfFileSystem(forPath: originalPath)
    attributes[FileAttributeKey(rawValue: kGMUserFileSystemVolumeSupportsExtendedDatesKey)] = true

    let originalUrl = URL(fileURLWithPath: originalPath, isDirectory: true)

    let volumeSupportsCaseSensitiveNames = try originalUrl.resourceValues(forKeys: [.volumeSupportsCaseSensitiveNamesKey]).volumeSupportsCaseSensitiveNames ?? true
    attributes[FileAttributeKey(rawValue: kGMUserFileSystemVolumeSupportsCaseSensitiveNamesKey)] = volumeSupportsCaseSensitiveNames

    attributes[FileAttributeKey(rawValue: kGMUserFileSystemVolumeSupportsSwapRenamingKey)] = true
    attributes[FileAttributeKey(rawValue: kGMUserFileSystemVolumeSupportsExclusiveRenamingKey)] = true

    attributes[FileAttributeKey(rawValue: kGMUserFileSystemVolumeSupportsSetVolumeNameKey)] = true

    attributes[FileAttributeKey(rawValue: kGMUserFileSystemVolumeSupportsReadWriteNodeLockingKey)] = true

    return attributes
}
```
