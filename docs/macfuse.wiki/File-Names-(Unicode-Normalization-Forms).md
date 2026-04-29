## Unicode 等价性（Unicode Equivalence）

Unicode 标准允许用不同的码点（code point）序列表示同一字符。这些序列在视觉与行为上应一致，此时称这些序列等价（equivalent）；但其字节串表示并不相同，长度也可能不同。因此比较两个 Unicode 字符串前必须进行 Unicode 规范化（normalization）。详见 https://unicode.org/reports/tr15/ 及其中示例。

本文关注以下两种 Unicode 规范化形式（normalization forms）：

* Normalization Form D（NFD）
* Normalization Form C（NFC）

许多字符既可作组合字符（composite），也可作预组合字符（precomposed）。在 NFD 下，这些字符会被分解（decomposed）；在 NFC 下通常保持预组合（precomposed）。NFD 的字节串一般比 NFC **更长**。

## 对 macFUSE 意味着什么？

与 APFS 类似，macFUSE 支持文件名在 **NFC 形式**下不超过 255 字节。

但访达（Finder）期望文件名为 **NFD 形式**（通常更长）。因此从文件系统实现向 macFUSE 传递文件名时，请使用 **NFD**。若使用 NFC，可能导致异常行为，例如在某些条件下 Finder 不显示文件名。参见 [Technical Q&A QA1173](https://developer.apple.com/library/archive/qa/qa1173/_index.html)。

macFUSE 允许在 `readdir` 回调中返回最长 **1024 字节**的文件名，从而可返回 Finder 所需的较长 NFD 形式非拉丁文件名；但所有文件名的 **NFC 形式**仍须满足 255 字节上限。
