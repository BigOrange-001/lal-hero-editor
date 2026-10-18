英雄工坊发行许可与归属记录
========================

本目录保存许可全文与原始归属，不改变任何组件的许可，也不代替其原文。
所有网络取得的文本来自对应版本的官方源仓库；SOURCES.json 记录源 URL、
版本/源树标识、保存文件 SHA-256，及少数版权头的提取方式。
构建过程只读取这些文件，不联网获取或替换许可。

本项目与原游戏资源
------------------
PROJECT-LICENSE-AND-ASSET-NOTICE.txt 原样复制本仓库 README 的授权声明：
本项目独立编写的代码及原创改动采用 MIT；原客户端、美术、声音、商标
及第三方组件保留各自权利。MIT 不重新授予原游戏素材的使用/再分发权。
英雄图标的来源与逐文件摘要另保留在 editor/resources/icon-index.json。

Python
------
CPython/LICENSE-3.12.6.txt 是 CPython 官方 v3.12.6 的完整 LICENSE。
CPython/license-documentation-3.12.6.rst 保留同版本官方第三方归属与许可。
Qt-PySide/pyside-setup/sources/ 下另外保留 PySide/Shiboken 实际引用的
Python 3.7 派生代码声明，不将其与运行时 CPython 3.12 的版本混淆。
构建时复制的 Installed-runtime/LICENSE.txt 保留解释器安装中的声明，
但不将该文件假定为 CPython 的全部许可；其原始内容保持不变。

Qt / Qt for Python
------------------
Qt-PySide 保存 Qt 6.12.0 与 PySide6/Shiboken6 6.12.0 官方源中的许可证、
版权头、qt_attribution.json 及其指定的 LicenseFile/CopyrightFile 原文。
其中包含 LGPL 3、GPL 2/3、Qt GPL Exception、LGPL 2.1 及相应组件许可。
原安装 wheel 内的商业许可说明也会原样保留；它不是新增商业授权。

源码范围包括 qtbase（Core/Gui/Widgets/Network 等）、qtsvg、qtmultimedia、
qtimageformats 和 pyside-setup 的运行时归属。COMPONENT-ATTRIBUTIONS.json
将各原始归属汇集为可读 JSON，保留作者、版本、用途、许可和源码地址。
它保留这些模块可选编译依赖的归属超集，不声称每个条目都出现在 Windows
发行二进制中。实际发行 DLL/PYD 文件列表由构建时的 BUNDLED-FILES.json
另行记录；未使用的 Qt 模块不会因附带其许可选项而变成应用功能。

Qt/PySide 以独立动态库随完整目录提供。发行包不限制替换兼容的动态库，
也不增加禁止为调试这些库的修改而进行逆向工程的条款。本项目未修改这些
上游库；对应版本的官方源仓库地址保存在 SOURCES.json。

FFmpeg / 图像与声音组件
----------------------
FFmpeg/ 保存 Qt 6.12.0 所标明的 FFmpeg 9.0.1 上游许可和原始归属。
Qt 的原始 ffmpeg/qt_attribution.json 包含其实际预构建后端说明；附带
GPL 与 LGPL 的上游许可文本用于完整保留选项，不宣称启用了可选 GPL 代码。
FFmpeg 的原始版权及许可声明未修改。归属声明中的 libjpeg 代码已在 FFmpeg
上游进行修改；原始文件头保留其标记，详细变更可在 SOURCES.json 对应的
官方 n9.0.1 源码及该版本历史中查看。本项目未进一步修改这些库。

This software is based in part on the work of the Independent JPEG Group.

Qt 的 libjpeg/libpng/zlib/FreeType/HarfBuzz/PCRE 等归属保存在各源码路径。
Pillow 安装包的完整 LICENSE 同时包含它使用的图像组件及其第三方声明，
构建时按实际安装版本原样复制，不以 Qt 的同名组件许可替代 Pillow 的声明。

发行时生成的记录
----------------
各实际安装的 Python 依赖会附带其 dist-info 许可证、notices 和 METADATA；
包括 Pillow、PySide6、Shiboken6、tzdata，以及构建工具 PyInstaller 等。
INSTALLED-LICENSES.json 记录实际依赖版本和随附文件摘要及来源。
BUNDLED-FILES.json 记录应用发行目录中的 DLL/PYD 相对路径与大小。
本文件只是文件与来源索引；各许可条款以随附原文为准。
