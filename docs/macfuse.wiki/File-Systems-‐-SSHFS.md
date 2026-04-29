**SSHFS** 让你通过 **SFTP** 挂载远端文件系统。多数 SSH 服务器默认开启 SFTP。更多说明见 https://github.com/libfuse/sshfs。

## 安装（Installation）

可从 https://macfuse.io 或 SSHFS 仓库发布页 https://github.com/libfuse/sshfs/releases 下载 SSHFS 安装包。

面向 macFUSE 的官方 SSHFS 安装包均已签名。可在安装窗口右上角点击锁形图标核验签名。正式发布使用证书 「Developer ID Installer: Benjamin Fleischer (3T5GSNBU6W)」 签名。

<img width="732" alt="Screenshot 2024-12-09 at 18 00 14" src="https://github.com/user-attachments/assets/c05bb664-bdc9-43a2-ac22-4110dace7b10">

面向 macFUSE 的官方 SSHFS 发布：

* SSHFS 3.7.5（macOS 10.9+，Apple Silicon 与 Intel，macFUSE 4.10+）<br>
  源码：https://github.com/libfuse/sshfs/tree/sshfs-3.7.5<br>
  下载：https://github.com/libfuse/sshfs/releases/download/sshfs-3.7.5/sshfs-3.7.5.pkg<br>
  SHA-256: 611713612179cf7ccd2995051165da7d19e0ca199ae70d9680c3d3551f456d46

* SSHFS 3.7.3 (ccb6821)（macOS 10.9+，Apple Silicon 与 Intel，macFUSE 4.10+）<br>
  源码：https://github.com/libfuse/sshfs/tree/ccb6821<br>
  下载：https://github.com/libfuse/sshfs/releases/download/sshfs-3.7.3/sshfs-3.7.3-ccb6821.pkg<br>
  SHA-256: 4ea567bc7b0435caa1d69a6621b4fdf1af67e847ef9203552131ad35b714d8cb

* SSHFS 2.10 (3ea4c59)（macOS 10.9+，Apple Silicon 与 Intel）<br>
  源码：https://github.com/libfuse/sshfs/tree/3ea4c59<br>
  下载：https://github.com/libfuse/sshfs/releases/download/sshfs-2.10/sshfs-2.10-3ea4c59.pkg<br>
  SHA-256: 4e125e88beaa35fdefd631498146319999f4ee802acfc8fce00cad967a7a17bb

## 卸载（Uninstallation）

SSHFS **不含**卸载程序。要移除 SSHFS，在「终端」中执行：

```
sudo rm /usr/local/bin/sshfs
sudo rm /usr/local/share/man/man1/sshfs.1
sudo pkgutil --forget io.macfuse.installer.components.sshfs
```

## 常见问题（Frequently Asked Questions）

### 我在 SSHFS 里发现了 bug，应该到哪里报告？

请在 SSHFS 仓库提交 issue：https://github.com/libfuse/sshfs/issues

## 许可（License）

SSHFS 采用 [GNU General Public License, Version 2](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html) 授权。

SSHFS 使用 **GLib**（GTK+、GNOME 等项目的底层基础库）。GLib 的说明与源码见 https://gitlab.gnome.org/GNOME/glib/。GLib 采用 [GNU Lesser General Public License, Version 2.1](https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html) 授权。
