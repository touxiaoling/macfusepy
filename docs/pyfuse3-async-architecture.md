# pyfuse3 异步架构参考

本文记录 `~/python/pyfuse3` 中异步 FUSE 实现对本仓库的参考价值，供后续继续实现
asyncio-only 运行时或 low-level spike 时查阅。

## 背景

本仓库的目标是面向 macOS、macFUSE 5.2+ 和 Python 3.14+ 的小型 libfuse3 绑定。
公开 API 只支持 asyncio 回调模型，用户传给 `FUSE` 的对象必须继承
`macfusepy.Operations`，覆盖的操作必须是 `async def`。

当前公开运行时建立在 libfuse low-level session 之上：

- `macfusepy._lowlevel` 负责绑定 `fuse_lowlevel_ops`、创建 session、接收请求并用
  `fuse_reply_*` 回复内核。
- `macfusepy.lowlevel_async` 把 `fuse_session_fd()` 接入 asyncio selector loop，驱动
  session fd pump。
- `macfusepy._runtime` 把用户面对的 path-based `Operations` 适配到 low-level inode
  请求，内部维护 lookup/forget、inode 生命周期和目录分页。
- `macfusepy._core` 只保留请求上下文、`fuse_exit()` 和 libfuse 版本查询等小型辅助。

这个模型的优点是 API 仍保持 path-based 简洁性，同时避免 high-level `fuse_main`
同步回调桥。代价是运行时需要在 Python 层维护 inode、目录项和请求回复状态。

## pyfuse3 的总体结构

`pyfuse3` 的主实现是 low-level libfuse API。它暴露的是 inode-based 用户模型，而不是
path-based high-level 模型。核心文件大致如下：

- `src/pyfuse3/__init__.pyx`：Cython 扩展主入口，维护全局 `fuse_session`、
  `fuse_lowlevel_ops`、session fd 和主循环。
- `src/pyfuse3/internal.pxi`：session pump、worker 调度、参数转换和内部工具。
- `src/pyfuse3/handlers.pxi`：每个 low-level FUSE 回调的 C/Python 桥接，以及
  `fuse_reply_*` 回复逻辑。
- `src/pyfuse3/_pyfuse3.py`：公开的 `Operations` 基类、类型别名和文档。
- `src/pyfuse3/asyncio.py`：把内部 trio 依赖替换成 asyncio 兼容层的适配文件。

需要特别注意：`pyfuse3` 官方实现默认依赖 trio。它的 asyncio 支持不是另一套完整
实现，而是通过 `pyfuse3.asyncio.enable()` 把模块内的 `trio` 引用替换成一个 fake
trio 模块。

## pyfuse3 的 asyncio 适配层

`src/pyfuse3/asyncio.py` 提供了少量 trio 兼容接口：

- `enable()`：把 `pyfuse3.trio` 指向 `pyfuse3.asyncio` 本身。
- `Lock = asyncio.Lock`。
- `wait_readable(fd)`：用 `loop.add_reader(fd, future.set_result, None)` 等待
  session fd 可读。
- `notify_closing(fd)`：给等待 fd 的 future 设置 `ClosedResourceError`。
- `_Nursery` / `open_nursery()`：用 `asyncio.create_task()` 和 `asyncio.wait()` 模拟
  trio nursery。

这层对本仓库的直接参考价值有限，因为本仓库不需要兼容 trio。后续实现应直接使用
asyncio 原生 API，例如 `asyncio.TaskGroup`、`loop.add_reader()`、`loop.remove_reader()`、
`asyncio.to_thread()`，而不是引入 fake trio 抽象。

## pyfuse3 的 low-level session pump

`pyfuse3` 真正值得参考的部分是 `internal.pxi` 中的 session pump。

它的核心流程是：

1. `init()` 调用 `fuse_session_new()` 创建 low-level session。
2. `fuse_session_mount()` 挂载后，保存 `fuse_session_fd(session)`。
3. `main()` 打开 nursery，启动至少一个 `_session_loop()` worker。
4. `_session_loop()` 等待 session fd 可读。
5. fd 可读后调用 `fuse_session_receive_buf(session, &buf)`。
6. 随后调用 `fuse_session_process_buf(session, &buf)`。
7. `process_buf` 进入某个 low-level C 回调，回调创建对应 coroutine 并保存到全局
   `py_retval`。
8. `_session_loop()` 在 `process_buf` 返回后等待 `py_retval`，用户操作完成后调用
   对应的 `fuse_reply_*` 回复内核。

它还维护了 worker 数量：

- `min_tasks` 和 `max_tasks` 控制最少和最多 worker。
- `read_lock` 确保同一时间只有一个 worker 真正等待和读取 session fd。
- 如果没有空闲 reader 且 worker 数量未达上限，会启动新 worker。
- 如果空闲 reader 太多，worker 会主动退出。

这套模型说明 low-level asyncio 实现不必把所有 FUSE 请求串行化到一个桥接线程中。
session fd 仍然只有一个读取入口，但每个请求可以自然落到 coroutine 中执行，并在完成时
调用 `fuse_reply_*`。

## 请求分发和错误处理

`handlers.pxi` 中每个 FUSE 操作一般分成两层：

- C 回调只复制必要参数到 `_Container`，然后把 async handler 保存为待等待的返回值。
- async handler 调用用户的 `Operations` 方法，捕获 `FUSEError`，最后调用
  `fuse_reply_err()`、`fuse_reply_attr()`、`fuse_reply_buf()`、`fuse_reply_open()` 等
  回复函数。

这种结构已经体现在当前 low-level 运行时中，但公开用户 API 仍保持 path-based，
因此两者职责不同：

- `pyfuse3` 用户操作返回 inode、`EntryAttributes`、`FileInfo` 等 low-level 对象。
- 本仓库当前用户操作返回 path-based high-level 结果，例如 `stat` 映射、文件句柄、
  字节串和目录项 iterable。
- `pyfuse3` 把 `lookup`、`forget` 和 inode 生命周期暴露给 inode-based 用户模型；
  本仓库把这些复杂度收敛在 `_runtime.py` 内部。

后续优化应继续沿用“C 回调复制参数，Python coroutine 负责执行业务并回复内核”的
分层，而不是恢复 high-level `fuse_main` 桥。

## readdir 和目录分页

`pyfuse3` 的 `readdir` 是 token-based：

- 用户实现 `Operations.readdir(fh, start_id, token)`。
- 用户对每个目录项调用 `readdir_reply(token, name, attr, next_id)`。
- 当 `readdir_reply()` 返回 `False` 时，说明内核提供的缓冲区已满，用户应停止写入。
- `next_id` 会在后续 `readdir` 调用中作为 `start_id` 传回。

它的文档明确要求：`next_id` 必须在目录项增删时仍然尽量避免重复返回或跳过目录项。

当前 path-based API 中，`Operations.readdir()` 可以返回：

- `name`
- `(name, attrs)`
- `(name, attrs, next_offset)`

这里已经保留了 `next_offset` 表达能力，但文档和测试可以继续借鉴 `pyfuse3` 的语义：
如果文件系统选择提供 offset，应保证 offset 是稳定游标，而不只是列表下标。简单文件
系统可以继续返回 `0` 或省略 offset，让运行时按普通 path-based 语义处理。

## cache notify 和阻塞风险

`pyfuse3` 暴露了几类通知能力：

- `invalidate_inode()`：让内核丢弃某个 inode 的属性或数据缓存。
- `invalidate_entry()`：让内核丢弃父目录下某个名字的目录项缓存。
- `invalidate_entry_async()`：把目录项失效请求放入后台线程队列，避免在 request handler
  中阻塞。
- `notify_store()`：把数据写入内核 page cache。

这些 API 的重要设计点不是具体函数名，而是它们对阻塞风险的处理。部分 libfuse notify
调用可能等待内核完成相关请求。如果在相关请求 handler 内直接调用，或在持有用户锁时
调用，可能造成死锁。

如果本仓库未来暴露缓存失效能力，应优先采用类似策略：

- 默认提供不会阻塞事件循环的异步入口。
- 对底层可能阻塞的 notify 操作使用后台线程或队列。
- 明确记录不能在相关请求、持锁区域或需要当前事件循环继续处理请求时同步调用。
- 对错误只在可观察位置记录日志，避免后台 notify 失败影响正在处理的请求。

## 对本仓库可直接借鉴的设计

可借鉴的设计点：

- 使用 `fuse_session_fd()` + `loop.add_reader()` 把 FUSE session 接入 asyncio selector。
- 把 low-level C 回调拆成“参数复制”和“async handler 回复内核”两层。
- 用任务组管理多个请求处理任务，并在退出时统一取消或等待。
- 为 session fd 关闭提供显式唤醒机制，避免 worker 永久等待可读事件。
- 对 `readdir` offset 语义写清楚，测试目录变更时的稳定性。
- 对 cache invalidation 和 notify 操作提供异步队列，避免 handler 内死锁。
- 在文档里明确“用户 async 回调不等于底层所有 I/O 都自动非阻塞”，阻塞本地 I/O 仍需
  `asyncio.to_thread()` 或专门的异步客户端。

## 不应引入的内容

不建议从 `pyfuse3` 引入的内容：

- trio 兼容层或 fake trio 抽象。本仓库只支持 asyncio，应使用 asyncio 原生结构。
- Linux、FreeBSD、FUSE 2.x、Python 旧版本或 `/proc` 相关兼容路径。
- 把公开 API 直接切成 inode-based。那会引入 lookup count、forget、硬链接和负缓存
  语义，适合 low-level 模块，但不适合当前小型 high-level API。
- 直接复制 LGPL-2.1+ 源码。本仓库当前许可证是 ISC，后续应只参考设计，不复制实现。
- 全局 session 状态作为长期公开模型。实验 spike 可以短期使用，公开运行时应尽量把
  session、operation table 和事件循环状态封装到对象里。

## 可能的演进路径

短期保持现状：

- 继续完善 `_runtime.py` 的 path-based asyncio-only 运行时。
- 保持 `Operations` 的 path-based 用户体验。
- 加强文档，说明 low-level session 运行时和 path-based 适配层的性能边界。

中期完善 low-level 运行时：

- 在 Cython 边界补齐 `fuse_session_new()`、`fuse_session_mount()`、
  `fuse_session_fd()`、`fuse_session_receive_buf()`、`fuse_session_process_buf()`、
  `fuse_session_exit()`、`fuse_session_unmount()`、`fuse_session_destroy()` 和常用
  `fuse_reply_*` 声明。
- 继续收紧 `AsyncFuseSessionPump` 和真实 session wrapper 的边界。
- 用 asyncio `TaskGroup` 管理请求任务和 session pump 生命周期。
- 先实现只读 inode tree：`lookup`、`getattr`、`opendir`、`readdir`、`open`、`read`、
  `release`、`forget`。
- 明确 low-level API 暂不公开，避免过早承诺兼容性。

长期再考虑公开 low-level API：

- 只有当 path-based high-level API 的桥接成本或语义限制成为真实瓶颈时，再考虑公开
  inode-based API。
- 如果公开，应与 high-level API 并存，而不是替换现有 `Operations`。
- 公开前需要系统性测试 lookup count、forget、多 hardlink、目录分页、缓存失效、
  卸载退出和异常路径。

## 结论

`pyfuse3` 最有价值的是 low-level session pump 和请求回复模型，而不是它的 asyncio
兼容层。本仓库应继续坚持 asyncio-only、macOS-only 和小型 high-level API 的边界。
后续优化应继续围绕 `macfusepy._lowlevel`、`macfusepy.lowlevel_async` 和 `_runtime.py`
推进，保持 asyncio 原生、对象封装良好且不复制 LGPL 源码。
