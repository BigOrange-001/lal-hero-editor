# 游戏配置与离线协议快照

来源：[BigOrange-001/lal-rebuild](https://github.com/BigOrange-001/lal-rebuild)，提交 `b12c2e2d04b7613bc0f4b9e1bf21838ecc17f89b`（合并 PR #17）。游戏版本 1.0.2、引擎 API 1。编辑器版本独立维护，见 VERSION 与 editor/app.py；游戏版本见 GAME_VERSION。

GAME_SOURCE.json 记录共享 Python 模块、JSON 配置与公开 Schema 的来源和 SHA-256。这些文件按原路径保留，确保与游戏导入器使用相同的基线覆盖、摘要、资源规则和配置编译；24 个 Python 模块包括静态导入依赖。离线编辑器没有 gateway、网络监听入口、游戏存档或客户端执行文件。

预览素材由原项目的 editor/resources 以及 assets/audio、assets/textures、assets/licenses 提供。SWF、字体运行包和 APK 未随工具源码复制。图集中的 ATF 只用于资源存在性与目录描述；可直接显示的英雄图标使用独立 PNG。

同步协议时，从明确的游戏提交复制 GAME_SOURCE.json 中的文件，更新摘要并执行全技能模板与包往返核心检查。需要同步动作语义或派发逻辑的改动应先在游戏项目实现，编辑器不自行创造游戏接口。

1.1.4 包含合并审查修复：两类遗漏的动作引用参与重排／删除检查，锐雯两个取模基数不接受零值。只允许这次收紧范围前的已知旧协议摘要，且旧包仍按新范围检查，不自动放行未来不同协议。
