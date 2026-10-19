> 开发中：1.2.0-dev 增加效果序列、状态条件和自定义召唤物；配套游戏接口已完成用户示例实机验证；编辑器新版未独立打包发布，未运行自动化测试。详见 [接口说明](docs/mod-effect-sequence.md)。正式发行仍为下列 1.1.4。

# 英雄工坊（lal-hero-editor）

版本：**1.1.4**。适配游戏 **1.0.2 / Mod API 1**。

1.1.4 将英雄包编辑器从游戏仓库独立，保留完整的离线创作、校验和 Windows EXE 构建能力；同步游戏 PR #17 的动作引用与技能参数边界修复，保留旧版合法英雄包兼容性。

基于《撸啊撸／最强王者》重构项目的 Windows 可视化英雄包创作工具。支持新建 `new` 英雄、以 `replace` 方式编辑原有英雄并导出标准 `patch` 补丁，提供技能编排、原版资源选择、面板基准、立绘与卡面制作、包校验和多个包合并导出。草稿保存为 `.lalhero`，游戏安装使用 `.heropack`。

## 下载与运行

从 [Releases](https://github.com/BigOrange-001/lal-hero-editor/releases/latest) 下载 Windows x64 ZIP，完整解压后运行 `HeroPackEditor.exe` 或 `启动英雄工坊.cmd`。请保留 `_internal`、资源和许可证目录；发行版不需要另外安装 Python。

编辑器离线运行，不修改已安装游戏或玩家存档。导出的包需要在支持对应能力的 [游戏项目](https://github.com/BigOrange-001/lal-rebuild) 中导入、预览并启用。原生技能模板要求 `skill.native-template.v1`；带独立边框定位的卡面要求 `asset.image.card-frame`。

## 构建与运行

源码开发使用 Windows x64 / Python 3.12。标准发行使用 Python 3.12.6 和已锁定的 Qt、Pillow、PyInstaller 版本，随包提供对应第三方许可文本。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r editor\requirements.txt
.\.venv\Scripts\python.exe -B scripts\hero_editor.py
```

只构建编辑器 EXE：

```powershell
.\.venv\Scripts\python.exe -B scripts\build_hero_editor.py
```

构建结果位于 `build/hero-editor-release-1.1.4/`，包含完整运行目录、ZIP、依赖许可证、源码摘要和发行校验值。不需要 Java、AIR SDK、FFDec 或游戏构建工具。更新打包依赖时应同步许可来源与摘要，不能跳过许可证完整性检查。

## 创作能力

- **英雄与补丁**：同包多个英雄和技能；原值／摘要守卫、依赖、版本与冲突校验；获取渠道、玩法开关及补丁适用范围。
- **技能编排**：全部 **1077** 条原版技能模板、**73** 种原生动作、**44** 类专属复合机制与 **324** 个参数；拖动排序同步引用，支持选敌、条件、分组、成长、召唤、分身和被动触发。旧版 16 动作格式继续兼容。
- **面板与基准**：物理／魔法／真实普攻；五种品质和不同职责的真实配置参考，按定位自动填充后可手动调整。
- **卡面制作**：原版盾形透明框、盾形选区、正选／反选笔、透明通道与出框人物；新素材固定框在下、人物在上，框体像素默认不选，布局以盾框而非图片留白为边界。
- **详情页立绘**：与卡面独立导入和绑定。白／绿／蓝／紫／橙画布分别锁定为 200×200、300×225、400×250、500×275、600×300；人物等比适配、底部对齐，空余透明。
- **合包与导出**：多个包合并为新身份，重写实体与引用，保留来源和默认设置；导出前使用游戏实际协议与编译规则校验，不执行外部脚本。

本工具不执行游戏战斗、不提供自动抠图服务；透明人物需要导入已带透明通道的原图。校验通过表示包满足当前协议和配置规则，最终技能表现仍需在匹配的游戏版本中确认。

## 文档与核心检查

- [使用与构建指南](docs/hero-pack-editor-guide.md)
- [开发目标与验收要求](docs/hero-pack-editor-requirements.md)
- [实现范围与验证记录](docs/hero-pack-editor-implementation.md)
- [战斗机制与编辑器目录](docs/battle-mechanism-editor-catalog.md)
- [英雄包作者规范](docs/mod-authoring.md)
- [协议与配置来源](docs/game-data-snapshot.md)

```powershell
python -B scripts/hero_editor.py --check-install --report build/install-check.json
python -B scripts/check_native_templates.py
python -B scripts/check_card_frame.py
python -B -m unittest server.test_mod_native_review
```

检查仅使用临时工程与离线配置，不需要启动游戏或读取存档。`server/` 保留游戏共享校验模块及其导入依赖的原目录结构，不是可启动的服务端；`client/resources/app/assets/` 仅用于素材查阅与试听，不包含可执行客户端和 SWF 运行资源。

## 授权声明


本项目为非官方的本地重构项目。MIT 许可仅适用于本项目独立编写的服务器、工具代码及原创改动，不覆盖原客户端代码、游戏图像、音频、商标或第三方组件。随仓库提供的原游戏资源及模板权利仍归原权利人；本项目不重新授予这些内容的使用或再分发权。构建依赖分别遵循其原有许可。

### MIT License

Copyright (c) 2026 BigOrange-001

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
