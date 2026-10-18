"""Chinese, offline PySide6 workbench for the game's real hero package format."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QTemporaryDir
from PySide6.QtGui import QAction, QCloseEvent, QFont, QKeySequence, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDockWidget, QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QMenu,
    QScrollArea, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit,
    QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .core import Project
from .skill_editor import SkillEditor
from .widgets import (
    BenchmarkDialog, CHANNELS, FlagsEditor, ImageEditorDialog, QUALITY,
    RefCombo, ResourcePreview, SCOPES, STATS, combo, integer, number,
)

THEME = """
QWidget { background:#111923; color:#dce5ee; font-family:'Microsoft YaHei UI','Microsoft YaHei','Segoe UI'; font-size:13px; }
QMainWindow, QDialog { background:#101720; }
QToolBar { background:#182230; border:0; padding:10px; spacing:7px; }
QToolButton, QPushButton { background:#263447; border:1px solid #394a62; border-radius:6px; padding:7px 12px; color:#edf4fa; min-height:19px; }
QPushButton:hover, QToolButton:hover { background:#34475f; border-color:#5b88a1; }
QPushButton:pressed, QToolButton:pressed { background:#1b8c85; }
QPushButton:disabled, QToolButton:disabled { color:#6a7b8c; background:#1b2531; border-color:#2a3645; }
QPushButton[primary="true"], QToolButton[primary="true"] { background:#168d86; border-color:#24b5a8; color:white; font-weight:600; }
QPushButton[primary="true"]:hover { background:#21aaa0; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox { background:#0e1620; border:1px solid #354458; border-radius:5px; padding:6px; selection-background-color:#267f83; }
QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border:1px solid #3bc9b4; }
QComboBox QAbstractItemView { background:#1a2634; color:#e8eef6; selection-background-color:#31506b; border:1px solid #4c6179; }
QGroupBox { background:#18222e; border:1px solid #2e3b4e; border-radius:8px; margin-top:19px; padding:14px 11px 11px; font-weight:600; }
QGroupBox::title { subcontrol-origin:margin; subcontrol-position:top left; padding:0 8px; color:#8de1d4; }
QGroupBox QLabel { background:transparent; font-weight:400; }
QGroupBox QLineEdit, QGroupBox QTextEdit, QGroupBox QComboBox, QGroupBox QSpinBox, QGroupBox QDoubleSpinBox { background:#0e1620; }
QTreeWidget, QListWidget, QTableWidget { background:#151e29; alternate-background-color:#1a2633; border:1px solid #2d3d50; border-radius:7px; outline:0; }
QTreeWidget::item, QListWidget::item { padding:7px; border-radius:3px; }
QTreeWidget::item:selected, QListWidget::item:selected, QTableWidget::item:selected { background:#28505b; color:#fff; }
QTreeWidget::item:hover, QListWidget::item:hover { background:#24384a; }
QHeaderView::section { background:#263548; color:#bfd4e5; border:0; border-right:1px solid #34475d; padding:8px; font-weight:600; }
QTableCornerButton::section { background:#263548; border:0; }
QTableWidget { gridline-color:#2e3a49; }
QTabWidget::pane { border:1px solid #2e3d50; border-radius:6px; padding:8px; }
QTabBar::tab { background:#1c2836; padding:9px 16px; margin-right:3px; border-top-left-radius:5px; border-top-right-radius:5px; color:#9db0c6; }
QTabBar::tab:selected { background:#2d3c52; color:#96ecda; border-bottom:2px solid #46ccba; }
QScrollArea { border:0; background:transparent; }
QScrollBar:vertical { background:#141e29; width:11px; margin:0; }
QScrollBar::handle:vertical { background:#41556b; border-radius:5px; min-height:25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QSplitter::handle { background:#263447; width:5px; height:5px; }
QCheckBox { spacing:7px; padding:4px 0; }
QCheckBox::indicator { width:15px; height:15px; border-radius:3px; border:1px solid #61758d; background:#111923; }
QCheckBox::indicator:checked { background:#32ad9e; border:1px solid #64dec9; }
QLabel#pageTitle { font-size:21px; font-weight:600; color:#eef6fc; padding:2px 0 12px; }
QLabel#muted { color:#94a7bd; font-size:12px; }
QLabel#brand { font-size:19px; font-weight:700; color:#92e7d7; padding:6px 3px; }
QDockWidget::title { background:#253448; padding:8px; color:#c2dce7; }
QStatusBar { background:#182330; color:#93b3c5; padding:3px; }
QToolTip { background:#2b3b4c; color:#f3f7fc; border:1px solid #58748b; padding:7px; }
QMenuBar, QMenu { background:#1a2634; color:#e1e9f3; }
QMenu::item:selected { background:#2b5661; }
"""


def apply_theme(app):
    app.setFont(QFont('Microsoft YaHei UI', 10))
    app.setStyleSheet(THEME)


def scroll_page(title):
    area = QScrollArea()
    area.setWidgetResizable(True)
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(20, 17, 20, 20)
    layout.setSpacing(15)
    heading = QLabel(title)
    heading.setObjectName('pageTitle')
    layout.addWidget(heading)
    area.setWidget(page)
    return area, layout


def form_card(title, layout):
    group = QGroupBox(title)
    form = QFormLayout(group)
    form.setSpacing(11)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
    layout.addWidget(group)
    return form


def text_value(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True) if not isinstance(value, str) else value


def plain_edit(value=''):
    editor = QTextEdit()
    editor.setPlainText(str(value))
    return editor


class PatchEditor(QWidget):
    """Multiple typed patch operations, guarded by the model's semantic values."""
    def __init__(self, window, patch):
        super().__init__()
        self.window, self.project, self.catalog, self.patch = window, window.project, window.catalog, patch
        self.index = -1
        self.loading = True
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        title = QLabel('替换补丁 · 精确目标与原值保护')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        form = form_card('补丁身份', layout)
        self.id = QLineEdit(patch.get('id', ''))
        self.target = QLineEdit(patch.get('target', ''))
        self.target.setReadOnly(True)
        self.target.setToolTip('为保护原值契约，已创建补丁固定目标；更换英雄请新建补丁。')
        self.guard = QLineEdit()
        self.guard.setReadOnly(True)
        form.addRow('补丁 ID *', self.id)
        form.addRow('精确目标 *', self.target)
        form.addRow('语义摘要 / 原值保护', self.guard)
        self.update_guard()
        layout.addWidget(QLabel('只修改列表中的字段。每个字段自动附加原值保护；不匹配当前游戏配置时，导出会定位错误。'))
        toolbar = QHBoxLayout()
        for label, callback in [('添加替换字段', self.add_field), ('删除所选字段', self.remove_field), ('原始预览', self.show_original), ('刷新原值保护', self.refresh_guards)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            toolbar.addWidget(button)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['字段路径', '当前原值 / 保护', '替换为', '操作'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(170)
        layout.addWidget(self.table)
        self.value_group = QGroupBox('选中字段的编辑值')
        self.value_form = QFormLayout(self.value_group)
        self.operation = combo([('替换 replace', 'replace'), ('原值设置 set', 'set'), ('清空可选槽 clear', 'clear')])
        self.value_form.addRow('写入方式', self.operation)
        self.value = QLineEdit()
        self.value_form.addRow('新值', self.value)
        self.original = QLabel()
        self.original.setWordWrap(True)
        self.original.setTextFormat(Qt.TextFormat.PlainText)
        self.value_form.addRow('原值', self.original)
        layout.addWidget(self.value_group)
        self.scopes = FlagsEditor('替换生效场景 · 默认全开', SCOPES, patch.get('patchScopes'), window.mark_dirty)
        self.channels = FlagsEditor('目标英雄玩法开关 · 由各包及存档共同约束', CHANNELS, patch.get('integrationDefaults'), window.mark_dirty)
        layout.addWidget(self.scopes)
        layout.addWidget(self.channels)
        layout.addStretch()
        self.id.textChanged.connect(window.mark_dirty)
        self.table.currentCellChanged.connect(lambda row, *_: self.select_field(row))
        self.operation.currentIndexChanged.connect(self.operation_changed)
        self.refresh_table()
        self.loading = False

    def update_guard(self):
        guard = self.patch.get('expect', {})
        self.guard.setText(str(guard.get('path', '')) + '  ' + str(guard.get('sha256', text_value(guard.get('value')))))

    def refresh_table(self, selected=0):
        self.table.blockSignals(True)
        operations = self.patch.get('operations', [])
        self.table.setRowCount(len(operations))
        for row, op in enumerate(operations):
            values = [op['path'], text_value(op.get('expect', self.patch.get('expect'))),
                      '（清空）' if op['op'] == 'clear' else text_value(op.get('value')), op['op']]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value[:250])
                item.setToolTip(value)
                self.table.setItem(row, column, item)
        self.table.setColumnWidth(0, 220)
        self.table.setColumnWidth(1, 195)
        self.table.setColumnWidth(2, 200)
        self.table.blockSignals(False)
        self.index = -1
        self.value_group.setEnabled(bool(operations))
        if operations:
            self.table.setCurrentCell(min(selected, len(operations)-1), 0)
            self.select_field(min(selected, len(operations)-1))

    def select_field(self, index):
        if index == self.index:
            return
        if not self.loading:
            self.flush_value()
        self.index = index
        if not 0 <= index < len(self.patch.get('operations', [])):
            return
        op = self.patch['operations'][index]
        path, value = op['path'], op.get('value')
        old = self.value
        self.value_form.removeWidget(old)
        old.deleteLater()
        self.loading = True
        self.operation.setCurrentIndex(max(0, self.operation.findData(op.get('op'))))
        if path.startswith(('baseStats.', 'growth.')):
            self.value = number(value or 0)
        elif path == 'damageType':
            self.value = combo([('物理','physical'),('魔法','magic'),('真实伤害','true')],value)
        elif path in {'speed', 'attackRange', 'leadership'} or path.rsplit('.', 1)[-1] in {'warmup', 'cooldown', 'range'}:
            self.value = integer(value or (1 if path.endswith('cooldown') else 0), 1 if path.endswith('cooldown') else 0,
                                 100 if path.endswith(('warmup', 'cooldown')) else 10000)
        elif path.startswith('skills.') and path.count('.') == 1:
            self.value = self.window.reference('skill', value)
        elif path.startswith('presentation.'):
            kind = {'portrait': 'portrait', 'icon': 'icon', 'voice': 'audio', 'basicAttackEffect': 'basicAttackEffect'}[path.split('.')[1]]
            self.value = self.window.reference(kind, value)
        elif path.endswith('description'):
            self.value = plain_edit(value or '')
            self.value.setMaximumHeight(120)
        else:
            self.value = QLineEdit(str(value or ''))
        self.value_form.setWidget(1, QFormLayout.ItemRole.FieldRole, self.value)
        signal = (getattr(self.value, 'valueChanged', None) or getattr(self.value, 'currentTextChanged', None)
                  or getattr(self.value, 'textChanged', None))
        if signal:
            signal.connect(self.window.mark_dirty)
        self.original.setText(text_value(op.get('expect', '总契约保护：' + text_value(self.patch.get('expect', {}))))[:1800])
        self.operation_changed()
        self.operation.model().item(2).setEnabled(path in {'skills.normal', 'skills.captain', 'skills.passive', 'presentation.voice'})
        self.loading = False

    def operation_changed(self, *_):
        self.value.setEnabled(self.operation.currentData() != 'clear')
        if not self.loading:
            self.window.mark_dirty()

    def flush_value(self):
        if not 0 <= self.index < len(self.patch.get('operations', [])):
            return
        operation = self.operation.currentData()
        if isinstance(self.value, RefCombo):
            value = self.value.value()
        elif isinstance(self.value, QComboBox):
            value = self.value.currentData()
        elif isinstance(self.value, QTextEdit):
            value = self.value.toPlainText()
        elif hasattr(self.value, 'value'):
            value = self.value.value()
        else:
            value = self.value.text()
        current = self.patch['operations'][self.index]
        if operation == current.get('op') and (operation == 'clear' or value == current.get('value')):
            return
        previous_scopes = copy.deepcopy(self.patch.get('patchScopes'))
        had_scopes = 'patchScopes' in self.patch
        self.patch['patchScopes'] = self.scopes.value()
        try:
            self.project.set_patch_field(self.patch, current['path'], value, op=operation, catalog=self.catalog)
        except Exception:
            if had_scopes:
                self.patch['patchScopes'] = previous_scopes
            else:
                self.patch.pop('patchScopes', None)
            raise
        self.update_guard()
        for column, text in ((2, '（清空）' if operation == 'clear' else text_value(value)), (3, operation)):
            if self.table.item(self.index, column):
                self.table.item(self.index, column).setText(text[:250])

    def flush(self):
        self.flush_value()
        identity = self.id.text().strip()
        if identity != self.patch.get('id'):
            index = next(i for i, row in enumerate(self.project.data['patches']['patches']) if row is self.patch)
            self.project.rename('patches', index, identity)
        self.patch['patchScopes'] = self.scopes.value()
        self.patch['integrationDefaults'] = self.channels.value()

    def add_field(self, path=None):
        try:
            self.flush()
            from mod_schema import PATCH_PATHS
            if not isinstance(path, str):
                path, ok = QInputDialog.getItem(self, '添加补丁字段', '选择要替换的语义字段', sorted(PATCH_PATHS), editable=False)
                if not ok:
                    return
            if any(o['path'] == path or o['path'].startswith(path+'.') or path.startswith(o['path']+'.') for o in self.patch['operations']):
                raise ValueError('此字段与已有替换重叠；请编辑已有字段，或先删除整个技能槽替换再修改其子字段。')
            original = self.project.patch_original(self.patch, path, catalog=self.catalog)
            value = copy.deepcopy(original)
            aid = self.patch['target'].split('/')[-1]
            hero = self.catalog.hero(aid)
            authored = None
            if self.patch['target'].startswith('self:hero/'):
                local = self.patch['target'][len('self:hero/'):]
                authored = next((h for h in self.project.data['heroes']['heroes']
                                 if h.get('id', '')+'/'+h.get('variant', '') == local), None)
            if path.startswith('skills.') and path.count('.') == 1:
                sid = (hero or {}).get(path.split('.')[1])
                value = authored.get('skills', {}).get(path.split('.')[1]) if authored else 'builtin:skill/'+sid if sid else None
            elif path.startswith('presentation.'):
                value = (authored or hero or {}).get('presentation', {}).get(path.split('.')[1], value)
            operation = 'clear' if value is None and path in {'skills.normal', 'skills.captain', 'skills.passive', 'presentation.voice'} else 'replace'
            self.project.set_patch_field(self.patch, path, value, op=operation, catalog=self.catalog)
            self.update_guard()
            self.refresh_table(len(self.patch['operations'])-1)
            self.window.mark_dirty()
        except Exception as error:
            self.window.show_error(error)

    def remove_field(self):
        try:
            if self.index >= 0:
                self.patch['operations'].pop(self.index)
                self.loading = True
                self.refresh_table(max(0, self.index-1))
                self.value_group.setEnabled(bool(self.patch['operations']))
                self.loading = False
                self.window.mark_dirty()
        except Exception as error:
            self.window.show_error(error)

    def refresh_guards(self):
        answer = QMessageBox.question(self, '明确接受当前目标原值',
            '重新绑定当前离线目录中的原值和语义摘要？\n这表示接受目标已发生的变化，不会修改替换后的值。')
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.flush()
            self.project.refresh_patch_guards(self.patch, catalog=self.catalog)
            self.update_guard()
            self.loading = True
            self.refresh_table(max(0, self.index))
            self.loading = False
            self.window.mark_dirty()
        except Exception as error:
            self.loading = False
            self.window.show_error(error)

    def show_original(self):
        aid = self.patch['target'].split('/')[-1]
        hero = self.catalog.hero(aid)
        self.window.show_json('目标原始配置与当前补丁', {'target': self.patch['target'], 'originalHero': hero,
            'native': self.catalog.base.get('cfg', self.catalog.base).get('avatar', {}).get(aid),
            'patch': self.patch}, editable=False)


class MainWindow(QMainWindow):
    """Public methods accept paths directly for unattended core verification."""
    def __init__(self, catalog=None):
        super().__init__()
        if catalog is None:
            from .catalog import Catalog
            catalog = Catalog()
        self.catalog = catalog
        self.project = Project.new(catalog=catalog)
        self.current_path = None
        self.dirty = False
        self.current = None
        self.current_editor = None
        self.current_flush = None
        self.field_widgets = {}
        self.loading = False
        self.resize(1480, 940)
        self.setMinimumSize(1000, 680)
        self.setWindowTitle('英雄工坊 · Hero Pack Studio')
        if QApplication.instance():
            apply_theme(QApplication.instance())
        self.build_toolbar()
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(12, 9, 12, 10)
        brand_bar = QWidget()
        brand_bar.setFixedHeight(52)
        brand_row = QHBoxLayout(brand_bar)
        brand_row.setContentsMargins(0, 0, 0, 0)
        emblem = QLabel()
        emblem.setFixedSize(36, 36)
        from PySide6.QtGui import QPixmap
        emblem.setPixmap(QPixmap(str(Path(__file__).parent/'resources/app-icon.svg')).scaled(34,34,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        brand_row.addWidget(emblem)
        brand = QLabel('英雄工坊')
        brand.setObjectName('brand')
        brand_row.addWidget(brand)
        self.project_label = QLabel()
        self.project_label.setObjectName('muted')
        brand_row.addWidget(self.project_label)
        brand_row.addStretch()
        version = QLabel('离线创作工作台  /  Mod API 1')
        version.setObjectName('muted')
        brand_row.addWidget(version)
        container_layout.addWidget(brand_bar, 0)
        self.splitter = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(200)
        self.tree.setMaximumWidth(360)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.tree_context_menu)
        self.tree.currentItemChanged.connect(self.navigation_changed)
        self.splitter.addWidget(self.tree)
        self.editor_host = QWidget()
        self.editor_layout = QVBoxLayout(self.editor_host)
        self.editor_layout.setContentsMargins(0, 0, 0, 0)
        self.splitter.addWidget(self.editor_host)
        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(10, 10, 5, 10)
        title = QLabel('预览与参考')
        title.setObjectName('pageTitle')
        preview_layout.addWidget(title)
        self.preview = ResourcePreview(catalog, self.project)
        self.preview.setMinimumHeight(220)
        preview_layout.addWidget(self.preview)
        self.icon_preview = ResourcePreview(catalog, self.project)
        self.icon_preview.setMinimumHeight(100)
        preview_layout.addWidget(self.icon_preview)
        self.preview_text = QLabel('原游戏图标预览；不运行完整战斗动画。')
        self.preview_text.setWordWrap(True)
        self.preview_text.setTextFormat(Qt.TextFormat.PlainText)
        preview_layout.addWidget(self.preview_text)
        refresh = QPushButton('更新预览 / 面板')
        refresh.clicked.connect(lambda: self.run(self.refresh_preview))
        preview_layout.addWidget(refresh)
        audio = QPushButton('播放 / 停止语音预览')
        audio.clicked.connect(lambda: self.run(self.play_preview_audio))
        preview_layout.addWidget(audio)
        benchmark = QPushButton('查看英雄面板平衡性基准')
        benchmark.clicked.connect(self.show_benchmarks)
        preview_layout.addWidget(benchmark)
        coverage = QPushButton('查看引擎机制覆盖')
        coverage.clicked.connect(self.show_coverage)
        preview_layout.addWidget(coverage)
        help_text = QLabel('创作顺序\n① 填写包身份与来源\n② 设计英雄 / 精确替换字段\n③ 引用原版技能或搭建 API 1 动作\n④ 裁剪并指派图片\n⑤ 校验通过后导出 .heropack\n\n工程保留草稿；导出执行游戏实际校验。')
        help_text.setObjectName('muted')
        help_text.setWordWrap(True)
        preview_layout.addWidget(help_text)
        preview_layout.addStretch()
        preview_panel.setMinimumWidth(240)
        preview_panel.setMaximumWidth(350)
        preview_scroll = QScrollArea()
        preview_scroll.setWidgetResizable(True)
        preview_scroll.setWidget(preview_panel)
        self.splitter.addWidget(preview_scroll)
        self.splitter.setSizes([230, 900, 280])
        self.splitter.setStretchFactor(1, 1)
        container_layout.addWidget(self.splitter, 1)
        self.setCentralWidget(container)
        self.build_issues()
        self.refresh_tree(('manifest', None))
        self.statusBar().showMessage('已新建可保存的 new 工程；先填写包名称和作者。')

    def build_toolbar(self):
        toolbar = QToolBar('创作操作', self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        actions = [
            ('新建 new', lambda: self.new_project('new'), QKeySequence.StandardKey.New),
            ('新建 replace', lambda: self.new_project('replace'), None),
            ('打开工程', self.choose_open, QKeySequence.StandardKey.Open),
            ('导入英雄包', self.choose_import, None), ('保存工程', self.choose_save, QKeySequence.StandardKey.Save),
            ('校验', self.validate_project, None), ('导出英雄包', self.choose_export, None),
            ('多包合并', self.choose_merge, None),
        ]
        for label, callback, shortcut in actions:
            action = QAction(label, self)
            if shortcut:
                action.setShortcut(shortcut)
            action.triggered.connect(lambda checked=False, fn=callback: self.run(fn))
            toolbar.addAction(action)
            if label == '导出英雄包':
                toolbar.widgetForAction(action).setProperty('primary', True)
        toolbar.addSeparator()
        add = QPushButton('＋ 新增英雄')
        add.clicked.connect(lambda: self.run(self.add_hero))
        toolbar.addWidget(add)
        add = QPushButton('＋ 替换补丁')
        add.clicked.connect(self.choose_patch)
        toolbar.addWidget(add)
        add = QPushButton('＋ 技能')
        menu=QMenu(add)
        menu.addAction('从任意原版技能模板创建',lambda:self.run(self.choose_skill_template))
        menu.addAction('创建旧版空白动作技能',lambda:self.run(self.add_skill))
        add.setMenu(menu)
        toolbar.addWidget(add)

    def build_issues(self):
        self.issue_dock = QDockWidget('校验结果 · 双击定位字段', self)
        self.issue_tree = QTreeWidget()
        self.issue_tree.setHeaderLabels(['级别', '位置', '问题 / 修改提示'])
        self.issue_tree.setColumnWidth(0, 70)
        self.issue_tree.setColumnWidth(1, 260)
        self.issue_tree.itemDoubleClicked.connect(self.locate_issue)
        self.issue_dock.setWidget(self.issue_tree)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.issue_dock)
        self.issue_dock.hide()

    def run(self, callback, *args, **kwargs):
        try:
            return callback(*args, **kwargs)
        except Exception as error:
            self.show_error(error)
            return None

    def show_error(self, error):
        path = getattr(error, 'path', '')
        message = str(error)
        if path:
            message = f'位置：{path}\n\n{message}'
        self.statusBar().showMessage(message.replace('\n', ' ')[:250], 12000)
        QMessageBox.warning(self, '操作未完成', message)

    def mark_dirty(self, *_):
        if not self.loading:
            self.dirty = True
            self.setWindowTitle('● ' + self.project.manifest.get('name', '未命名工程') + ' · 英雄工坊')

    def flush(self):
        for spin in self.findChildren(QAbstractSpinBox):
            spin.interpretText()
        if self.current_editor and hasattr(self.current_editor, 'flush'):
            self.current_editor.flush()
        elif self.current_flush:
            self.current_flush()

    def may_discard(self):
        if not self.dirty:
            return True
        answer = QMessageBox.question(self, '当前工程尚未保存', '保存当前工程后继续？',
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return bool(self.choose_save())
        return True

    def set_project(self, project, path=None):
        if not isinstance(project.manifest, dict) or not isinstance(project.data, dict) or not isinstance(project.assets, dict):
            raise ValueError('工程内容结构错误；当前工程未替换。')
        for kind in ('heroes', 'skills', 'patches'):
            doc = project.data.get(kind)
            if not isinstance(doc, dict) or not isinstance(doc.get(kind), list) or not all(isinstance(row, dict) for row in doc[kind]):
                raise ValueError(f'工程 {kind} 结构错误；当前工程未替换。')
        if any(not isinstance(key, str) or not isinstance(value, bytes) for key,value in project.assets.items()):
            raise ValueError('工程素材结构错误；当前工程未替换。')
        self.project = project
        self.current_path = Path(path) if path else None
        self.current = self.current_editor = self.current_flush = None
        self.dirty = False
        self.preview.project = self.icon_preview.project = project
        self.issue_tree.clear()
        self.issue_dock.hide()
        if 'offlineDependencyPaths' in project.metadata:
            self.catalog.package_paths = [Path(path) for path in project.metadata['offlineDependencyPaths']]
        self.refresh_tree(('manifest', None))
        self.setWindowTitle(project.manifest.get('name', '未命名工程') + ' · 英雄工坊')
        missing = [str(path) for path in getattr(self.catalog, 'package_paths', []) if not Path(path).is_file()]
        if missing:
            for path in missing:
                self.issue_tree.addTopLevelItem(QTreeWidgetItem(['缺少依赖', path, '工程记录的离线依赖文件不存在；请在包属性的“离线依赖包”中重新选择。']))
            self.issue_dock.show()
            self.statusBar().showMessage('缺少离线依赖文件，请在包属性中重新定位：' + '；'.join(missing), 20000)

    def new_project(self, kind='new', force=False):
        if not force and not self.may_discard():
            return None
        project = Project.new(kind=kind, catalog=self.catalog)
        self.set_project(project)
        return project

    def open_project(self, path, force=False):
        if not force and not self.may_discard():
            return None
        project = Project.load(path, catalog=self.catalog)
        self.set_project(project, path if Path(path).suffix.lower() != '.heropack' else None)
        return project

    def import_package(self, path, force=False):
        if not force and not self.may_discard():
            return None
        project = Project.import_package(path, catalog=self.catalog)
        self.set_project(project)
        self.statusBar().showMessage('已导入英雄包为可编辑工程；保存工程使用独立文件。')
        return project

    def save_project(self, path=None):
        self.flush()
        path = path or self.current_path
        if not path:
            raise ValueError('请先选择工程保存位置。')
        self.project.metadata['offlineDependencyPaths'] = [str(Path(p).absolute()) for p in getattr(self.catalog, 'package_paths', [])]
        saved = self.project.save(path)
        self.current_path = Path(saved)
        self.dirty = False
        self.setWindowTitle(self.project.manifest.get('name', '未命名') + ' · 英雄工坊')
        self.statusBar().showMessage('工程已保存：' + str(saved), 10000)
        return saved

    def validate_project(self):
        self.flush()
        issues = self.project.validate(catalog=self.catalog)
        self.issue_tree.clear()
        for issue in issues:
            item = QTreeWidgetItem(['错误' if issue.get('severity') == 'error' else '提示', str(issue.get('path', '')), str(issue.get('message', ''))])
            item.setData(0, Qt.ItemDataRole.UserRole, issue)
            self.issue_tree.addTopLevelItem(item)
        if not issues:
            self.issue_tree.addTopLevelItem(QTreeWidgetItem(['通过', '', '已使用游戏实际包校验与编译规则检查，可导出。']))
        self.issue_dock.show()
        self.statusBar().showMessage('校验完成：' + str(sum(i.get('severity') == 'error' for i in issues)) + ' 个错误。', 10000)
        return issues

    def export_package(self, path):
        issues = self.validate_project()
        if any(issue.get('severity') == 'error' for issue in issues):
            raise ValueError('英雄包尚未通过校验。请双击下方错误定位并修正，再导出。')
        result = self.project.export(path, catalog=self.catalog)
        self.statusBar().showMessage('已导出可导入游戏的英雄包：' + str(path), 15000)
        return result

    def merge_projects(self, paths, name='合并英雄包', author='', force=False, show_report=False):
        if not force and not self.may_discard():
            return None
        from .merge import merge_packages
        project, report = merge_packages(paths, catalog=self.catalog, name=name, author=author)
        self.set_project(project)
        self.mark_dirty()
        if show_report:
            self.show_json('合并报告 · 引用重写与冲突', report, editable=False)
        return project, report

    def choose_open(self):
        path, _ = QFileDialog.getOpenFileName(self, '打开英雄工程', '', '英雄工程 (*.lalhero *.heroproj *.heropack);;所有文件 (*)')
        return self.open_project(path) if path else None

    def choose_import(self):
        path, _ = QFileDialog.getOpenFileName(self, '导入游戏英雄包', '', '游戏英雄包 (*.heropack)')
        return self.import_package(path) if path else None

    def choose_save(self):
        if self.current_path:
            return self.save_project()
        path, _ = QFileDialog.getSaveFileName(self, '保存可继续编辑的工程', self.project.manifest.get('name', '英雄工程')+'.lalhero', '英雄工程 (*.lalhero)')
        return self.save_project(path if Path(path).suffix else path+'.lalhero') if path else None

    def choose_export(self):
        path, _ = QFileDialog.getSaveFileName(self, '导出标准英雄包', self.project.manifest.get('name', '英雄包')+'.heropack', '游戏英雄包 (*.heropack)')
        return self.export_package(path if Path(path).suffix else path+'.heropack') if path else None

    def choose_merge(self):
        paths, _ = QFileDialog.getOpenFileNames(self, '选择多个需要合并的包', '', '游戏英雄包 (*.heropack)')
        if paths:
            return self.merge_projects(paths, show_report=True)

    def refresh_tree(self, selected=None):
        selected = selected or self.current or ('manifest', None)
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            target = None
            package = QTreeWidgetItem(['包属性与依赖'])
            package.setData(0, Qt.ItemDataRole.UserRole, ('manifest', None))
            self.tree.addTopLevelItem(package)
            if selected[0] == 'manifest':
                target = package
            for kind, label in [('heroes', '新增英雄 new'), ('patches', '替换补丁 replace'), ('skills', '技能定义')]:
                group = QTreeWidgetItem([label])
                group.setExpanded(True)
                self.tree.addTopLevelItem(group)
                for index, row in enumerate(self.project.data.get(kind, {}).get(kind, [])):
                    name = row.get('name') or row.get('id', '未命名')
                    if kind == 'patches':
                        name += ' → ' + str(row.get('target', '')).split('/')[-1]
                    child = QTreeWidgetItem([name])
                    child.setToolTip(0, str(row.get('id')) + (' / '+str(row.get('variant')) if kind == 'heroes' else ''))
                    child.setData(0, Qt.ItemDataRole.UserRole, (kind, index))
                    group.addChild(child)
                    if selected == (kind, index):
                        target = child
                group.setExpanded(True)
            media = QTreeWidgetItem([f'素材库  ({len(self.project.assets)})'])
            media.setData(0, Qt.ItemDataRole.UserRole, ('assets', None))
            self.tree.addTopLevelItem(media)
            if selected[0] == 'assets':
                target = media
        finally:
            self.tree.blockSignals(False)
        self.tree.setCurrentItem(target or package)
        self.project_label.setText(('NEW' if self.project.manifest.get('kind') == 'new' else 'REPLACE → PATCH') + '  /  ' + self.project.manifest.get('name', ''))

    def navigation_changed(self, item, previous):
        selection = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not selection:
            return
        try:
            self.flush()
            self.show_entity(*selection)
        except Exception as error:
            self.tree.blockSignals(True)
            self.tree.setCurrentItem(previous)
            self.tree.blockSignals(False)
            self.show_error(error)

    def select_entity(self, kind, index=None):
        self.flush()
        self.current_editor = self.current_flush = None
        self.refresh_tree((kind, index))

    def show_entity(self, kind, index=None):
        self.loading = True
        self.current = (kind, index)
        self.current_editor = self.current_flush = None
        self.field_widgets = {}
        while self.editor_layout.count():
            item = self.editor_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        if kind == 'manifest':
            editor = self.package_page()
        elif kind == 'heroes':
            editor = self.hero_page(self.project.data['heroes']['heroes'][index])
        elif kind == 'skills':
            self.current_editor = SkillEditor(self.catalog, self.project)
            self.current_editor.bind(self.project.data['skills']['skills'][index])
            self.current_editor.changed.connect(self.mark_dirty)
            self.current_editor.error.connect(self.show_error)
            editor = QScrollArea()
            editor.setWidgetResizable(True)
            editor.setWidget(self.current_editor)
        elif kind == 'patches':
            editor = QScrollArea()
            editor.setWidgetResizable(True)
            self.current_editor = PatchEditor(self, self.project.data['patches']['patches'][index])
            editor.setWidget(self.current_editor)
        else:
            editor = self.assets_page()
        self.editor_layout.addWidget(editor)
        self.loading = False
        self.refresh_preview(flush=False)

    def reference(self, kind, value=None, optional=True):
        rows = list(self.catalog.references(kind))
        if kind == 'skill':
            rows = [(f'{r.get("name", r["id"])} · {r["id"]}' + ('' if r.get('reusable') else ' [先导入为模板]'), r.get('reference', 'builtin:skill/'+r['id'])) for r in self.catalog.skills]
            rows += [(r.get('name', r['id'])+' [本包]', 'self:skill/'+r['id']) for r in self.project.data['skills']['skills'] if isinstance(r.get('id'),str) and r.get('id')]
        elif kind == 'hero':
            rows += [(r.get('name', r['id'])+' [本包] '+r['variant'], 'self:hero/'+r['id']+'/'+r['variant']) for r in self.project.data['heroes']['heroes'] if isinstance(r.get('id'),str) and r.get('id') and isinstance(r.get('variant'),str) and r.get('variant')]
        if kind in {'portrait', 'icon', 'audio'}:
            extensions = {'.mp3'} if kind == 'audio' else {'.png', '.jpg', '.jpeg'}
            rows += [(path+' [本包素材]', 'self:asset/'+path) for path in sorted(self.project.assets) if Path(path).suffix.lower() in extensions]
        box = RefCombo(rows, optional=optional)
        if kind == 'skill':
            unsafe = {r.get('reference', 'builtin:skill/'+r['id']) for r in self.catalog.skills if not r.get('reusable')}
            for i in range(box.count()):
                if box.itemData(i) in unsafe:
                    box.model().item(i).setEnabled(False)
        box.set_value(value)
        return box

    def connect_change(self, field):
        signal = (getattr(field, 'valueChanged', None) or getattr(field, 'currentTextChanged', None) or
                  getattr(field, 'textChanged', None) or getattr(field, 'toggled', None))
        if signal:
            signal.connect(self.mark_dirty)

    def package_page(self):
        area, layout = scroll_page('包属性与发布身份')
        manifest = self.project.manifest
        form = form_card('永久身份 · 发布版本', layout)
        fields = {}
        for key, label in [('packageId', '注册 UUID *（发布后请勿变更）'), ('name', '包名称 *'),
                           ('author', '作者 *'), ('version', '版本 *（例如 1.0.0）')]:
            field = QLineEdit(str(manifest.get(key, '')))
            if key == 'author':
                field.setPlaceholderText('必填：作者名称')
            fields[key] = field
            form.addRow(label, field)
            self.connect_change(field)
            self.field_widgets[key] = field
        self.field_widgets['manifest'] = form.parentWidget()
        kind = QLabel('new · 可拥有的新英雄' if manifest.get('kind') == 'new' else 'replace → patch · 依托现有英雄的补丁')
        form.addRow('导出格式', kind)
        description = plain_edit(manifest.get('description', ''))
        description.setMaximumHeight(95)
        self.connect_change(description)
        form.addRow('说明（选填）', description)
        preview = RefCombo([(p,p) for p in sorted(self.project.assets) if Path(p).suffix.lower() in {'.png','.jpg','.jpeg'}])
        preview.set_value(manifest.get('preview'))
        self.connect_change(preview)
        form.addRow('包预览资源（选填）', preview)
        notes = form_card('创作来源说明', layout)
        source = manifest.get('sourceNotes', {})
        source_options = [('自制设计', 'author-design'), ('回忆还原', 'recollection'), ('资料还原', 'restoration'), ('其他', 'other')]
        original_kind = source.get('kind') if isinstance(source, dict) else None
        if original_kind is not None and original_kind not in [value for _, value in source_options]:
            source_options.append(('原来源：' + str(original_kind), original_kind))
        source_kind = combo(source_options, original_kind)
        source_description = plain_edit(source.get('description', '') if isinstance(source, dict) else str(source or ''))
        source_edits = {'kind': False, 'description': False}
        source_kind.currentIndexChanged.connect(lambda: source_edits.update(kind=True))
        source_description.textChanged.connect(lambda: source_edits.update(description=True))
        source_description.setMaximumHeight(90)
        notes.addRow('来源性质', source_kind)
        notes.addRow('证据与不确定之处', source_description)
        self.connect_change(source_kind)
        self.connect_change(source_description)
        dependency_group = QGroupBox('明确依赖 · 不会自动安装其他包')
        dependency_layout = QVBoxLayout(dependency_group)
        dependencies = QTableWidget(0, 3)
        dependencies.setHorizontalHeaderLabels(['依赖包 UUID', '版本要求', '精确摘要 digest（选填）'])
        dependencies.horizontalHeader().setStretchLastSection(True)
        dependencies.setMinimumHeight(140)
        def add_dependency(value=None):
            value = value if isinstance(value, dict) else {}
            i = dependencies.rowCount()
            dependencies.insertRow(i)
            for column, key in enumerate(('packageId', 'version', 'digest')):
                dependencies.setItem(i, column, QTableWidgetItem(value.get(key, '')))
            self.mark_dirty()
        for dependency in manifest.get('dependencies', []):
            add_dependency(dependency)
        buttons = QHBoxLayout()
        button = QPushButton('添加依赖')
        button.clicked.connect(lambda: add_dependency())
        buttons.addWidget(button)
        button = QPushButton('删除所选依赖')
        button.clicked.connect(lambda: (dependencies.removeRow(dependencies.currentRow()), self.mark_dirty()) if dependencies.currentRow() >= 0 else None)
        buttons.addWidget(button)
        buttons.addStretch()
        dependency_layout.addLayout(buttons)
        dependency_layout.addWidget(dependencies)
        library = QPushButton('管理离线依赖包…（选择 .heropack 文件）')
        library.clicked.connect(lambda: self.run(self.show_dependency_manager))
        dependency_layout.addWidget(library)
        offline = QLabel(f'显式离线库：{len(getattr(self.catalog, "package_paths", []))} 个文件。只读取你选择的文件，不扫描游戏 Mod 目录。')
        offline.setWordWrap(True)
        dependency_layout.addWidget(offline)
        dependencies.itemChanged.connect(self.mark_dirty)
        layout.addWidget(dependency_group)
        flags = FlagsEditor('包级玩法默认值 · 每个存档仍可取消', CHANNELS, manifest.get('integrationDefaults'), self.mark_dirty)
        layout.addWidget(flags)
        label = QLabel('必填项用 * 标记。永久 UUID 用于存档身份；版本必须是三段整数。\n能力、入口、文件清单与 SHA-256 摘要在导出时由模型整理和校验。手动填写未开放机制不会获得支持。')
        label.setWordWrap(True)
        label.setObjectName('muted')
        layout.addWidget(label)
        advanced = QPushButton('高级：查看包清单')
        advanced.clicked.connect(lambda: self.run(lambda: (self.flush(), self.show_json('包清单（高级）', manifest))))
        layout.addWidget(advanced)
        layout.addStretch()
        def flush():
            for key, field in fields.items():
                manifest[key] = field.text().strip()
            manifest['description'] = description.toPlainText()
            if preview.value():
                manifest['preview'] = preview.value()
            else:
                manifest.pop('preview', None)
            if any(source_edits.values()):
                old_notes = manifest.get('sourceNotes')
                notes_value = copy.deepcopy(old_notes) if isinstance(old_notes, dict) else {'description': source_description.toPlainText()}
                if source_edits['kind']:
                    notes_value['kind'] = source_kind.currentData()
                if source_edits['description']:
                    notes_value['description'] = source_description.toPlainText()
                manifest['sourceNotes'] = notes_value
            manifest['dependencies'] = []
            for i in range(dependencies.rowCount()):
                dependency = {key: (dependencies.item(i, j).text().strip() if dependencies.item(i, j) else '') for j,key in enumerate(('packageId', 'version', 'digest'))}
                if not dependency['digest']:
                    dependency.pop('digest')
                manifest['dependencies'].append(dependency)
            manifest['integrationDefaults'] = flags.value()
        self.current_flush = flush
        return area

    def hero_page(self, hero):
        area, layout = scroll_page('新增英雄 · 身份、数值与资源')
        form = form_card('身份与定位', layout)
        fields = {'id': QLineEdit(hero.get('id', '')), 'variant': QLineEdit(hero.get('variant', '')),
                  'name': QLineEdit(hero.get('name', '')),
                  'quality': combo([(v, k) for k,v in QUALITY.items()], hero.get('quality', 5)),
                  'signType': combo([('输出', 'attack'), ('坦克', 'tank'), ('辅助', 'assist')], hero.get('signType')),
                  'actionType': combo([('突进 forward', 'forward'), ('迂回 sly', 'sly'), ('站桩 stand', 'stand'), ('诡诈 cunning', 'cunning')], hero.get('actionType')),
                  'damageType': combo([('物理', 'physical'), ('魔法', 'magic'), ('真实伤害', 'true')], hero.get('damageType')),
                  'role': QLineEdit(hero.get('role', ''))}
        names = {'id': '英雄本地 ID *', 'variant': '变体 ID *（品质变体独立）', 'name': '英雄名称 *',
                 'quality': '品质 *', 'signType': '战斗职责 *', 'actionType': '行动类型 *', 'damageType': '普攻伤害类型 *', 'role': '角色定位说明（选填）'}
        fields['damageType'].setToolTip('真实伤害使用原生类型 3：不扣除物防／魔防，沿用原版真实伤害倍率（当前 0.3）及命中、暴击、护盾等后续规则。')
        for quality,color in {6:'#efa64c',5:'#b07be8',4:'#5b9de8',3:'#56b87b',2:'#c8ced7'}.items():
            fields['quality'].setItemData(fields['quality'].findData(quality),QColor(color),Qt.ItemDataRole.ForegroundRole)
        for key, field in fields.items():
            form.addRow(names[key], field)
            self.connect_change(field)
            self.field_widgets[key] = field
        description = plain_edit(hero.get('description', ''))
        description.setMaximumHeight(95)
        self.connect_change(description)
        form.addRow('英雄说明（选填）', description)
        stats_group = QGroupBox('战斗数值 · 基础 + 成长 × (等级 − 1)')
        stats_layout = QGridLayout(stats_group)
        stats_layout.addWidget(QLabel('面板字段'), 0, 0)
        stats_layout.addWidget(QLabel('1 级基础 *'), 0, 1)
        stats_layout.addWidget(QLabel('每级成长 *'), 0, 2)
        stats = {}
        for i, (key,label) in enumerate(STATS.items(), 1):
            stats_layout.addWidget(QLabel(label), i, 0)
            for j, group in enumerate(('baseStats', 'growth'), 1):
                field = number(hero.get(group, {}).get(key, 0), 1 if group == 'baseStats' and key == 'health' else 0)
                stats[(group, key)] = field
                stats_layout.addWidget(field, i, j)
                self.connect_change(field)
                self.field_widgets[group+'.'+key] = field
        button = QPushButton('查看同品质 / 定位真实英雄基准')
        button.clicked.connect(lambda: BenchmarkDialog(self.catalog, fields['quality'].currentData(), fields['role'].text(), self).exec())
        stats_layout.addWidget(button, 5, 0, 1, 3)
        autofill = QPushButton('按定位自动填充基准值')
        autofill.setObjectName('autofillStats')
        autofill.setToolTip('替换基础属性、每级成长、速度、射程与领导力。按当前品质和战斗职责取原版中位数；定位说明匹配时进一步筛选。填入后仍可手动修改。')
        stats_layout.addWidget(autofill, 6, 0, 1, 3)
        baseline_note = QLabel('自动填充会覆盖上述数值及速度、射程、领导力；不会修改技能和等级上限。')
        baseline_note.setWordWrap(True)
        baseline_note.setObjectName('muted')
        stats_layout.addWidget(baseline_note, 7, 0, 1, 3)
        layout.addWidget(stats_group)
        limits = form_card('范围与养成', layout)
        for key,label,maximum,minimum in [('speed','速度 *',10000,0), ('attackRange','普攻射程 *',10000,0),
                                         ('leadership','领导力 *',10000,0), ('levelCap','等级上限 *',99,1)]:
            fields[key] = integer(hero.get(key, minimum), minimum, maximum)
            limits.addRow(label, fields[key])
            self.connect_change(fields[key])
            self.field_widgets[key] = fields[key]
        def fill_baseline():
            baseline = self.catalog.stat_baseline(fields['quality'].currentData(),
                                                  fields['signType'].currentData(), fields['role'].text())
            for (group, key), field in stats.items():
                field.setValue(baseline[group][key])
            for key in ('speed', 'attackRange', 'leadership'):
                fields[key].setValue(baseline[key])
            note = f'已填入：{baseline["basis"]}，{baseline["count"]} 位原版英雄的属性中位数。'
            if fields['role'].text().strip() and not baseline['roleMatched']:
                note += ' 定位说明未匹配到同职责分类，使用战斗职责基准。'
            baseline_note.setText(note)
            self.mark_dirty()
            self.refresh_preview()
            self.statusBar().showMessage(note, 12000)
        autofill.clicked.connect(lambda: self.run(fill_baseline))
        star_up = self.reference('hero', hero.get('progression', {}).get('starUp'))
        limits.addRow('进阶目标（选填，可跨包）', star_up)
        self.connect_change(star_up)
        progression = QLabel('标准玩家英雄养成')
        progression.setToolTip('builtin:progression/default-player-hero · 当前游戏开放的标准模型')
        limits.addRow('养成预设 *', progression)
        skills = form_card('技能槽 · 可复用原版完整技能或本包技能', layout)
        skill_fields = {}
        for key, label in [('normal', '普通技能'), ('captain', '队长技能'), ('passive', '被动技能')]:
            box = self.reference('skill', hero.get('skills', {}).get(key))
            skill_fields[key] = box
            row = QHBoxLayout()
            row.addWidget(box)
            button = QPushButton('创建并绑定')
            menu=QMenu(button)
            menu.addAction('从原版模板创建并绑定',lambda checked=False,slot=key:self.run(self.choose_skill_template,hero,slot))
            menu.addAction('创建空白技能并绑定',lambda checked=False,slot=key:self.run(self.add_skill,hero,slot))
            button.setMenu(menu)
            row.addWidget(button)
            skills.addRow(label, row)
            self.connect_change(box)
            self.field_widgets['skills.'+key] = box
        presentation = form_card('表现资源 · 两张必需图片与普攻特效', layout)
        resources = {}
        for key,label,kind in [('portrait','详情页立绘 *','portrait'), ('icon','列表 / 战斗卡面 *','icon'),
                               ('basicAttackEffect','普攻特效 *','basicAttackEffect'), ('voice','语音（选填）','audio')]:
            field = self.reference(kind, hero.get('presentation', {}).get(key), optional=key == 'voice')
            resources[key] = field
            presentation.addRow(label, field)
            self.connect_change(field)
            self.field_widgets['presentation.'+key] = field
        for slot, label in [('portrait','导入详情页立绘（独立无框）'),('icon','制作列表 / 战斗卡面')]:
            image_button = QPushButton(label)
            image_button.clicked.connect(lambda checked=False, target=slot: self.run(self.choose_image, target, hero))
            presentation.addRow(image_button)
        button = QPushButton('打开素材库 · 导入 / 裁剪 / 指派')
        button.clicked.connect(lambda: self.select_entity('assets'))
        presentation.addRow(button)
        flags = FlagsEditor('此英雄的玩法默认值', CHANNELS, hero.get('integrationDefaults'), self.mark_dirty)
        layout.addWidget(flags)
        closed = QLabel('尚未开放：自定义获取价格 / 权重、自制缘分关系、自定义养成迁移。现有 acquisition / destiny 原始占位字段会保留；玩法入口使用上方默认开关。')
        closed.setWordWrap(True)
        closed.setObjectName('muted')
        layout.addWidget(closed)
        actions = QHBoxLayout()
        delete = QPushButton('删除本英雄')
        delete.clicked.connect(self.delete_current)
        actions.addWidget(delete)
        advanced = QPushButton('高级 JSON（选用）')
        advanced.clicked.connect(lambda: self.run(lambda: (self.flush(), self.show_json('英雄条目（高级）', hero))))
        actions.addWidget(advanced)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addStretch()
        def flush():
            old_identity, old_variant = hero.get('id'), hero.get('variant')
            new_identity, new_variant = fields['id'].text().strip(), fields['variant'].text().strip()
            if (new_identity, new_variant) != (old_identity, old_variant):
                index = next(i for i,row in enumerate(self.project.data['heroes']['heroes']) if row is hero)
                self.project.rename('heroes', index, new_identity, new_variant=new_variant)
                reference = star_up.value()
                if isinstance(reference, str) and reference.startswith('self:hero/'+old_identity+'/'):
                    suffix = reference[len('self:hero/'+old_identity+'/'):]
                    star_up.set_value('self:hero/'+new_identity+'/'+(new_variant if suffix == old_variant else suffix))
            for key, field in fields.items():
                hero[key] = field.currentData() if isinstance(field, QComboBox) else field.value() if hasattr(field,'value') else field.text().strip()
            hero['unitType'] = 'hero'
            hero['description'] = description.toPlainText()
            for (group,key), field in stats.items():
                hero.setdefault(group, {})[key] = field.value()
            hero['progression'] = {'preset': 'builtin:progression/default-player-hero', 'starUp': star_up.value()}
            hero['skills'] = {key: field.value() for key,field in skill_fields.items()}
            hero['presentation'] = {key: field.value() for key,field in resources.items()}
            hero['integrationDefaults'] = flags.value()
        self.current_flush = flush
        return area

    def assets_page(self):
        area, layout = scroll_page('素材库 · 裁剪、品质卡面与指派')
        hint = QLabel('源图、手工蒙版与合成配方保存在工程中（源/蒙版单文件 ≤32 MiB）；只有生成的 RGBA PNG 进入英雄包。原版框可独立另存。')
        hint.setWordWrap(True)
        hint.setObjectName('muted')
        layout.addWidget(hint)
        toolbar = QHBoxLayout()
        for label,callback in [('制作卡面 / 裁剪', self.choose_image), ('导入详情页立绘', lambda: self.choose_image('portrait')), ('导入 MP3 语音', self.choose_audio),
                               ('重新编辑所选图片', self.edit_asset), ('删除素材', self.delete_asset)]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, fn=callback: self.run(fn))
            toolbar.addWidget(button)
        layout.addLayout(toolbar)
        self.asset_table = QTableWidget(0, 4)
        self.asset_table.setHorizontalHeaderLabels(['包内路径', '类型', '尺寸 / 说明', '字节数'])
        self.asset_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.asset_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.asset_table.horizontalHeader().setStretchLastSection(True)
        self.asset_table.setMinimumHeight(260)
        layout.addWidget(self.asset_table)
        self.asset_paths = sorted(self.project.assets)
        self.asset_table.setRowCount(len(self.asset_paths))
        for row,path in enumerate(self.asset_paths):
            raw = self.project.assets[path]
            kind, detail = '音频' if Path(path).suffix.lower() == '.mp3' else '资源', ''
            if Path(path).suffix.lower() in {'.png', '.jpg', '.jpeg'}:
                from .media import inspect_image
                try:
                    info = inspect_image(raw)
                    kind, detail = '图片', f'{info["width"]} × {info["height"]}'
                except Exception as error:
                    detail = str(error)
            for column,value in enumerate([path, kind, detail, f'{len(raw):,}']):
                self.asset_table.setItem(row,column,QTableWidgetItem(value))
        self.asset_table.setColumnWidth(0,280)
        self.asset_table.currentCellChanged.connect(lambda row,*_: self.preview_asset(row))
        assign = form_card('将所选素材指派给本工程英雄', layout)
        self.asset_hero = combo([(str(h.get('name',h.get('id','未命名')))+' / '+str(h.get('variant','')), i) for i,h in enumerate(self.project.data['heroes']['heroes'])])
        self.asset_slot = combo([('详情页立绘 portrait（无框）','portrait'),('列表 / 战斗卡面 icon','icon'),('语音 voice','voice')])
        assign.addRow('英雄',self.asset_hero)
        assign.addRow('槽位',self.asset_slot)
        button = QPushButton('指派所选素材')
        button.setProperty('primary',True)
        button.clicked.connect(lambda: self.run(self.assign_selected_asset))
        assign.addRow(button)
        layout.addWidget(QLabel('自制动画/SWF 不作为外部可执行资源导入。特效在技能与普攻下拉框中复用游戏定义。'))
        layout.addStretch()
        self.current_flush = None
        if self.asset_paths:
            self.asset_table.setCurrentCell(0,0)
        return area

    def add_hero(self, source_aid=None):
        self.flush()
        row = self.project.add_hero(catalog=self.catalog, source_aid=source_aid)
        self.current_editor = self.current_flush = None
        self.mark_dirty()
        self.refresh_tree(('heroes',len(self.project.data['heroes']['heroes'])-1))
        return row

    def choose_skill_template(self,hero=None,slot=None):
        self.flush()
        dialog=QDialog(self);dialog.setWindowTitle('从全部原版技能导入模板');dialog.resize(860,470)
        layout=QVBoxLayout(dialog);layout.addWidget(QLabel('所有原版技能都可导入，包含召唤、分身、被动和角色复合机制。输入名称或 ID 搜索。'))
        picker=RefCombo(self.catalog.references('skillTemplate'),optional=False);layout.addWidget(picker)
        details=QLabel();details.setWordWrap(True);layout.addWidget(details)
        def preview():
            row=self.catalog.skill(str(picker.value()).split('/')[-1])
            details.setText((row['description']+'\n\n'+row['reason']) if row else '请选择当前游戏目录中的技能。')
        picker.currentTextChanged.connect(preview);preview();layout.addStretch()
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        source=self.catalog.skill(str(picker.value()).split('/')[-1])
        if source is None:raise ValueError('请选择有效的原版技能模板')
        row=self.project.add_skill();identity=row['id'];row.clear();row.update(copy.deepcopy(source['authored']));row['id']=identity
        if isinstance(hero,dict) and slot:hero.setdefault('skills',{})[slot]='self:skill/'+identity
        self.current_editor=self.current_flush=None;self.mark_dirty()
        self.refresh_tree(('skills',len(self.project.rows('skills'))-1))
        return row

    def add_skill(self, hero=None, slot=None):
        self.flush()
        row = self.project.add_skill()
        if isinstance(hero,dict) and slot:
            hero.setdefault('skills',{})[slot] = 'self:skill/'+row['id']
        self.current_editor = self.current_flush = None
        self.mark_dirty()
        self.refresh_tree(('skills',len(self.project.data['skills']['skills'])-1))
        return row

    def add_patch(self, target):
        self.flush()
        row = self.project.add_patch(target,catalog=self.catalog)
        self.current_editor = self.current_flush = None
        self.mark_dirty()
        self.refresh_tree(('patches',len(self.project.data['patches']['patches'])-1))
        return row

    def add_slot_patch(self, target, slot, replacement, op='replace'):
        self.flush()
        row = self.project.add_slot_patch(target, slot, replacement, op=op, catalog=self.catalog)
        self.current_editor = self.current_flush = None
        self.mark_dirty()
        self.refresh_tree(('patches', len(self.project.data['patches']['patches'])-1))
        return row

    def choose_patch(self):
        try:
            self.flush()
        except Exception as error:
            self.show_error(error)
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('选择替换目标英雄')
        dialog.resize(700,270)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('选择精确的品质英雄。创建后将自动绑定目标原值与语义摘要。'))
        targets = self.reference('hero',optional=False)
        targets.setObjectName('patchTarget')
        layout.addWidget(targets)
        mode = combo([('通用字段（从名称开始，可继续增加其他字段）', None),
                      ('仅普通技能槽', 'normal'), ('仅队长技能槽', 'captain'), ('仅被动技能槽', 'passive')])
        mode.setObjectName('patchInitialMode')
        form = QFormLayout()
        form.addRow('初始修改', mode)
        layout.addLayout(form)
        hint = QLabel('私有技能槽需要独立保护时，选择“仅…技能槽”分别创建补丁。初始值沿用目标当前技能；空槽使用明确清空操作。')
        hint.setWordWrap(True)
        hint.setObjectName('muted')
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            def create():
                target, slot = targets.value(), mode.currentData()
                if slot is None:
                    return self.add_patch(target)
                if isinstance(target, str) and target.startswith('self:hero/'):
                    local = target[len('self:hero/'):]
                    source = next((hero for hero in self.project.data['heroes']['heroes']
                                   if hero.get('id', '')+'/'+hero.get('variant', '') == local), None)
                    if source is None:
                        raise ValueError('找不到本工程目标英雄，请重新选择。')
                    replacement = source.get('skills', {}).get(slot)
                elif isinstance(target, str) and target.startswith(('builtin:hero/', 'builtin:avatar/')):
                    source = self.catalog.hero(target.split('/')[-1])
                    if source is None:
                        raise ValueError('找不到内置目标英雄，请重新选择。')
                    sid = source.get(slot)
                    replacement = 'builtin:skill/'+sid if sid else None
                else:
                    raise ValueError('单槽初始模板请选择内置英雄或本工程英雄。')
                return self.add_slot_patch(target, slot, replacement, op='clear' if replacement is None else 'replace')
            self.run(create)

    def delete_current(self):
        if not self.current or self.current[0] not in {'heroes','skills','patches'}:
            return
        if QMessageBox.question(self,'删除条目','删除此条目？引用此条目的其他内容会在校验时定位为缺失。') != QMessageBox.StandardButton.Yes:
            return
        kind,index = self.current
        self.project.data[kind][kind].pop(index)
        self.current_editor = self.current_flush = None
        self.mark_dirty()
        self.refresh_tree(('manifest',None))

    def tree_context_menu(self, point):
        item = self.tree.itemAt(point)
        selection = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not selection or selection[0] not in {'heroes', 'skills', 'patches'}:
            return
        self.tree.setCurrentItem(item)
        menu = QMenu(self)
        action = menu.addAction('删除此条目')
        action.triggered.connect(self.delete_current)
        menu.exec(self.tree.viewport().mapToGlobal(point))

    def manage_dependencies(self, paths, declare=False):
        """Add only explicit files; usable without a modal dialog by the verifier."""
        self.flush()
        from mod_packages import inspect_package
        existing = [Path(p).absolute() for p in getattr(self.catalog, 'package_paths', [])]
        added = []
        candidates = [(Path(path).absolute(), inspect_package(Path(path).absolute(), self.catalog.base)) for path in paths]
        for file,package in candidates:
            if file not in existing:
                existing.append(file)
            if declare and package.package_id != self.project.manifest.get('packageId'):
                dependency = {'packageId': package.package_id, 'version': package.version, 'digest': package.digest}
                values = self.project.manifest.setdefault('dependencies', [])
                prior = next((i for i, d in enumerate(values) if d.get('packageId') == package.package_id), None)
                if prior is None:
                    values.append(dependency)
                else:
                    values[prior] = dependency
            added.append({'name': package.manifest.get('name'), 'version': package.version,
                          'packageId': package.package_id, 'path': str(file)})
        self.catalog.package_paths = existing
        self.project.metadata['offlineDependencyPaths'] = [str(p) for p in existing]
        self.mark_dirty()
        selection = self.current
        self.current_flush = self.current_editor = None
        self.refresh_tree(selection)
        return added

    def show_dependency_manager(self):
        self.flush()
        dialog = QDialog(self)
        dialog.setWindowTitle('显式离线依赖包 · 不扫描游戏目录')
        dialog.resize(1000, 520)
        layout = QVBoxLayout(dialog)
        info = QLabel('这些文件仅用于本工程的引用、依赖与导出校验。工程保存文件路径；移动后需要重新选择。清单依赖仍需对应的 UUID、版本和可选摘要。')
        info.setWordWrap(True)
        layout.addWidget(info)
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(['包名称', '版本', 'UUID', '文件位置 / 缺失原因'])
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        declare = QCheckBox('添加时同时声明精确版本与摘要依赖')
        declare.setChecked(True)
        layout.addWidget(declare)
        def refresh():
            from mod_packages import inspect_package
            paths = list(getattr(self.catalog, 'package_paths', []))
            table.setRowCount(len(paths))
            for i, path in enumerate(paths):
                try:
                    pack = inspect_package(path, self.catalog.base)
                    values = [pack.manifest.get('name',''), pack.version, pack.package_id, str(path)]
                except Exception as error:
                    values = ['无法读取 / 缺失', '', '', str(path)+'\n'+str(error)]
                for j,value in enumerate(values):
                    table.setItem(i,j,QTableWidgetItem(value))
            table.resizeColumnsToContents()
        def add():
            paths,_ = QFileDialog.getOpenFileNames(dialog, '选择依赖包文件', '', '游戏英雄包 (*.heropack)')
            if paths:
                self.run(self.manage_dependencies, paths, declare.isChecked())
                refresh()
        def remove():
            row = table.currentRow()
            if row >= 0:
                paths = list(getattr(self.catalog, 'package_paths', []))
                paths.pop(row)
                self.catalog.package_paths = paths
                self.project.metadata['offlineDependencyPaths'] = [str(p) for p in paths]
                self.mark_dirty()
                refresh()
        buttons = QHBoxLayout()
        for label,callback in [('添加离线包',add),('移除所选文件',remove),('完成',dialog.accept)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        refresh()
        dialog.exec()
        # Rebuild after explicit library changes; do not flush a stale dependency table.
        self.current_flush = self.current_editor = None
        self.refresh_tree(('manifest', None))

    def import_media(self, path, data=None, output_path=None):
        self.flush()
        source = Path(path)
        raw = source.read_bytes() if data is None else data
        if len(raw) > 33554432:
            raise ValueError('素材超过单文件 32 MiB 上限。')
        name = output_path or 'assets/'+re.sub(r'[^A-Za-z0-9_.-]','_',source.name)
        if not name.startswith('assets/'):
            name = 'assets/'+name
        if name in self.project.assets and output_path is None:
            stem,suffix = Path(name).stem,Path(name).suffix
            i = 2
            while name in self.project.assets:
                name = f'assets/{stem}_{i}{suffix}'
                i += 1
        self.project.assets[name] = bytes(raw)
        self.mark_dirty()
        return name

    def choose_image(self, slot='icon', hero=None):
        path,_ = QFileDialog.getOpenFileName(self,'选择原始图片','','图片 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)')
        if not path:
            return
        raw = self.read_image_source(path)
        dialog = ImageEditorDialog(raw,self, recipe={'purpose':'portrait','framed':False,'quality':hero.get('quality',6) if hero else 6} if slot == 'portrait' else None)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            output = self.unique_image_path(Path(path).with_suffix('.png'))
            self.store_image_edit_result(output, raw, dialog.recipe(), dialog.output,
                                         foreground=dialog.foreground_mask(), clip=dialog.clip_mask())
            if hero is not None:
                self.flush()
                index = next(i for i, row in enumerate(self.project.data['heroes']['heroes']) if row is hero)
                self.assign_asset(output,index,slot)
                self.current_flush = None
                self.refresh_tree(('heroes',index))
            else:
                self.select_entity('assets')

    @staticmethod
    def read_image_source(path):
        file = Path(path)
        if not 0 < file.stat().st_size <= 32*1024*1024:
            raise ValueError('源图需完整保存在可重编工程中，单文件必须在 32 MiB 以内。请先缩小源图，再导入。')
        raw = file.read_bytes()
        if not 0 < len(raw) <= 32*1024*1024:
            raise ValueError('源图为空或读取时超过了 32 MiB。原工程未改变。')
        return raw

    def unique_image_path(self, path):
        filename = re.sub(r'[^A-Za-z0-9_.-]', '_', Path(path).with_suffix('.png').name)
        name, index = 'assets/'+filename, 2
        while name in self.project.assets:
            name = 'assets/'+Path(filename).stem+'_'+str(index)+'.png'
            index += 1
        return name

    def store_image_edit_result(self, asset_path, source, recipe, output, *, foreground=None, clip=None):
        """Publish a rendered asset and its working files as one transaction."""
        self.flush()
        if not isinstance(output, bytes) or not output:
            raise ValueError('请先生成完整的 PNG 结果。')
        from mod_packages import validate_media
        validate_media(output, asset_path)
        candidate = Project(copy.deepcopy(self.project.manifest), copy.deepcopy(self.project.data),
                            dict(self.project.assets), copy.deepcopy(self.project.metadata), dict(self.project.working))
        candidate.assets[asset_path] = output
        candidate.store_image_edit(asset_path, source, recipe, foreground=foreground, clip=clip)
        candidate.metadata.get('imageSources', {}).pop(asset_path, None)
        # All image-edit quotas/copies above complete before any live mapping changes.
        self.project.assets.clear()
        self.project.assets.update(candidate.assets)
        self.project.metadata.clear()
        self.project.metadata.update(candidate.metadata)
        self.project.working.clear()
        self.project.working.update(candidate.working)
        self.mark_dirty()
        return asset_path

    def choose_audio(self):
        path,_ = QFileDialog.getOpenFileName(self,'导入 MP3 语音（最长 120 秒）','','MP3 (*.mp3)')
        if path:
            self.import_media(path)
            self.select_entity('assets')

    def selected_asset(self):
        if self.current and self.current[0] == 'assets' and self.asset_table.currentRow() >= 0:
            return self.asset_paths[self.asset_table.currentRow()]
        raise ValueError('请先在素材库中选中一个素材。')

    def preview_asset(self,row):
        if 0 <= row < len(self.asset_paths):
            path = self.asset_paths[row]
            self.preview.show_reference('self:asset/'+path)
            self.icon_preview.setText(path)
            try:
                editing = self.project.image_edit(path)
                if editing:
                    self.preview_text.setText('可重编源图与蒙版已保存在工程工作区，不随英雄包导出。\n配方：\n'+text_value(editing['recipe']))
                else:
                    legacy = self.project.metadata.get('imageSources',{}).get(path,{})
                    self.preview_text.setText('旧工程源图路径：\n'+text_value(legacy) if legacy else '当前是已有成品；若没有原始工作图，重新编辑时会默认不重复套框。')
            except Exception as error:
                self.preview_text.setText('可重编工作素材缺失或损坏：'+str(error)+'\n当前成品仍保留。')

    def play_preview_audio(self):
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        if not hasattr(self, '_audio_player'):
            self._audio_output = QAudioOutput(self)
            self._audio_player = QMediaPlayer(self)
            self._audio_player.setAudioOutput(self._audio_output)
            self._audio_temp = QTemporaryDir('hero-editor-audio-XXXXXX')
        if self._audio_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._audio_player.stop()
            return
        reference = None
        if self.current[0] == 'assets':
            reference = 'self:asset/'+self.selected_asset()
        elif self.current[0] == 'heroes':
            self.flush()
            reference = self.project.data['heroes']['heroes'][self.current[1]].get('presentation', {}).get('voice')
        if not reference:
            raise ValueError('请在素材库选中 MP3，或为当前英雄绑定语音。')
        if reference.startswith('self:asset/'):
            name = reference.split('/',1)[1]
            if not name.lower().endswith('.mp3'):
                raise ValueError('当前素材不是 MP3 语音。')
            path = Path(self._audio_temp.path()) / 'preview.mp3'
            path.write_bytes(self.project.assets.get(name, self.project.assets.get('assets/'+name, b'')))
        else:
            preview = self.catalog.preview(reference)
            path = Path(preview['path']) if preview.get('kind') == 'audio' and preview.get('path') else None
        if not path or not path.is_file():
            raise ValueError('当前语音没有可供本机试听的文件。')
        self._audio_player.setSource(QUrl.fromLocalFile(str(path.absolute())))
        self._audio_player.play()

    def edit_asset(self):
        path = self.selected_asset()
        if Path(path).suffix.lower() not in {'.png','.jpg','.jpeg'}:
            raise ValueError('当前素材不是图片；请选择 PNG 或 JPEG。')
        editing = self.project.image_edit(path)
        finished_only = False
        if editing:
            raw = editing['source']
            dialog = ImageEditorDialog(raw, self, recipe=editing['recipe'],
                                       foreground_mask=editing['foreground'], clip_mask=editing['clip'])
        else:
            info = self.project.metadata.get('imageSources',{}).get(path,{})
            original = Path(info.get('path',''))
            if original.is_file():
                raw = self.read_image_source(original)
                dialog = ImageEditorDialog(raw, self, recipe=info)
            else:
                raw = self.project.assets[path]
                dialog = ImageEditorDialog(raw, self, recipe={'framed': False})
                finished_only = True
                dialog.setWindowTitle('编辑已有成品 · 无原始工作图 · 默认不重复套框')
                notice = QLabel('此素材只有成品，未恢复到原始分层。当前将成品作为新输入，默认不叠框；再次勾选套框会叠加第二层框。')
                notice.setWordWrap(True)
                dialog.layout().insertWidget(0, notice)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Transparent composition is PNG. Preserve an imported JPEG rather
            # than silently storing PNG bytes under its incompatible extension.
            output = path if Path(path).suffix.lower() == '.png' else self.unique_image_path(path)
            self.store_image_edit_result(output, raw, dialog.recipe(), dialog.output,
                                         foreground=dialog.foreground_mask(), clip=dialog.clip_mask())
            self.select_entity('assets')
            if output != path:
                self.statusBar().showMessage('已生成 '+output+'；原 JPEG 保留，请将新 PNG 指派到需要的槽位。', 15000)

    def delete_asset(self):
        path = self.selected_asset()
        if QMessageBox.question(self,'删除素材','删除 '+path+'？引用该素材的槽位会在校验时显示缺失。') == QMessageBox.StandardButton.Yes:
            self.project.remove_image_edit(path)
            del self.project.assets[path]
            self.project.metadata.get('imageSources',{}).pop(path,None)
            self.mark_dirty()
            self.select_entity('assets')

    def assign_asset(self,path,hero_index,slot):
        self.flush()
        if path not in self.project.assets:
            raise ValueError('素材不存在。')
        if slot not in {'portrait','icon','voice'}:
            raise ValueError('只能指派详情页立绘、列表 / 战斗卡面或语音。')
        suffix = Path(path).suffix.lower()
        if (slot == 'voice' and suffix != '.mp3') or (slot != 'voice' and suffix not in {'.png','.jpg','.jpeg'}):
            raise ValueError('语音槽需要 MP3；立绘与卡面槽需要 PNG/JPEG。')
        hero = self.project.data['heroes']['heroes'][hero_index]
        if slot == 'portrait':
            from .media import make_portrait, portrait_size, inspect_image, validate_media
            media = validate_media(self.project.assets[path],path)
            if media.get('cardFrame'):
                raise ValueError('详情页立绘不能直接使用已合成盾框的卡面，请独立导入无框原图。')
            if (media['width'],media['height']) != portrait_size(hero['quality']):
                raw = self.project.assets[path]
                output = self.unique_image_path(Path(path).with_name(Path(path).stem+'_portrait.png'))
                image_info = inspect_image(raw)
                recipe = {'purpose':'portrait','framed':False,'quality':hero['quality'],'size':list(portrait_size(hero['quality'])),
                          'box':[0,0,image_info['width'],image_info['height']]}
                self.store_image_edit_result(output,raw,recipe,make_portrait(raw,hero['quality']))
                path = output
        hero['presentation'][slot] = 'self:asset/'+path
        self.mark_dirty()
        self.statusBar().showMessage(f'已指派给 {hero["name"]} 的 {slot}。',8000)
        return hero['presentation'][slot]

    def assign_selected_asset(self):
        if self.asset_hero.currentData() is None:
            raise ValueError('工程中没有新增英雄。补丁请在 presentation 对应字段选择本包素材。')
        return self.assign_asset(self.selected_asset(),self.asset_hero.currentData(),self.asset_slot.currentData())

    def refresh_preview(self,flush=True):
        if flush:
            self.flush()
        if not self.current:
            return
        kind,index = self.current
        if kind == 'heroes':
            hero = self.project.data[kind][kind][index]
            presentation = hero.get('presentation',{})
            self.preview.show_reference(presentation.get('portrait'))
            self.icon_preview.show_reference(presentation.get('icon'))
            self.preview_text.setText(f'{hero.get("name", "")} · {QUALITY.get(hero.get("quality"), "")} · {hero.get("role") or hero.get("signType", "")}\n等级 1 / 上限 {hero.get("levelCap", "")}\n' +
                '\n'.join(label+'：'+str(hero.get('baseStats',{}).get(key,0))+' + '+str(hero.get('growth',{}).get(key,0))+'/级' for key,label in STATS.items()))
        elif kind == 'patches':
            target = self.project.data[kind][kind][index].get('target','')
            aid = target.split('/')[-1]
            self.preview.show_reference('builtin:portrait/'+aid)
            self.icon_preview.show_reference('builtin:icon/'+aid)
            self.preview_text.setText('当前补丁目标：'+target+'\n只应用显式列出的字段；原始值与目标摘要由模型保护。')
        elif kind == 'skills':
            skill = self.project.data[kind][kind][index]
            self.preview.setText(skill.get('name','')+'\n\n'+skill.get('description',''))
            self.icon_preview.setText('动作从上到下依次结算\n'+str(len(skill.get('actions',[])))+' 个动作')
            self.preview_text.setText('触发：施法者行动机会\n首次等待 '+str(skill.get('warmup'))+'，冷却 '+str(skill.get('cooldown'))+'\n编辑器展示结构与参数；最终结算使用游戏引擎。')
            if skill.get('model')=='native-template-v1':
                timing=skill['nativeTemplate']['settings'].get('pl')
                self.preview_text.setText('完整原生机制模板\n'+skill['nativeTemplate']['source']+'\n'+
                    (f'首次等待 {timing[0]}，冷却 {timing[1]}，距离 {timing[2]}' if timing else '原生被动技能')+
                    '\n动作、条件、目标关联、成长和复合机制参数均随工程保存。')
        elif kind == 'manifest':
            self.preview.setText('英雄工坊\n\nNEW · 新英雄\nREPLACE · 精确补丁')
            self.icon_preview.setText(self.project.manifest.get('version','1.0.0'))
            self.preview_text.setText('包 UUID\n'+self.project.manifest.get('packageId','')+'\n\n发布后保持 UUID，可由游戏识别版本与存档身份。')

    def show_benchmarks(self):
        self.flush()
        hero = self.project.data['heroes']['heroes'][self.current[1]] if self.current and self.current[0] == 'heroes' else {}
        BenchmarkDialog(self.catalog,hero.get('quality',6),hero.get('role',''),self).exec()

    def show_coverage(self):
        editor = self.current_editor if isinstance(self.current_editor,SkillEditor) else SkillEditor(self.catalog,self.project,self)
        editor.show_coverage()
        if editor is not self.current_editor:
            editor.deleteLater()

    def apply_json_edit(self, value, parsed):
        if not isinstance(value, dict) or not isinstance(parsed, dict):
            raise ValueError('条目必须是对象。')
        manifest, data = copy.deepcopy(self.project.manifest), copy.deepcopy(self.project.data)
        if value is self.project.manifest:
            manifest = copy.deepcopy(parsed)
        else:
            found = False
            for kind in ('heroes', 'skills', 'patches'):
                for index, row in enumerate(self.project.rows(kind)):
                    if row is value:
                        data[kind][kind][index] = copy.deepcopy(parsed)
                        found = True
                        break
            if not found:
                raise ValueError('此数据不是当前工程中的可编辑条目。')
        # Validate renderable structure before replacing the only live copy.
        # Incomplete drafts remain allowed; export performs the full schema.
        Project(manifest, data, dict(self.project.assets), copy.deepcopy(self.project.metadata))
        value.clear()
        value.update(copy.deepcopy(parsed))

    def show_json(self,title,value,editable=True):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(850,620)
        layout = QVBoxLayout(dialog)
        label = QLabel('高级入口不替代可视化表单；新增字段仍必须通过游戏规范校验。' if editable else '只读原始数据 / 报告')
        layout.addWidget(label)
        editor = plain_edit(json.dumps(value,ensure_ascii=False,indent=2))
        editor.setReadOnly(not editable)
        editor.setFont(QFont('Consolas',10))
        layout.addWidget(editor)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel if editable else QDialogButtonBox.StandardButton.Close)
        layout.addWidget(buttons)
        if editable:
            def accept():
                try:
                    parsed = json.loads(editor.toPlainText())
                    self.apply_json_edit(value, parsed)
                    self.current_editor = self.current_flush = None
                    self.mark_dirty()
                    dialog.accept()
                    self.refresh_tree(self.current)
                except Exception as error:
                    self.show_error(error)
            buttons.accepted.connect(accept)
        buttons.rejected.connect(dialog.reject)
        return dialog.exec()

    def locate_issue(self,item,*_):
        issue = item.data(0,Qt.ItemDataRole.UserRole) or {}
        path = str(issue.get('path',''))
        match = re.search(r'(heroes|skills|patches)\[(\d+)\](?:\.(.*))?',path)
        if match:
            kind,index,field = match[1],int(match[2]),match[3] or ''
            if index < len(self.project.data[kind][kind]):
                self.select_entity(kind,index)
                if field in self.field_widgets:
                    widget = self.field_widgets[field]
                    widget.setFocus()
                    if isinstance(widget,QLineEdit):
                        widget.selectAll()
                elif kind == 'skills' and isinstance(self.current_editor,SkillEditor):
                    action = re.search(r'actions\[(\d+)\]',field)
                    self.current_editor.tabs.setCurrentIndex(1 if action else 0)
                    if action:
                        self.current_editor.actions.setCurrentRow(int(action[1]))
        elif 'assets/' in path:
            self.select_entity('assets')
        else:
            self.select_entity('manifest')
            field = path.removeprefix('manifest.')
            if field in self.field_widgets:
                self.field_widgets[field].setFocus()
        self.statusBar().showMessage(path+'：'+str(issue.get('message','')),15000)

    def closeEvent(self,event:QCloseEvent):
        try:
            if self.may_discard():
                event.accept()
            else:
                event.ignore()
        except Exception as error:
            event.ignore()
            self.show_error(error)
