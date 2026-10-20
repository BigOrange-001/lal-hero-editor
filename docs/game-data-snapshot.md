# 游戏配置与离线协议快照

来源：[BigOrange-001/lal-rebuild](https://github.com/BigOrange-001/lal-rebuild)，提交 `9f95b38d84bc98e11159d43669b1d54c0372e845`（[游戏 PR #21](https://github.com/BigOrange-001/lal-rebuild/pull/21)，待合并，以正式1.0.3 main 5b6bccd为基线）。GAME_VERSION 为1.0.3；编辑器版本独立维护，见 VERSION 与 editor/app.py。

GAME_SOURCE.json记录共享Python模块、JSON配置和Schema的来源与SHA-256。离线编辑器通过共享的mod_authoring_103顺序投影1.0.3英雄、技能书、平衡、DOT和皮肤技能；数值快照为纯模块native_skill_snapshot，不包含战斗执行器。只复制依赖闭包内的55个文件；gateway、客户端执行资源和玩家数据库不包含在内。

编辑器的包扫描类型修复已被游戏PR #19与正式1.0.3吸收，本轮与游戏快照重新一致。新增skill.native-template.103和skill.events.v1的校验与编译代码、Schema与游戏PR #21同步；来源状态不把未合并分支记为main。文件统一使用LF，并去除player_store继承的额外EOF空行。

本轮按用户要求未运行功能测试或打包。已生成Schema，静态核对Python语法、共享内容、来源摘要和提取数值快照实现。新通用事件接口需要包含游戏PR #21的新版客户端，现有1.0.3正式APK和1.1.4编辑器发行版均不自动获得这些接口。

预览素材沿用原有内置资源，不加入个人美术。素材与第三方代码的权利范围见仓库README和许可证。
