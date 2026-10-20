from pathlib import Path
import sys,json,collections
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'server')]
from editor.catalog import Catalog
from mod_native import OP_LABELS,argument_label,ability_contract,contracts
c=Catalog();abi=ability_contract()['mechanisms'];ops=collections.defaultdict(list)
for r in c.skills:
    for a in r['actions']:ops[a[0]].append((r,a))
lines=['# 战斗机制与编辑器覆盖目录','','生成来源：当前仓库实际配置与客户端复合机制参数契约。运行 `python -B scripts/generate_battle_editor_catalog.py` 更新。', '',f'当前 **{len(c.skills)} 条技能全部可导入编辑器完整模板**；包含 **{len(ops)} 种原生动作、{len(abi)} 类复合机制、{sum(map(len,abi.values()))} 个复合机制可调参数**。这些是技能条目数，包含品质变体，不是去重后的英雄技能数。','','## 从游戏逻辑到编辑器','','| 游戏逻辑 | 编辑入口 | 导出字段 |','| --- | --- | --- |','| 施放等待、冷却、射程、生命条件、AOE、站桩 | 基础与触发 | `nativeTemplate.settings.pl` |','| 被动触发（0～19） | 基础与触发 → 被动触发方式 | `passiveTrigger`，绑定英雄时编译为 `skill_diff` |','| 伤害、控制、位移、召唤等执行步骤 | 动作 / 选敌 / 条件 / 附加效果 | `actions[].type/arguments` |','| 单动作选敌、上限、锁定、目标组、筛选 | 同页字段树 | `actionTargetPolicies/MaxTargets/Locks/Groups/PolicyArgs` |','| 成长、伤害分摊、说明、召唤与分身策略 | 成长 / 分组 / 召唤 / 联动 | `skillUp/skillUpPaths/damageShareGroups/manualSummonPolicy/manualClonePolicy` |','| 专属复合技能内部数值与条件阈值 | 复合机制内部数值与条件 | `abilityParameters` |','','树中的列表索引从 0 开始；动作列表显示从 1 开始的可读序号。数字、开关、资源、列表与对象均有结构化控件，无需修改原始 JSON。原生复合机制保留游戏已有执行流程，数值与条件阈值由参数契约提供；增加新的脚本算法仍需开发游戏引擎。','','## 全部原生动作','','参数列按原生位置列出。具体数组长度取决于所选原版预设，最后的视觉特效可从已安装资源选择。','','| 类型 | 编辑器名称 | 参数 | 使用条目数 | 示例来源 |','| --- | --- | --- | ---: | --- |']
for kind,uses in sorted(ops.items()):
    row,raw=uses[0];args='、'.join(argument_label(kind,i,raw[1:]) for i in range(1,len(raw)))
    lines.append(f'| `{kind}` | {OP_LABELS.get(kind,kind)} | {args} | {len({r["id"] for r,a in uses})} | {row["name"]} · `{row["id"]}` |')
lines += ['', '`hitup` / `fleeup` 保留原版历史动作数据；当前执行器没有对应增益执行分支。模板导入保持原有行为，名称不代表新增了实际增益算法。', '', '## 复合机制参数','','每个参数保留默认值、类型、合法范围、中文用途及代码来源上下文。施放条件与执行参数均通过固定数据接口读取；不载入外部脚本。','','| 机制 | 示例技能 | 参数数量 | 参数示例 |','| --- | --- | ---: | --- |']
for kind,descriptors in abi.items():
    rows=[r for r in c.skills if any(a[0]=='manual_ability' and a[1]==kind for a in r['actions'])]
    names='、'.join(r['name'] for r in rows[:2]);labels='、'.join(d.get('label',k) for k,d in list(descriptors.items())[:3])
    lines.append(f'| `{kind}` | {names} | {len(descriptors)} | {labels} |')
lines += ['', '完整参数契约见 [native_ability_parameters.json](../server/native_ability_parameters.json)。', '', '## 选敌、条件与关联','','已安装选敌策略：'+ '、'.join('`'+p+'`' for p in sorted(contracts(c.base)['policies']))+'。','','条件字符串按已有原生动作提供，包括施放前持续伤害、灼烧、流血、生命阈值、主目标及击杀链条件。条件的执行语义由对应原生动作决定，不能把一种动作的条件任意套到另一种动作。分路筛选提供 `all/same_as_caster/same_as_center`，排序支持原生 `nearest`。','','拖动动作会同步：目标锁、中心与主目标索引、排除目标集合、前置持续状态索引、伤害共享组、成长路径、等级说明和动作内部来源引用。非法前向依赖会拒绝，删除被引用动作会拒绝，原数据保持不变。','','被动枚举：0 无额外触发，1 未命中，2 暴击，3 击杀，4 邪恶，5 沉默，6 眩晕，7 灼烧，8 破甲，9 中毒，10 虚弱，11 护盾，12 净化，13 强化，14 四属性，15 祝福，16 双抗，17 嘲讽，18 无上述状态，19 控制／负面状态。','','## 身份、兼容与安全边界','','模板的 `source/sourceDigest` 指向不可变原版机制来源，包内 `id` 是自制技能身份。编译器生成私有运行 ID，并另外写入受校验的机制来源标识；不能依靠改名绕过角色专属派发。来源变动需要重新导入审核，合包不会改变机制来源。','','原生模板需要 `skill.native-template.v1`；1.0.3 机制与限时神佑条件需要 `skill.native-template.103`；通用事件被动需要 `skill.events.v1`。客户端在请求中声明支持。服务端检查激活、登录及玩法请求；仅升级编辑器不能让旧客户端执行新格式。原有命名字段的 16 动作格式继续兼容。','','校验覆盖已知动作与形状、有限数值、参数范围、资源与单位引用、来源摘要、动作关联、成长路径和召唤策略。所有包仍经过相同的配额、依赖与冲突校验，不提供 AS3/SWF/eval 或外部代码加载。','','## 验证范围','','核心检查见 `scripts/check_native_templates.py`：全量往返、逐技能编辑、合法重排、五批真实包导入导出、合包、坏契约拒绝及实际 Qt 控件编辑保存。本次 1.0.3 更新与审查修复按用户要求不运行上述检查、客户端编译、游戏实战或 APK/AIR 打包。目录由配置生成，列出覆盖范围并不表示通过运行测试。', '', '格式与操作见 [作者规范](mod-authoring.md)、[使用指南](hero-pack-editor-guide.md)、[Schema](../schemas/mod-native-template.schema.json)。','']
(ROOT/'docs/battle-mechanism-editor-catalog.md').write_text('\n'.join(lines),'utf-8')
print('Generated full battle/editor catalogue')
