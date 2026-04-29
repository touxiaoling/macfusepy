## 什么是 macFUSE？

macFUSE 是一套软件包，为 macOS 带来 FUSE 文件系统支持。FUSE 文件系统作为普通应用运行在用户态（user space），而不是以内核扩展（kernel extension）形式存在。许多第三方产品依赖 macFUSE 完成与文件系统的集成。

macFUSE 可用于多种场景下的文件系统开发，包括但不限于：

* 与云存储服务集成的文件系统
* 文件的透明加密与解密
* 访问 macOS 不支持的卷格式
* 应用专属的虚拟卷

## 如何安装 macFUSE？

从 https://macfuse.io 或 https://github.com/macfuse/macfuse/releases 下载最新版 macFUSE，双击下载的文件并运行安装程序。

<img width="662" src="https://user-images.githubusercontent.com/716336/232920283-01ed498e-c9f6-4bcf-a43a-bca58959498b.png">

请注意：虽然可以通过包管理器安装 macFUSE，但建议改为从 macFUSE 官网下载最新发布版。各包管理器中的 macFUSE 软件包并非由 macFUSE 开发者维护。

macFUSE 提供两种挂载（mount）后端（backend）：

* [FSKit Backend](#fskit-backend)
* [Kernel Backend](#kernel-backend)

更多信息见 [FUSE Backends](https://github.com/macfuse/macfuse/wiki/FUSE-Backends)。

### FSKit Backend

该新后端完全在用户态运行，基于新的 `FSKit` API（适用于 macOS 15.4 及更高版本）。  
不需要内核扩展（kernel extension），也无需在恢复模式（Recovery Mode）中调整安全设置。

### Kernel Backend

该后端依赖内核扩展，在用户态文件系统与 macOS 内核之间桥接；性能最佳、功能最全，但需要先在恢复模式中启用第三方内核扩展（third-party kernel extensions）的支持。

#### Enabling support for third party kernel extensions (Apple Silicon Macs)

仅在 Apple 芯片 Mac 上首次使用 macFUSE 时需要执行本步骤。若已启用第三方内核扩展支持，请直接跳到 [Allow the macFUSE kernel extension to load](#allow-the-macfuse-kernel-extension-to-load-apple-silicon-and-intel-macs) 小节（「允许加载 macFUSE 内核扩展」）。

<details>
<summary>macOS 13 及更高版本</summary>

<br>

> 在 Apple 芯片 Mac 上，首次尝试加载内核扩展时会出现如下提示：
>
> <img width="372" src="https://user-images.githubusercontent.com/716336/232904088-3a7fb9f0-560a-4d43-9828-52c2816f1539.png">
>
> 点击 「Open System Settings」（打开系统设置）。将打开 「Privacy & Security」（隐私与安全性）相关设置页面。
>
> <img width="827" src="https://user-images.githubusercontent.com/716336/232904406-fd8102df-ef11-46cc-9a0e-54b199484771.png">
>
> 默认情况下，Apple 芯片 Mac 上第三方内核扩展处于关闭状态。点击 「Enable System Extensions…」（启用系统扩展…），并在提示时输入登录密码。
>
> <img width="827" src="https://user-images.githubusercontent.com/716336/232904736-a4d30803-b24e-4167-8e8d-ecd0944f8f19.png">
>
> 点击 「Shut Down」（关机）。关机后，按住触控 ID 或电源键开机，进入恢复环境（Recovery environment）并启动 「Startup Security Utility」（启动安全性实用工具）。
>
> 若 「Startup Security Utility」未自动启动，请参见下文 [故障排查指南](#troubleshooting-guide)。
>
> <br>
> <img width="661" src="https://user-images.githubusercontent.com/716336/232919624-d90f2b4c-0be8-4f11-8488-bea023392068.png">
> <br>
> <br>
>
> 选择要更新安全策略的 macOS 卷。通常只有一个卷。随后点击 「Security Policy…」（安全策略…）按钮。
>
> <br>
> <img width="661" alt="2" src="https://user-images.githubusercontent.com/716336/232919686-341cb980-1437-428d-a052-1fe0e164d7e0.png">
> <br>
> <br>
>
> 选择 「Reduced Security」（降低安全性），并勾选 「Allow user management of kernel extensions from identified developers」（允许用户管理来自已识别开发者的内核扩展）。然后点击 「OK」，按提示输入登录密码并重新启动 Mac。

</details>

<details>
<summary>macOS 12 及更早版本</summary>

<br>

> 在 Apple 芯片 Mac 上，首次尝试加载内核扩展时会出现如下提示：
>
> <img width="372" src="https://user-images.githubusercontent.com/716336/186743673-c1862904-10c5-4f70-a3d5-07d030d3c514.png">
>
> 点击 「Open Security Preferences」（打开安全性偏好设置）。将打开 「Security & Privacy」（安全性与隐私）系统偏好设置。
>
> <img width="780" src="https://user-images.githubusercontent.com/716336/186742980-0f248522-3ac8-457e-9d12-9cfbb4567e69.png">
>
> 默认情况下，Apple 芯片 Mac 上第三方内核扩展处于关闭状态。点击窗口左下角的锁形图标并输入登录密码，然后点击 「Enable system extensions…」（启用系统扩展…）。
>
> <img width="780" src="https://user-images.githubusercontent.com/716336/186743269-829a2bc4-f52d-45d0-8534-f3be49f881a8.png">
>
> 点击 「Shut Down」（关机）。关机后，按住触控 ID 或电源键开机，进入恢复环境并启动 「Startup Security Utility」。
>
> 若 「Startup Security Utility」未自动启动，请参见下文 [故障排查指南](#troubleshooting-guide)。
>
> <br>
> <img width="729" src="https://user-images.githubusercontent.com/716336/186741210-32add05b-efd9-4633-a913-7639a77efb9e.png">
> <br>
> <br>
>
> 选择要更新安全策略的 macOS 卷。通常只有一个卷。随后点击 「Security Policy…」按钮。
>
> <br>
> <img width="729" src="https://user-images.githubusercontent.com/716336/186741256-e1e5351c-4282-40cc-950e-a5eeb22b9b26.png">
> <br>
> <br>
>
> 选择 「Reduced Security」，并勾选 「Allow user management of kernel extensions from identified developers」。然后点击 「OK」，按提示输入登录密码并重新启动 Mac。

</details>

#### Allow the macFUSE kernel extension to load (Apple Silicon and Intel Macs)

<details>
<summary>macOS 13 及更高版本</summary>

<br>

> 在 Apple 芯片与 Intel Mac 上，首次使用 macFUSE，或在安装 macFUSE 更新之后，可能出现如下提示：
>
> <img width="372" src="https://user-images.githubusercontent.com/716336/232854457-af6777ec-0835-460b-8d08-b5145838d79e.png">
>
> 点击 「Open System Settings」。
>
> <img width="827" src="https://user-images.githubusercontent.com/716336/232852468-902cc2fe-34ad-48fc-9e4f-26ec6a647979.png">
>
> 点击 「Allow」（允许）。系统将要求输入登录密码。
>
> <img width="827" src="https://user-images.githubusercontent.com/716336/232852056-d75fbefb-1738-4369-8e6e-737f015c57ad.png">
>
> 重新启动 Mac 后即可使用 macFUSE。

</details>

<details>
<summary>macOS 12 及更早版本</summary>

<br>

> 在 Apple 芯片与 Intel Mac 上，首次使用 macFUSE，或在安装 macFUSE 更新之后，可能出现如下提示：
>
> <img width="372" src="https://user-images.githubusercontent.com/716336/186746555-f213ae7f-5ac8-4038-822a-d703e925fc8a.png">
>
> 点击 「Open Security Preferences」。
>
> <img width="780" src="https://user-images.githubusercontent.com/716336/186746692-87af993b-d1e6-4136-87fb-fe0949d6c813.png">
>
> 点击窗口左下角的锁形图标并输入登录密码，然后点击 「Allow」。
>
> <img width="780" src="https://user-images.githubusercontent.com/716336/186746880-3b387c60-1e7d-44b2-9e7c-51748ed4d87b.png">
>
> 重新启动 Mac 后即可使用 macFUSE。

</details>

## Troubleshooting Guide

* 请为当前 macOS 版本安装全部可用更新，并使用最新版 macFUSE。

* 若按上述步骤操作后仍没有 「Allow」 按钮，可尝试手动加载 macFUSE 内核扩展。在 「终端」（Terminal）中执行：

  ```
  /usr/bin/sudo /usr/bin/kmutil load -p /Library/Filesystems/macfuse.fs/Contents/Extensions/15/macfuse.kext
  ```

  将上述命令中的 `15` 替换为你当前运行中的 macOS 主版本号。提示时须输入登录密码；你的用户账户需要管理员权限。

* 若多次点击 「Allow」 并按提示重启后，系统仍反复要求允许加载 macFUSE 内核扩展，很可能是遇到了 macOS 的缺陷（bug）。

  macFUSE 文件系统包（bundle）内含多个内核扩展以支持不同 macOS 版本。极少数情况下，系统会选错扩展。可运行以下命令，从 macFUSE 文件系统包中剥离未使用的扩展作为变通办法：

  ```
  /bin/bash <(curl -Ls https://gist.github.com/bfleischer/46dde8226a47f218b4d4eb8a51c50136/raw)
  ```

  你的用户账户需要管理员权限，执行时会提示输入登录密码。然后再次尝试挂载卷，并重复上文相关步骤。

* 若无法在恢复模式中访问 「Startup Security Utility」，可尝试：

  * 关闭 Mac
  * 按住电源键进入启动设置（startup settings）
  * 选择 「Options」 以进入恢复模式（recovery mode）
  * 点按菜单栏中的 Apple 标志，选择 「Startup Disk」，再选择装有 macOS 的卷并重新启动 Mac
  * 再次进入恢复模式。此时一般即可访问 「Startup Security Utility」

* 较新版本的 macOS 在外置卷启动时不再支持加载第三方内核扩展；目前没有已知变通办法。这是 macOS 的限制，而非 macFUSE 的限制。

* 较新版本的 macOS 在虚拟机中运行时也不支持加载第三方内核扩展；目前没有已知变通办法。同样是 macOS 的限制，而非 macFUSE 的限制。

* 已有记录表明：与当前运行的 macOS 版本不兼容的第三方内核扩展，可能导致系统拒绝加载兼容的第三方内核扩展（包括 macFUSE）。典型例子包括（非穷尽）：
   * 旧版 BlackBerry USB Driver（`/System/Library/Extensions/com.rim.driver.BlackBerryUSBDriverInt.kext`）
   * OpenZFS 的旧版本（`Library/Extensions/spl.kext`）

* 可向 Apple 报告问题：使用 「Feedback Assistant」 应用（可通过 Spotlight 打开，或在访达（Finder）中前往 `/System/Library/CoreServices/Applications`）。

## Notes

使用 macFUSE **无需**关闭 Gatekeeper 或系统完整性保护（System Integrity Protection，SIP）。所有官方 macFUSE 发行版均经数字签名并由 Apple Notary Service 公证，因此可与 Gatekeeper 及 SIP 协同工作。
