# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Cursor Task 与子代理

**优先用 Task 子代理**承担可并行的重活，避免主对话上下文被海量检索输出占满。

**适合交给子代理：**跨目录探索与关键词定位、多步只读调查、可写清验收标准的独立子任务、长时间或需密切跟进的 shell/构建（按需后台运行）。

**不必强行子代理：**目标与改动点已明确的一两处编辑、单文件小补丁、读一两个已知路径即可回答的问题。

**模型 `gpt-5.5-high`：**当任务明显依赖复杂推理、多方案权衡、或大范围理解后再下结论时，可在发起 Task 时指定 **`gpt-5.5-high`**；在适当的时机灵活切换使用。若用户点名其它模型 slug，仅使用平台当前允许列表中的值，不可用则如实说明。


## 2. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 3. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 4. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 5. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

**约束：**子代理看不到本会话的隐含约定，须在 Task 的说明里写清工作目录、目标、交付格式与仓库级约束（例如本文件中的支持策略与测试要求）。

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

# 项目上下文

这个仓库是仅面向 macOS 的 macFUSE 5.2+ libfuse3 Python 绑定。它使用
Cython 纯 Python 语法实现编译核心，并通过 `macfusepy` 包暴露一组小型高级
Python API。

## 支持策略

- 仅支持 Python 3.14 或更新版本。
- 仅支持 macFUSE 5.2 或更新版本。
- 仅支持 macOS 26.4 或更新版本。
- 不要添加 Linux、FreeBSD、Python 2、FUSE 2.x、osxfuse 或 ctypes 兼容路径。
- 在这个分支上工作时，优先替换过时兼容代码，而不是继续保留它。

## 工具链

- 使用 `uv` 管理 Python 环境和包。
- 除非用户明确要求，否则不要引入 `pip`、`virtualenv`、Poetry、Hatch 或 tox
  工作流。
- 将构建元数据保留在 `pyproject.toml` 中，将扩展构建细节保留在
  `setup.py`。

常用命令：

```bash
uv sync
uv run python setup.py build_ext --inplace
uv run pytest
uv run pytest --run-benchmarks -m benchmark tests/test_benchmarks.py
```

扩展构建需要安装带有 libfuse3 头文件的 macFUSE 5.2+。当前构建会在可用时使用
`pkg-config fuse3`，并检查常见的 macFUSE 头文件和库文件路径。

## 架构

- `macfusepy/_core.py`：保留 libfuse 请求上下文、`fuse_exit` 和版本查询的小型
  Cython 纯 Python 扩展。
- `macfusepy/_lowlevel.py`：绑定 libfuse low-level API，创建 session、处理请求并调用
  `fuse_reply_*` 回复。
- `macfusepy/_runtime.py`：公开的同步 `FUSE` 运行时，以
  `InodeOperations` 为核心；path-based `Operations` 只作为易用层适配到 low-level
  inode 请求。
- `macfusepy/fuse3.pxd`：libfuse3 C API 的 Cython 声明。
- `macfusepy/operations.py`：高级 path-based `Operations`、inode-first
  `InodeOperations` 基类和日志 mixin。
- `macfusepy/types.py`：向用户代码暴露的 libfuse3 结构体小型 Python 包装器。
- `macfusepy/errors.py`：供操作抛出 errno 值的 `FuseOSError`。
- `macfusepy/lowlevel_async.py`：同步 session pump 和 low-level helper 类型。
  `LowLevelAttr`、`LowLevelEntry` 作为 `InodeOperations` 的轻量辅助类型通过包根导出；
  其余内容仍是运行时内部支撑。
- `examples/`：示例文件系统，应与 libfuse3 操作签名保持一致。
- `tests/`：覆盖公共 API 行为和示例的 pytest 测试。

## 实现说明

- 保持 `macfusepy/__init__.py` 的公共导入面小而明确；新增公开类型时同步更新
  `tests/test_public_api.py` 和 README。
- 公开 API 只支持同步回调模型；传给 `FUSE` 的对象必须继承 `InodeOperations`
  或 `Operations`，覆盖的操作必须是普通 `def`。性能敏感路径优先使用
  `InodeOperations`。
- 当前公开模型建立在 libfuse low-level session 之上；low-level 回调同步执行用户
  方法并立即用 `fuse_reply_*` 回复。
- 不要为用户暴露异步操作兼容层，也不要把 `_lowlevel.py` 或整个 `lowlevel_async.py`
  作为稳定公共 API 导出；只通过包根暴露经过测试的轻量 low-level 类型。
- 运行时始终使用 libfuse 的多线程 low-level session loop；用户回调可能并行进入，
  文件系统实现必须自行保护共享状态。
- 操作签名应遵循 libfuse3/macFUSE 5.2+ 行为，包括 libfuse3 提供的文件句柄和
  flags 参数。
- 示例传入或返回的文件时间戳应使用纳秒。
- Python 操作错误应抛出 `FuseOSError(errno_value)`，这样回调可以向 libfuse
  返回负 errno 值。
- `InodeOperations` 是一等核心接口，直接暴露 parent inode、inode、bytes 名字和
  文件句柄，适合性能敏感或已经维护 inode 表的文件系统；path-based `Operations`
  由运行时维护 lookup/forget、inode 生命周期、目录分页和请求回复状态，只承担
  标准化和易用层职责。
- 围绕 Cython 边界做聚焦修改；更新单个操作或结构体映射时避免大范围重构。

## 语言规范

- `CLAUDE.md`、`README`、项目文档和代码注释都应使用中文。代码标识符、
  shell 命令、错误字符串、上游 API 名称和协议术语在保留原文更清晰时可保留原文。

## 测试说明

- 在运行会导入 `macfusepy._core` 的测试前，先执行
  `uv run python setup.py build_ext --inplace`。
- 当前测试套件使用 `uv run pytest` 运行。
- benchmark 测试默认跳过；只跑 benchmark 用
  `uv run pytest --run-benchmarks -m benchmark tests/test_benchmarks.py`。
- `mounted_fuse` 相关测试会真实挂载并在 teardown 中尝试 `/sbin/umount` 和
  `/usr/sbin/diskutil unmount force`；排查挂载子进程时可设置 `macfusepy_TEST_DEBUG=1`。
- 测试可能要求本机安装兼容的 macFUSE，因为 `libfuse_version()` 来自编译扩展。

## 可以参考学习

官方有一个 pyfuse3 的异步实现，但它只支持 trio。需要了解曾经的 low-level 异步
设计时，可以看 `~/python/pyfuse3` 和 `doc/pyfuse3-async-architecture.md`。