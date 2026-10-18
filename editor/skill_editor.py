"""Structured API-1 skill editor; list order is the exported action order."""
from __future__ import annotations

import copy
import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFormLayout,
    QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSplitter,
    QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from .widgets import RefCombo, ResourcePreview, combo, integer, number

ACTIONS = {
    'damage': '伤害', 'cure': '治疗', 'shield': '攻击倍率护盾',
    'hp_shield': '生命倍率护盾', 'caster_hp_shield': '施法者生命护盾',
    'target_hp_shield': '目标生命护盾', 'stun': '眩晕', 'silence': '沉默',
    'weak': '虚弱', 'sunder': '破甲', 'poison': '中毒', 'burn': '灼烧',
    'strong': '强化', 'purify': '净化', 'armor': '自身护甲', 'move_to_target': '移动至敌方目标',
}
BENEFICIAL = {'cure', 'shield', 'hp_shield', 'caster_hp_shield', 'target_hp_shield', 'strong', 'purify', 'armor'}
POLICIES = {
    'ally_all': '我方全场', 'ally_all_lowest_hp_ratio': '我方全场最低生命比例',
    'ally_lane_all': '我方本路全体', 'ally_lane_highest_attack_any': '我方本路最高攻击',
    'ally_lane_lowest_current_hp_any': '我方本路最低当前生命',
    'ally_lane_lowest_current_hp_hero': '我方本路最低当前生命英雄',
    'ally_lane_lowest_hp_ratio_any': '我方本路最低生命比例',
    'ally_lane_lowest_hp_ratio_hero': '我方本路最低生命比例英雄',
    'ally_lane_lowest_hp_ratio_n': '我方本路低生命比例前 N 个', 'ally_self': '施法者自身',
    'enemy_global_highest_attack_hero': '敌方全场最高攻击英雄',
    'enemy_global_highest_hpmax_hero': '敌方全场最高生命上限英雄',
    'enemy_global_lowest_current_hp': '敌方全场最低当前生命',
    'enemy_global_lowest_hp_ratio_hero': '敌方全场最低生命比例英雄',
    'enemy_global_lowest_hpmax': '敌方全场最低生命上限',
    'enemy_lane_all': '敌方本路全体', 'enemy_lane_farthest': '敌方本路最后排',
    'enemy_lane_frontmost': '敌方本路最前排',
    'enemy_lane_highest_attack_hero': '敌方本路最高攻击英雄',
    'enemy_lane_lowest_current_hp_hero': '敌方本路最低当前生命英雄',
    'enemy_lane_lowest_hp_ratio_any': '敌方本路最低生命比例',
    'enemy_lane_lowest_hp_ratio_n': '敌方本路低生命比例前 N 个',
}


class ActionList(QListWidget):
    moveRequested = Signal(int, int)

    def __init__(self):
        super().__init__()
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setMinimumWidth(225)
        self.setToolTip('拖动动作改变实际结算顺序。依赖与升级索引会同步重映射；不能把被锁定动作移到引用它的动作之后。')

    def dropEvent(self, event):
        old = self.currentRow()
        new = self.indexAt(event.position().toPoint()).row()
        if new < 0:
            new = self.count() - 1
        elif self.dropIndicatorPosition() == QAbstractItemView.DropIndicatorPosition.BelowItem and new < old:
            new += 1
        elif self.dropIndicatorPosition() == QAbstractItemView.DropIndicatorPosition.AboveItem and new > old:
            new -= 1
        event.ignore()
        if old >= 0 and old != new:
            self.moveRequested.emit(old, new)


class SkillEditor(QWidget):
    changed = Signal()
    error = Signal(str)

    def __init__(self, catalog, project, parent=None):
        super().__init__(parent)
        self.catalog, self.project = catalog, project
        self.skill = None
        self.action_index = -1
        self.loading = False
        layout = QVBoxLayout(self)
        title = QLabel('技能编辑 · API 1')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        basics = QWidget()
        form = QFormLayout(basics)
        self.id = QLineEdit()
        self.name = QLineEdit()
        self.description = QTextEdit()
        self.description.setMaximumHeight(95)
        self.rank_template = QLineEdit()
        self.rank_template.setPlaceholderText('选填；原版转换时保留。{rank:动作索引:字段索引} 显示百分数，{flat:动作索引:字段索引} 显示整数。索引从 0 起。')
        self.rank_template.setToolTip('等级说明模板只支持 rank/flat 数值占位。动作重排会同步索引；清空后使用普通说明。')
        self.warmup, self.cooldown = integer(0, 0, 100), integer(1, 1, 100)
        self.range = integer(1500, 0, 10000)
        self.target = combo([(label, key) for key, label in POLICIES.items()], 'enemy_lane_frontmost')
        self.aoe = integer(0, -1, 6)
        aoe_help = ('AOE 指范围／群体作用。此处保留原版引擎的旧 AOE 参数，不是范围半径。'
                    '\n自定义技能建议保持 0；实际作用对象主要由“动作与结算顺序”中的“本动作目标”和“最大目标数 N”决定。'
                    '\n例如本路最多攻击 3 人：本动作目标选“敌方本路全体”，最大目标数设为 3，并设置足够射程。'
                    '只选“本路全体”但最大目标数仍为 1，仍只作用于 1 个目标。')
        self.aoe.setToolTip(aoe_help)
        self.ban_stand = QCheckBox('站桩时禁止施放（banStand）')
        self.ban_stand.setChecked(True)
        for label, field in [('技能本地 ID *', self.id), ('名称 *', self.name), ('说明 *', self.description), ('等级说明模板（选填）', self.rank_template),
                             ('首次等待 *（施法者行动机会）', self.warmup), ('冷却 *（施法者行动机会）', self.cooldown),
                             ('射程 *', self.range), ('默认目标 *', self.target), ('AOE 约定（选填）', self.aoe)]:
            form.addRow(label, field)
        aoe_note = QLabel(aoe_help)
        aoe_note.setObjectName('muted')
        aoe_note.setWordWrap(True)
        form.addRow('AOE 说明', aoe_note)
        form.addRow(self.ban_stand)
        hint = QLabel('触发计时：ownerTurns；首次等待与冷却按施法者行动机会计算。\n状态持续时间遵循目标的原生行动回合。技能等级固定为 1 ～ 10。\n动作按下页列表从上到下结算；没有隐含递归、自动重放或组合条件脚本。')
        hint.setWordWrap(True)
        form.addRow(hint)
        self.tabs.addTab(basics, '基础与触发')

        actions = QWidget()
        action_layout = QVBoxLayout(actions)
        buttons = QHBoxLayout()
        for text, callback in [('添加动作', self.add_action), ('删除动作', self.remove_action),
                               ('上移', lambda: self.move_action(self.action_index, self.action_index-1)),
                               ('下移', lambda: self.move_action(self.action_index, self.action_index+1))]:
            button = QPushButton(text)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        buttons.addStretch()
        action_layout.addLayout(buttons)
        splitter = QSplitter()
        self.actions = ActionList()
        splitter.addWidget(self.actions)
        action_scroll = QScrollArea()
        action_scroll.setWidgetResizable(True)
        editor = QWidget()
        self.action_form = QFormLayout(editor)
        self.action_type = combo([(label, key) for key, label in ACTIONS.items()], 'damage')
        self.coefficient = number(1, 0, 1000, 4, .1)
        self.damage_type = combo([('物理', 'physical'), ('魔法', 'magic')])
        self.duration = integer(1, 1, 100)
        self.amount = number(0.1, 0, 1000, 4, .05)
        self.effect = RefCombo(catalog.references('skillEffect'))
        self.action_target = combo([('跟随技能默认目标', None)] + [(label, key) for key, label in POLICIES.items()])
        self.max_targets = integer(1, -1, 6)
        self.max_targets.setToolTip('-1：全部有效目标；1～6：最多 N 个；0 无效。位移动作只能选择 1 个目标。')
        self.distance = integer(0, 0, 10000)
        self.distance.setToolTip('0：移动至目标；正数：本次位移距离上限。仍使用原生碰撞和站位规则，不保证落点重合。')
        self.lock_only = QCheckBox('仅复用前序目标，不再次按目标策略筛选')
        self.lock_only.setToolTip('必须先选择更早的同阵营动作。用于保留原版突进后继续攻击同一目标的机制。')
        self.lock = combo([('不锁定前序目标', None)])
        for label, field in [('动作类型 *', self.action_type), ('系数（按类型必填）', self.coefficient),
                             ('伤害类型', self.damage_type), ('持续目标行动回合', self.duration),
                             ('附加量 amount', self.amount), ('视觉特效（可不播放）', self.effect),
                             ('本动作目标', self.action_target), ('最大目标数 N', self.max_targets),
                             ('位移距离上限', self.distance),
                             ('复用前序动作的目标', self.lock), ('锁定方式', self.lock_only)]:
            self.action_form.addRow(label, field)
        self.effect_preview = ResourcePreview(catalog, project)
        self.action_form.addRow(self.effect_preview)
        self.action_help = QLabel()
        self.action_help.setWordWrap(True)
        self.action_form.addRow(self.action_help)
        action_scroll.setWidget(editor)
        splitter.addWidget(action_scroll)
        splitter.setStretchFactor(1, 3)
        action_layout.addWidget(splitter)
        self.tabs.addTab(actions, '动作与结算顺序')

        upgrades = QWidget()
        upgrade_layout = QVBoxLayout(upgrades)
        row = QHBoxLayout()
        add = QPushButton('添加等级成长')
        remove = QPushButton('删除所选成长')
        add.clicked.connect(lambda: self.add_upgrade())
        remove.clicked.connect(self.remove_upgrade)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch()
        upgrade_layout.addLayout(row)
        self.upgrades = QTableWidget(0, 3)
        self.upgrades.setHorizontalHeaderLabels(['动作', '成长字段', '每级增加（1 → 10）'])
        self.upgrades.horizontalHeader().setStretchLastSection(True)
        upgrade_layout.addWidget(self.upgrades)
        self.level = integer(1, 1, 10)
        level_row = QHBoxLayout()
        level_row.addWidget(QLabel('预览技能等级'))
        level_row.addWidget(self.level)
        level_row.addStretch()
        upgrade_layout.addLayout(level_row)
        self.level_preview = QLabel()
        self.level_preview.setWordWrap(True)
        upgrade_layout.addWidget(self.level_preview)
        upgrade_layout.addWidget(QLabel('计算：基础参数 + 每级增加 × (等级 − 1)。全等级必须在 0 ～ 1000 内；同动作同字段只允许一条成长。'))
        self.tabs.addTab(upgrades, '等级 1 ～ 10')

        reuse = QWidget()
        reuse_layout = QVBoxLayout(reuse)
        self.builtin = RefCombo(catalog.references('skillTemplate'), optional=False)
        reuse_layout.addWidget(QLabel('全部原版技能均可导入完整可编辑模板；包含原生复合机制、召唤、分身和被动触发。'))
        reuse_layout.addWidget(self.builtin)
        self.template_button = QPushButton('导入所选原版技能为完整可编辑模板')
        self.template_button.clicked.connect(self.convert_template)
        reuse_layout.addWidget(self.template_button)
        self.builtin_info = QLabel()
        self.builtin_info.setWordWrap(True)
        reuse_layout.addWidget(self.builtin_info)
        coverage = QPushButton('查看全部原版技能机制覆盖清单')
        coverage.clicked.connect(self.show_coverage)
        reuse_layout.addWidget(coverage)
        limitation = QLabel('导入后切换到完整机制编辑页：按字段调整原生参数、条件、成长和动作顺序。旧版空白动作工程继续兼容。\n英雄包仅包含结构化数据，不导入任意执行代码／SWF；自制特效动画、缘分与进度迁移仍属于独立接口。')
        limitation.setWordWrap(True)
        reuse_layout.addWidget(limitation)
        reuse_layout.addStretch()
        self.tabs.addTab(reuse, '复用与机制覆盖')

        self.actions.currentRowChanged.connect(self.select_action)
        self.actions.moveRequested.connect(self.move_action)
        self.action_type.currentIndexChanged.connect(self.action_type_changed)
        self.effect.currentTextChanged.connect(lambda: self.effect_preview.show_reference(self.effect.value()))
        self.builtin.currentTextChanged.connect(self.describe_builtin)
        self.level.valueChanged.connect(self.refresh_level_preview)
        for field in [self.id, self.name, self.description, self.rank_template, self.warmup, self.cooldown, self.range, self.target,
                      self.aoe, self.ban_stand, self.coefficient, self.damage_type, self.duration, self.amount,
                      self.effect, self.action_target, self.max_targets, self.lock, self.lock_only, self.distance]:
            signal = (getattr(field, 'valueChanged', None) or getattr(field, 'currentTextChanged', None) or
                      getattr(field, 'textChanged', None) or getattr(field, 'toggled', None))
            if signal:
                signal.connect(self.mark_changed)
        self.describe_builtin()
        from .native_skill_editor import NativeSkillEditor
        self.native_editor=NativeSkillEditor(catalog,project,self)
        self.native_editor.changed.connect(self.mark_changed)
        self.native_editor.error.connect(self.error)
        layout.addWidget(self.native_editor)
        self.native_editor.hide()

    def mark_changed(self, *_):
        if not self.loading:
            self.changed.emit()

    def bind(self, skill, action_index=0):
        if skill.get('model')=='native-template-v1':
            self.skill=skill;self.tabs.hide();self.native_editor.show();self.native_editor.bind(skill,action_index)
            return
        self.native_editor.hide();self.tabs.show()
        self.loading = True
        self.skill = skill
        self.action_index = -1
        self.id.setText(str(skill.get('id', '')))
        self.name.setText(str(skill.get('name', '')))
        self.description.setPlainText(str(skill.get('description', '')))
        self.rank_template.setText(skill.get('rankInfoTemplate', ''))
        self.warmup.setValue(skill.get('warmup', 0))
        self.cooldown.setValue(skill.get('cooldown', 1))
        self.range.setValue(skill.get('range', 1500))
        self.target.setCurrentIndex(max(0, self.target.findData(skill.get('targetPolicy'))))
        self.aoe.setValue(skill.get('aoe', 0))
        self.ban_stand.setChecked(skill.get('banStand', True))
        self.actions.clear()
        for index, action in enumerate(skill.get('actions', [])):
            self.actions.addItem(f'{index+1}. {ACTIONS.get(action.get("type"), action.get("type", "?"))}')
        self.upgrades.setRowCount(0)
        for upgrade in skill.get('upgrades', []):
            self.add_upgrade(upgrade)
        self.actions.setCurrentRow(min(action_index, self.actions.count()-1))
        self.loading = False
        self.refresh_level_preview()

    def flush_action(self):
        if self.skill is None or not 0 <= self.action_index < len(self.skill['actions']):
            return
        kind = self.action_type.currentData()
        action = {'type': kind, 'effect': self.effect.value(), 'maxTargets': self.max_targets.value()}
        if self.action_target.currentData() is not None:
            action['targetPolicy'] = self.action_target.currentData()
        if kind == 'move_to_target':
            action['distance'] = self.distance.value()
        elif kind != 'purify':
            action['coefficient'] = self.coefficient.value()
        if kind in {'damage', 'stun', 'silence', 'weak', 'sunder', 'poison'}:
            action['damageType'] = self.damage_type.currentData()
        if kind not in {'damage', 'cure', 'move_to_target'}:
            action['duration'] = self.duration.value()
        if kind in {'weak', 'sunder', 'poison'}:
            action['amount'] = self.amount.value()
        if self.lock.currentData() is not None:
            action['lockToAction'] = self.lock.currentData()
        if self.lock_only.isChecked():
            action['lockOnly'] = True
        self.skill['actions'][self.action_index] = action

    def flush(self):
        if self.skill is not None and self.skill.get('model')=='native-template-v1':
            return self.native_editor.flush()
        if self.skill is None:
            return
        identity = self.id.text().strip()
        if identity != self.skill.get('id'):
            index = next(i for i, row in enumerate(self.project.data['skills']['skills']) if row is self.skill)
            self.project.rename('skills', index, identity)
        self.flush_action()
        self.skill.update(name=self.name.text().strip(),
                          description=self.description.toPlainText(), timingUnit='ownerTurns',
                          warmup=self.warmup.value(), cooldown=self.cooldown.value(), range=self.range.value(),
                          targetPolicy=self.target.currentData(), maxLevel=10, aoe=self.aoe.value(),
                          banStand=self.ban_stand.isChecked())
        if self.rank_template.text():
            self.skill['rankInfoTemplate'] = self.rank_template.text()
        else:
            self.skill.pop('rankInfoTemplate', None)
        self.skill['upgrades'] = self.upgrade_values()

    def upgrade_values(self):
        return [{'action': self.upgrades.cellWidget(i, 0).currentData(),
                 'field': self.upgrades.cellWidget(i, 1).currentData(),
                 'perLevel': self.upgrades.cellWidget(i, 2).value()} for i in range(self.upgrades.rowCount())]

    def select_action(self, index):
        if not self.loading:
            self.flush_action()
        self.action_index = index
        if self.skill is None or not 0 <= index < len(self.skill.get('actions', [])):
            return
        was_loading, self.loading = self.loading, True
        action = self.skill['actions'][index]
        self.action_type.setCurrentIndex(max(0, self.action_type.findData(action.get('type'))))
        self.coefficient.setValue(action.get('coefficient', 1))
        self.damage_type.setCurrentIndex(max(0, self.damage_type.findData(action.get('damageType', 'physical'))))
        self.duration.setValue(action.get('duration', 1))
        self.amount.setValue(action.get('amount', 0.1))
        self.effect.set_value(action.get('effect'))
        self.action_target.setCurrentIndex(max(0, self.action_target.findData(action.get('targetPolicy'))))
        self.max_targets.setValue(action.get('maxTargets', 1))
        self.distance.setValue(action.get('distance', 0))
        self.lock_only.setChecked(action.get('lockOnly', False))
        self.lock.clear()
        self.lock.addItem('不锁定前序目标', None)
        for i, earlier in enumerate(self.skill['actions'][:index]):
            self.lock.addItem(f'{i+1}. {ACTIONS.get(earlier.get("type"), "动作")}', i)
        self.lock.setCurrentIndex(max(0, self.lock.findData(action.get('lockToAction'))))
        self.action_type_changed()
        self.effect_preview.show_reference(self.effect.value())
        self.loading = was_loading

    def action_type_changed(self, *_):
        kind = self.action_type.currentData()
        self.coefficient.setEnabled(kind not in {'purify', 'move_to_target'})
        self.damage_type.setEnabled(kind in {'damage', 'stun', 'silence', 'weak', 'sunder', 'poison'})
        self.duration.setEnabled(kind not in {'damage', 'cure', 'move_to_target'})
        self.distance.setEnabled(kind == 'move_to_target')
        self.lock_only.setEnabled(kind != 'move_to_target')
        self.amount.setEnabled(kind in {'weak', 'sunder', 'poison'})
        if not self.loading:
            if kind == 'move_to_target':
                self.max_targets.setValue(1)
                self.lock_only.setChecked(False)
            policy = self.action_target.currentData() or self.target.currentData() or ''
            if kind == 'armor' or policy.startswith('ally_') != (kind in BENEFICIAL):
                wanted = 'ally_self' if kind in BENEFICIAL else 'enemy_lane_frontmost'
                self.action_target.setCurrentIndex(self.action_target.findData(wanted))
        self.action_help.setText('结算单位：系数沿用游戏原生公式；伤害各自动作独立经过防御与命中。\n' +
                                 ('此动作为友方效果。' if kind in BENEFICIAL else '此动作为敌方效果。') +
                                 ('护甲动作当前仅允许施法者自身。' if kind == 'armor' else '') +
                                 '\n目标锁只能指向同阵营的更早动作；调整顺序时自动维护关联。')
        if kind == 'move_to_target':
            self.action_help.setText('移动至选定敌方目标；距离 0 表示不额外限制，正数限制本次移动距离。\n此动作不造成伤害；可将后续伤害／控制锁定到它选中的目标。最大目标数必须为 1。')
        self.mark_changed()

    def add_action(self, *_):
        if self.skill is None:
            return
        if len(self.skill.get('actions', [])) >= 32:
            self.error.emit('一个技能最多 32 个动作。')
            return
        self.flush()
        self.skill.setdefault('actions', []).append({'type': 'damage', 'coefficient': 1.0,
            'damageType': 'physical', 'effect': None, 'targetPolicy': 'enemy_lane_frontmost'})
        self.bind(self.skill, len(self.skill['actions'])-1)
        self.changed.emit()

    def remove_action(self, *_):
        if self.action_index < 0:
            return
        try:
            self.flush()
            self.project.remove_action(self.skill, self.action_index)
            self.bind(self.skill, max(0, self.action_index-1))
            self.changed.emit()
        except Exception as error:
            self.error.emit(str(error))

    def move_action(self, old, new):
        if self.skill is not None and self.skill.get('model')=='native-template-v1':
            return self.native_editor.move_action(old,new)
        if self.skill is None or old == new or not (0 <= new < len(self.skill['actions'])):
            return False
        try:
            self.flush()
            self.project.reorder_actions(self.skill, old, new)
            self.bind(self.skill, new)
            self.changed.emit()
            return True
        except Exception as error:
            self.error.emit('顺序未改变：' + str(error))
            return False

    def add_upgrade(self, value=None):
        if self.skill is None:
            return
        value = value if isinstance(value, dict) else {'action': max(0, self.action_index), 'field': 'coefficient', 'perLevel': 0.1}
        row = self.upgrades.rowCount()
        if row >= 128:
            self.error.emit('最多 128 条等级成长。')
            return
        self.upgrades.insertRow(row)
        action = combo([(f'{i+1}. {ACTIONS.get(a.get("type"), "动作")}', i) for i, a in enumerate(self.skill.get('actions', []))], value.get('action', 0))
        field = combo([('系数 coefficient', 'coefficient'), ('附加量 amount', 'amount')], value.get('field', 'coefficient'))
        increase = number(value.get('perLevel', 0), -1000, 1000, 4, .1)
        for column, widget in enumerate((action, field, increase)):
            self.upgrades.setCellWidget(row, column, widget)
            signal = getattr(widget, 'valueChanged', None) or widget.currentIndexChanged
            signal.connect(self.mark_changed)
            signal.connect(self.refresh_level_preview)
        self.mark_changed()

    def remove_upgrade(self):
        row = self.upgrades.currentRow()
        if row >= 0:
            self.upgrades.removeRow(row)
            self.mark_changed()
            self.refresh_level_preview()

    def refresh_level_preview(self, *_):
        if self.skill is None:
            return
        values = copy.deepcopy(self.skill.get('actions', []))
        if 0 <= self.action_index < len(values):
            current = {'coefficient': self.coefficient.value(), 'amount': self.amount.value()}
            for field in ('coefficient', 'amount'):
                if field in values[self.action_index]:
                    values[self.action_index][field] = current[field]
        for up in self.upgrade_values():
            if isinstance(up['action'], int) and 0 <= up['action'] < len(values) and up['field'] in values[up['action']]:
                values[up['action']][up['field']] += up['perLevel']*(self.level.value()-1)
        self.level_preview.setText('\n'.join(f'{i+1}. {ACTIONS.get(a.get("type"), "动作")}　' + '　'.join(f'{key}={a[key]:g}' for key in ('coefficient', 'amount') if key in a) for i, a in enumerate(values)))

    def describe_builtin(self, *_):
        reference = self.builtin.value()
        row = self.catalog.skill(str(reference).split('/')[-1]) if reference else None
        convertible = bool(row and row.get('editable') and row.get('authored'))
        self.template_button.setEnabled(convertible)
        self.template_button.setToolTip('将完整机制转换为可编辑动作。' if convertible else
                                       '当前包规范无法完整表达此技能，不能转换；可引用的技能仍可直接在英雄技能槽选用。')
        if not row:
            self.builtin_info.setText('选择已有技能，查看可引用、可转换状态。')
            return
        self.builtin_info.setText(f'{row.get("name", "")}\n{row.get("description", "")}\n' +
                                   ('可直接引用。' if row.get('reusable') else '不可安全引用。') +
                                   ('可转换成 API 1 模板。' if row.get('editable') else '不能转换成自定义动作。') +
                                   '\n' + str(row.get('reason', '')))
        if row.get('reusable') and not convertible:
            self.builtin_info.setText(self.builtin_info.text() +
                '\n使用方法：回到英雄属性，在普通／队长／被动技能槽直接选择此原版技能，保留完整机制。'
                '\n拆开编辑需要同步扩展游戏端包规范、编译器和编辑器；不能忽略不支持的动作。')

    def convert_template(self):
        reference = self.builtin.value()
        row = self.catalog.skill(str(reference).split('/')[-1]) if reference else None
        if not row or not row.get('editable') or not row.get('authored'):
            self.error.emit('该机制不能转换：' + str((row or {}).get('reason', '请选择支持的内置技能。')))
            return False
        if QMessageBox.question(self, '替换当前技能内容', '用内置模板替换当前技能的触发、动作与成长？保留当前本地 ID。') != QMessageBox.StandardButton.Yes:
            return False
        self.flush()
        identity = self.skill['id']
        template = copy.deepcopy(row['authored'])
        template['id'] = identity
        self.skill.clear()
        self.skill.update(template)
        self.bind(self.skill)
        self.changed.emit()
        return True

    def show_coverage(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('原版技能 → API 1 编辑器覆盖清单')
        dialog.resize(1100, 680)
        layout = QVBoxLayout(dialog)
        coverage = self.catalog.coverage()
        summary = QLabel(str(coverage.get('summary', '')) if isinstance(coverage, dict) else str(coverage))
        summary.setWordWrap(True)
        layout.addWidget(summary)
        search = QLineEdit()
        search.setPlaceholderText('按名称、ID、机制或缺口搜索')
        layout.addWidget(search)
        table = QTableWidget(len(self.catalog.skills), 5)
        table.setHorizontalHeaderLabels(['技能', '完整引用', '动作模板', '机制/缺口说明', '实际动作'])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for i, skill in enumerate(self.catalog.skills):
            values = [f'{skill.get("name", "")} ({skill["id"]})', '支持' if skill.get('reusable') else '不支持',
                      '支持' if skill.get('editable') else '不支持', skill.get('reason', ''),
                      json.dumps(skill.get('actions'), ensure_ascii=False)]
            for j, value in enumerate(values):
                table.setItem(i, j, QTableWidgetItem(str(value)))
        table.resizeColumnsToContents()
        layout.addWidget(table)
        search.textChanged.connect(lambda text: [table.setRowHidden(i, text.casefold() not in ' '.join(table.item(i,j).text() for j in range(5)).casefold()) for i in range(table.rowCount())])
        dialog.exec()
