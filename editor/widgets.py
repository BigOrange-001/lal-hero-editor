"""Reusable visual controls for the hero pack editor (no game runtime needed)."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QRectF, Signal, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QGraphicsScene, QGraphicsView, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

QUALITY = {6: '橙色', 5: '紫色', 4: '蓝色', 3: '绿色', 2: '白色'}
STATS = {'health': '生命', 'attack': '攻击', 'physicalDefense': '物理防御', 'magicDefense': '魔法防御'}
CHANNELS = {
    'appearance.arena_enemy': '作为竞技场敌人',
    'acquisition.summon.normal': '普通抽卡', 'acquisition.summon.advanced': '高级抽卡',
    'acquisition.shop.hero_soul': '碎片兑换商店', 'appearance.fragment_enemy': '碎片玩法敌人',
    'appearance.exploration_enemy': '探索敌人', 'appearance.expedition_enemy': '远征敌人（当前无生成器）',
    'appearance.campaign_random_enemy': '战役随机敌人（当前固定阵容）',
    'appearance.assist_bot': '系统助战', 'acquisition.summon.activity': '活动抽卡',
    'acquisition.exchange.hero': '英雄兑换', 'acquisition.exchange.activity': '活动兑换',
    'acquisition.drop.campaign': '战役掉落', 'acquisition.drop.activity': '活动掉落',
    'acquisition.drop.tower_hero': '爬塔英雄掉落', 'acquisition.drop.tower_soul': '爬塔碎片掉落',
    'usage.friend_assist': '好友助战', 'usage.destiny': '缘分（API 1 不支持自定义关系）',
    'usage.auxiliary_formation': '辅助阵位',
}
SCOPES = {'owned': '玩家持有', 'arenaEnemy': '竞技场敌人', 'pveEnemy': 'PVE 敌人',
          'assist': '助战', 'summoned': '召唤/分身定义'}


class ExactSpinBox(QDoubleSpinBox):
    """Do not round an imported number simply by visiting and saving a form."""
    def setValue(self, value):
        self._source_value = value
        super().setValue(float(value or 0))
        self._display_value = super().value()

    def value(self):
        current = super().value()
        if hasattr(self, '_display_value') and current == self._display_value:
            return self._source_value
        return current

    def textFromValue(self, value):
        text = super().textFromValue(value)
        decimal = self.locale().decimalPoint()
        if decimal in text:
            whole, fraction = text.rsplit(decimal, 1)
            fraction = fraction.rstrip('0')
            return whole + (decimal + fraction if fraction else '')
        return text


def number(value=0, minimum=0, maximum=10000000, decimals=3, step=1):
    spin = ExactSpinBox()
    spin.setRange(minimum, maximum)
    spin.setDecimals(max(decimals, 8))
    spin.setSingleStep(step)
    spin.setKeyboardTracking(False)
    spin.setValue(float(value or 0))
    spin.setMinimumWidth(105)
    spin.setToolTip(f'可直接输入，也可使用上下按钮或滚轮。范围：{minimum} ～ {maximum}\n导入原值：{value!r}；未修改时保留原始精度。')
    return spin


def integer(value=0, minimum=0, maximum=10000):
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setKeyboardTracking(False)
    spin.setValue(int(value or 0))
    spin.setToolTip(f'整数，范围：{minimum} ～ {maximum}；支持输入及滚轮')
    return spin


def combo(values, value=None):
    box = QComboBox()
    for item in values:
        label, data = item if isinstance(item, tuple) else (item, item)
        box.addItem(str(label), data)
    if value is not None:
        i = box.findData(value)
        if i >= 0:
            box.setCurrentIndex(i)
    return box


class RefCombo(QComboBox):
    """Searchable resource picker that also retains explicit dependency refs."""
    def __init__(self, rows=(), optional=True, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMinimumWidth(220)
        if optional:
            self.addItem('（无 / 清空）', None)
        for label, ref in rows:
            self.addItem(str(label), ref)
        self.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setToolTip('输入名称或 ID 搜索；也可填写完整 mod: 依赖引用。')

    def value(self):
        index = self.currentIndex()
        if index >= 0 and self.currentText() == self.itemText(index):
            return self.itemData(index)
        return self.currentText().strip() or None

    def set_value(self, value):
        index = self.findData(value)
        if index >= 0:
            self.setCurrentIndex(index)
        elif value is None:
            self.setEditText('')
        else:
            self.addItem(str(value), value)
            self.setCurrentIndex(self.count() - 1)


class FlagsEditor(QGroupBox):
    def __init__(self, title, labels, values=None, changed=None, parent=None):
        super().__init__(title, parent)
        grid = QGridLayout(self)
        self.checks = {}
        self.original = dict(values or {})
        for index, (key, label) in enumerate(labels.items()):
            check = QCheckBox(label)
            check.setChecked(self.original.get(key, True))
            check.setToolTip(key + '\n默认启用；游戏会根据品质及已开放的玩法适配进一步限制。')
            if changed:
                check.toggled.connect(changed)
            grid.addWidget(check, index // 2, index % 2)
            self.checks[key] = check

    def value(self):
        return {key: check.isChecked() for key, check in self.checks.items()
                if key in self.original or not check.isChecked()}


class ResourcePreview(QLabel):
    def __init__(self, catalog, project=None, parent=None):
        super().__init__(parent)
        self.catalog, self.project = catalog, project
        self._source_pixmap = None
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(135)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet('background:#18212c;border:1px solid #46566b;border-radius:6px;padding:8px;')
        self.setText('选择资源以预览')
        self.setTextFormat(Qt.TextFormat.PlainText)

    def setText(self, text):
        self._source_pixmap = None
        super().setText(text)

    def setPixmap(self, pixmap):
        self._source_pixmap = QPixmap(pixmap) if not pixmap.isNull() else None
        if self._source_pixmap is None:
            super().setPixmap(QPixmap())
        else:
            self.fit_pixmap()

    def fit_pixmap(self):
        if self._source_pixmap is None:
            return
        size = self.contentsRect().adjusted(8, 8, -8, -8).size()
        if size.width() > 0 and size.height() > 0:
            super().setPixmap(self._source_pixmap.scaled(size, Qt.AspectRatioMode.KeepAspectRatio,
                                                       Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_pixmap()

    def show_reference(self, reference):
        self.setPixmap(QPixmap())
        if not reference:
            self.setText('未绑定素材')
            return
        try:
            if str(reference).startswith('self:asset/') and self.project:
                path = str(reference).split('/', 1)[1]
                raw = self.project.assets.get(path, self.project.assets.get('assets/' + path))
                if raw:
                    image = QImage.fromData(raw)
                    if not image.isNull():
                        self.setPixmap(QPixmap.fromImage(image))
                        return
            preview = self.catalog.preview(reference) if hasattr(self.catalog, 'preview') else None
            if not preview:
                rows = list(getattr(self.catalog, 'effects', [])) + list(getattr(self.catalog, 'heroes', []))
                preview = next((r.get('preview') for r in rows if r.get('reference') == reference), None)
            if isinstance(preview, dict):
                path = preview.get('path') or preview.get('image')
                if path and Path(path).is_file():
                    image = QPixmap(str(path))
                    if not image.isNull():
                        if preview.get('box'):
                            image = image.copy(*[int(part) for part in preview['box']])
                        self.setPixmap(image)
                        return
                self.setText(str(preview.get('text') or preview.get('description') or preview.get('reason') or
                                 json.dumps(preview, ensure_ascii=False, indent=2))[:2400])
            else:
                self.setText(str(reference) + '\n\n使用原版素材。动画由游戏时间线执行，编辑器不执行 SWF。')
        except Exception as error:
            self.setText(str(reference) + '\n预览不可用：' + str(error))


class CropView(QGraphicsView):
    selectionChanged = Signal(tuple)

    def __init__(self, image, parent=None):
        super().__init__(parent)
        self.scene_ = QGraphicsScene(self)
        self.setScene(self.scene_)
        self.scene_.addPixmap(QPixmap.fromImage(image))
        self.bounds = QRectF(0, 0, image.width(), image.height())
        self.scene_.setSceneRect(self.bounds)
        self.crop = self.scene_.addRect(self.bounds, QPen(QColor('#5de0d1'), 2), QColor(70, 210, 180, 35))
        self.crop.setZValue(2)
        self.anchor = None
        self.moving = False
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setMinimumSize(350, 300)
        self.setToolTip('在图上拖动框选；选区内拖动可平移；按住 Shift 重新框选。也可右侧输入精确坐标。')

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fitInView(self.bounds, Qt.AspectRatioMode.KeepAspectRatio)

    def set_box(self, box, emit=False):
        left, top, right, bottom = box
        rect = QRectF(left, top, max(1, right-left), max(1, bottom-top)).intersected(self.bounds)
        self.crop.setRect(rect)
        if emit:
            self.selectionChanged.emit((round(rect.left()), round(rect.top()), round(rect.right()), round(rect.bottom())))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.anchor = self.mapToScene(event.position().toPoint())
            self.initial = self.crop.rect()
            self.moving = self.initial != self.bounds and self.initial.contains(self.anchor) and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.anchor is not None:
            end = self.mapToScene(event.position().toPoint())
            if self.moving:
                rect = self.initial.translated(end - self.anchor)
                rect.moveLeft(max(0, min(rect.left(), self.bounds.width()-rect.width())))
                rect.moveTop(max(0, min(rect.top(), self.bounds.height()-rect.height())))
            else:
                rect = QRectF(self.anchor, end).normalized().intersected(self.bounds)
            if rect.width() >= 1 and rect.height() >= 1:
                self.set_box((rect.left(), rect.top(), rect.right(), rect.bottom()), True)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.anchor = None
        super().mouseReleaseEvent(event)


class ImageEditorDialog(QDialog):
    """Non-destructive crop + native frame + two explicit, paintable mattes."""
    def __init__(self, data, parent=None, *, recipe=None, foreground_mask=None, clip_mask=None):
        super().__init__(parent)
        from .media import inspect_image
        from .compositor_widgets import LayerCanvas
        from PIL import Image, ImageOps
        from io import BytesIO
        if not isinstance(data, bytes) or not 0 < len(data) <= 32 * 1024 * 1024:
            raise ValueError('为了把可重编的源图完整保存在工程中，源图必须为 1 字节至 32 MiB。请先缩小过大的图片。')
        self.data, self.output = data, None
        self.portrait_mode = bool(recipe and recipe.get('purpose') == 'portrait')
        self.source_mode = not self.portrait_mode and (recipe is None or recipe.get('selectionSpace') == 'source')
        self._legacy_layer_order = recipe.get('layerOrder') if recipe and recipe.get('layerOrder') in ('behind','split') else None
        self._restoring = True
        self._layers = None
        self._layers_key = None
        self._size_by_mode = {False: (320, 480), True: (160, 160)}
        info = inspect_image(data)
        with Image.open(BytesIO(data)) as original:
            corrected = ImageOps.exif_transpose(original).convert('RGBA')
            raw = corrected.tobytes()
            image = QImage(raw, corrected.width, corrected.height, corrected.width*4,
                           QImage.Format.Format_RGBA8888).copy()
            corrected.close()
        self.image_width, self.image_height = image.width(), image.height()
        self.setWindowTitle('图片与原版透明框 · 图层合成')
        self.resize(1220, 850)
        self.setMinimumSize(920, 680)
        outer = QVBoxLayout(self)
        notice = QLabel('先把盾形选区移到原图上并调好大小，再用正选笔补入头发/武器，用反选笔删去不要的部分。实际使用区域与前后遮挡可以分别编辑。')
        notice.setWordWrap(True)
        outer.addWidget(notice)
        splitter = QSplitter()
        self.tabs = QTabWidget()
        if self.source_mode:
            from .source_selection import SourceShieldView
            self.view = SourceShieldView(image, (recipe or {}).get('quality', 6))
            selection_page = QWidget()
            selection_layout = QVBoxLayout(selection_page)
            selection_tools = QHBoxLayout()
            self.selection_tool = combo([('移动 / 缩放盾形选区', 'move'), ('正选笔 · 添加使用区域', 'add'),
                                         ('反选笔 · 减少使用区域', 'subtract'), ('查看 / 平移', 'pan')])
            self.selection_brush = integer(12, 1, 512)
            selection_tools.addWidget(self.selection_tool)
            selection_tools.addWidget(QLabel('笔刷大小'))
            selection_tools.addWidget(self.selection_brush)
            reset = QPushButton('重置为盾形')
            reset.clicked.connect(self.view.reset_selection)
            selection_tools.addWidget(reset)
            fit_source = QPushButton('适合窗口')
            fit_source.clicked.connect(self.view.fit_canvas)
            selection_tools.addWidget(fit_source)
            selection_layout.addLayout(selection_tools)
            selection_layout.addWidget(self.view, 1)
            hint = QLabel('拖动盾形内部移动，拖动四角等比缩放；滚轮放大查看。亮区是实际使用范围，暗区不会导入。正选可超出盾框，反选可挖掉框内不要的背景。')
            hint.setWordWrap(True)
            selection_layout.addWidget(hint)
            self.selection_tool.currentIndexChanged.connect(self.update_selection_tool)
            self.selection_brush.valueChanged.connect(self.update_selection_tool)
            self.tabs.addTab(selection_page, '① 在原图上选择实际使用区域')
        else:
            self.view = CropView(image)
            self.tabs.addTab(self.view, '① 原图裁剪（旧工程）')
        canvas_page = QWidget()
        canvas_layout = QVBoxLayout(canvas_page)
        zoom_row = QHBoxLayout()
        fit = QPushButton('适合窗口')
        self.zoom = integer(100, 10, 1600)
        self.zoom.setSuffix(' %')
        zoom_row.addWidget(fit)
        zoom_row.addWidget(QLabel('缩放'))
        zoom_row.addWidget(self.zoom)
        zoom_row.addStretch()
        canvas_layout.addLayout(zoom_row)
        self.canvas = LayerCanvas()
        self.preview = self.canvas
        canvas_layout.addWidget(self.canvas, 1)
        self.canvas_hint = QLabel('棋盘表示透明区域；蒙版着色只是编辑辅助，不会写入成品。滚轮缩放，选择“查看/平移”可拖动画布。')
        self.canvas_hint.setWordWrap(True)
        self.canvas_hint.setObjectName('muted')
        canvas_layout.addWidget(self.canvas_hint)
        self.tabs.addTab(canvas_page, '② 图层合成与蒙版')
        splitter.addWidget(self.tabs)
        controls_scroll = QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls = QWidget()
        control_layout = QVBoxLayout(controls)
        crop_group = QGroupBox('盾形选框 · 原图坐标（等比）' if self.source_mode else '原图裁剪 · EXIF 转正后的像素坐标')
        crop_form = QFormLayout(crop_group)
        self.coords = [integer(v, 0, max(image.width(), image.height()))
                       for v in (0, 0, image.width(), image.height())]
        for label, field in zip(('左边 X', '上边 Y', '右边 X', '下边 Y'), self.coords):
            crop_form.addRow(label, field)
            field.valueChanged.connect(self.coordinates_changed)
        control_layout.addWidget(crop_group)
        output_group = QGroupBox('输出与原版框')
        output_form = QFormLayout(output_group)
        self.width, self.height = integer(320, 1, 2048), integer(480, 1, 2048)
        output_form.addRow('输出宽度', self.width)
        output_form.addRow('输出高度', self.height)
        self.frame_inset = integer(12 if self.source_mode else 0, 0, 35)
        self.frame_inset.setSuffix(' %')
        output_form.addRow('出框留白', self.frame_inset)
        self.quality = combo([(v, k) for k, v in QUALITY.items()], 6)
        self.framed = QCheckBox('叠加原版独立透明品质框')
        self.background = QCheckBox('使用原版框内底图（若原模板包含）')
        self.background.setChecked(True)
        self.layer_order = combo([('框在下，人物图在上', 'front')], 'front')
        output_form.addRow(self.framed)
        output_form.addRow('原版框品质', self.quality)
        output_form.addRow('前后图层关系', self.layer_order)
        output_form.addRow(self.background)
        presets = QHBoxLayout()
        for name, size in [('原版框 160²', (160, 160)), ('普通裁剪 320×480', (320, 480))]:
            button = QPushButton(name)
            button.clicked.connect(lambda checked=False, value=size: self.set_output_size(value))
            presets.addWidget(button)
        output_form.addRow(presets)
        self.layer_hint = QLabel()
        self.layer_hint.setWordWrap(True)
        output_form.addRow(self.layer_hint)
        control_layout.addWidget(output_group)
        self.mask_group = QGroupBox('手工蒙版 · 输出画布像素坐标')
        mask_form = QFormLayout(self.mask_group)
        self.mask_target = combo([('查看 / 平移（不画蒙版）', None),
                                  ('前景出框蒙版', 'foreground'), ('框内裁剪蒙版', 'clip')])
        self.brush_mode = combo([('画出显示区域 · 白', False), ('擦去显示区域 · 黑', True)])
        self.brush_size = integer(12, 1, 512)
        self.show_mask = QCheckBox('显示所选蒙版着色（不导出）')
        self.show_mask.setChecked(True)
        mask_form.addRow('编辑图层', self.mask_target)
        mask_form.addRow('画笔 / 橡皮', self.brush_mode)
        mask_form.addRow('笔刷直径（输出像素）', self.brush_size)
        mask_form.addRow(self.show_mask)
        row = QHBoxLayout()
        for label, callback in [('重置当前蒙版', self.reset_current_mask), ('导入 PNG 蒙版', self.import_current_mask)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        mask_form.addRow(row)
        row = QHBoxLayout()
        for label, callback in [('另存当前蒙版 PNG', self.save_current_mask), ('另存原版透明框', self.save_native_frame)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            row.addWidget(button)
        mask_form.addRow(row)
        help_text = QLabel('前景蒙版：白色区域的人物放到框上面。框内蒙版：白色区域保留框后人物，黑色裁掉。\n透明 PNG 蒙版使用实际 alpha；不透明灰度图使用亮度。普通照片不会自动变成透明人物。')
        help_text.setWordWrap(True)
        mask_form.addRow(help_text)
        control_layout.addWidget(self.mask_group)
        if self._legacy_layer_order is None:
            self.mask_group.hide()
        self.status = QLabel()
        self.status.setWordWrap(True)
        control_layout.addWidget(self.status)
        render = QPushButton('生成 / 更新透明预览')
        render.setProperty('primary', True)
        render.clicked.connect(self.render_preview)
        control_layout.addWidget(render)
        details = QLabel(f'原图 {image.width()} × {image.height()}；{info.get("bytes", len(data)):,} 字节\n源图与蒙版随工程保存（单文件 ≤32 MiB），不会进入 .heropack。\n人物与原版框均等比处理，不拉伸框形。')
        details.setWordWrap(True)
        details.setObjectName('muted')
        control_layout.addWidget(details)
        control_layout.addStretch()
        controls_scroll.setWidget(controls)
        controls_scroll.setMinimumWidth(340)
        controls_scroll.setMaximumWidth(440)
        splitter.addWidget(controls_scroll)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        outer.addWidget(splitter, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('使用生成结果并保留可重编工程')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.accept_output)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(180)
        self._preview_timer.timeout.connect(lambda: self.render_preview(quiet=True))
        if self.source_mode:
            self.view.frameChanged.connect(self.selection_changed)
            self.view.maskChanged.connect(lambda _: self.invalidate_output(schedule=False))
            self.view.strokeFinished.connect(lambda: self.render_preview(quiet=True))
        else:
            self.view.selectionChanged.connect(self.selection_changed)
        self.canvas.strokeFinished.connect(lambda: self.render_preview(quiet=True))
        self.canvas.maskChanged.connect(lambda _: self.invalidate_output(schedule=False))
        self.canvas.zoomChanged.connect(self.sync_zoom)
        self.zoom.valueChanged.connect(self.canvas.set_zoom)
        fit.clicked.connect(self.canvas.fit_canvas)
        for field in (self.mask_target, self.brush_mode, self.brush_size, self.show_mask):
            signal = getattr(field, 'currentIndexChanged', None) or getattr(field, 'valueChanged', None) or field.toggled
            signal.connect(self.update_tool)
        self.framed.toggled.connect(self.frame_changed)
        self.width.valueChanged.connect(self.settings_changed)
        self.height.valueChanged.connect(self.settings_changed)
        self.quality.currentIndexChanged.connect(self.settings_changed)
        self.layer_order.currentIndexChanged.connect(self.settings_changed)
        self.background.toggled.connect(self.settings_changed)
        self.frame_inset.valueChanged.connect(self.settings_changed)
        recipe = dict(recipe or {})
        if self.portrait_mode:
            self.setWindowTitle('详情页立绘 · 独立无框图片')
            notice.setText('此图片用于角色详情页，与卡面独立。按原版品质尺寸锁定输出，人物等比完整缩放，空余补透明像素；不会叠盾框。可调整裁剪范围。')
            from .media import portrait_size
            recipe['size'] = portrait_size(recipe.get('quality', 6))
            recipe.setdefault('quality', 6)
            recipe.setdefault('box', (0, 0, self.image_width, self.image_height))
            recipe['framed'] = False
            self.framed.setEnabled(False)
        framed = recipe.get('framed', self.source_mode)
        self.width.setValue(recipe.get('size', (160, 160) if framed else (320, 480))[0])
        self.height.setValue(recipe.get('size', (160, 160) if framed else (320, 480))[1])
        initial_box = recipe.get('box', self.view.source_box() if self.source_mode else (0, 0, image.width(), image.height()))
        for field, value in zip(self.coords, initial_box):
            field.setValue(round(value))
        self.quality.setCurrentIndex(max(0, self.quality.findData(recipe.get('quality', 6))))
        self.layer_order.setCurrentIndex(max(0, self.layer_order.findData(recipe.get('layerOrder', 'split'))))
        self.background.setChecked(recipe.get('includeBackground', True))
        self.frame_inset.setValue(recipe.get('frameInset', 12 if self.source_mode else 0))
        self.framed.setChecked(framed)
        self._previous_framed = framed
        self._size_by_mode[framed] = (self.width.value(), self.height.value())
        self.canvas.configure((self.width.value(), self.height.value()))
        if foreground_mask is not None:
            self.canvas.import_mask('foreground', foreground_mask)
        if clip_mask is not None:
            (self.view if self.source_mode else self.canvas).import_mask('clip', clip_mask)
        self._restoring = False
        if self.source_mode:
            self.view.set_box(initial_box)
            # Re-apply saved source-space pixels after positioning the shield.
            if clip_mask is not None:
                self.view.import_mask('clip', clip_mask)
            self.update_selection_tool()
        else:
            self.coordinates_changed()
        self.update_controls()
        self.render_preview(quiet=True)

    def update_selection_tool(self, *_):
        if self.source_mode:
            self.view.set_mode(self.selection_tool.currentData(), self.selection_brush.value())

    def set_output_size(self, size):
        self._restoring = True
        self.width.setValue(size[0])
        self.height.setValue(size[1])
        self._restoring = False
        self.settings_changed()

    def selection_changed(self, box):
        for field, value in zip(self.coords, box):
            field.blockSignals(True)
            field.setValue(round(value))
            field.blockSignals(False)
        self.invalidate_output()

    def coordinates_changed(self, *_):
        box = tuple(field.value() for field in self.coords)
        if box[2] > box[0] and box[3] > box[1]:
            self.view.set_box(box)
        self.invalidate_output()

    def frame_changed(self, framed):
        if self._restoring:
            return
        self._size_by_mode[self._previous_framed] = (self.width.value(), self.height.value())
        self._previous_framed = framed
        self.set_output_size(self._size_by_mode[framed])
        self.tabs.setCurrentIndex(1 if framed else 0)
        self.update_controls()

    def settings_changed(self, *_):
        if self._restoring:
            return
        if self.source_mode and self.view.quality != self.quality.currentData():
            self.view.set_quality(self.quality.currentData())
        self.update_controls()
        self.invalidate_output()

    def update_controls(self):
        framed = self.framed.isChecked()
        self.mask_group.setEnabled(framed)
        self.quality.setEnabled(framed or self.portrait_mode)
        self.width.setEnabled(not self.portrait_mode)
        self.height.setEnabled(not self.portrait_mode)
        if self.portrait_mode:
            from .media import portrait_size
            for field, value in zip((self.width,self.height),portrait_size(self.quality.currentData())):
                field.blockSignals(True)
                field.setValue(value)
                field.blockSignals(False)
        self.layer_order.setEnabled(framed)
        self.background.setEnabled(framed)
        if self.source_mode:
            self.mask_target.model().item(self.mask_target.findData('clip')).setEnabled(False)
        mode = self.layer_order.currentData()
        text = {'behind': '框在人物前面；框内蒙版决定后景保留区域，前景蒙版不参与此模式。',
                'split': '先画框后人物，再叠原版框，最后叠前景蒙版选中的人物。适合手动控制头发/武器出框。',
                'front': '固定框在下、人物图在上。盾形初始选区排除框本体像素；用正选笔补入需要出框的头发或武器。出框留白不会改变游戏内边框大小。'}[mode]
        self.layer_hint.setText(text if framed else '普通裁剪不叠框；需要原版框与遮挡层时勾选上方选项。')
        self.update_tool()

    def update_tool(self, *_):
        target = self.mask_target.currentData() if self.framed.isChecked() else None
        self.canvas.set_tool(target, self.brush_mode.currentData(), self.brush_size.value(), self.show_mask.isChecked())
        if target:
            self.tabs.setCurrentIndex(1)
        self.brush_mode.setEnabled(target is not None)
        self.brush_size.setEnabled(target is not None)

    def invalidate_output(self, schedule=True):
        if self._restoring:
            return
        self.output = None
        if schedule:
            # A pending size/crop/frame change invalidates scene coordinates.
            # Do not let a stroke land on the previous canvas during debounce.
            self.canvas.setEnabled(False)
            self._preview_timer.start()

    def sync_zoom(self, percentage):
        self.zoom.blockSignals(True)
        self.zoom.setValue(percentage)
        self.zoom.blockSignals(False)

    def recipe(self):
        result = {'box': list(self.view.source_box()) if self.source_mode else [field.value() for field in self.coords], 'size': [self.width.value(), self.height.value()],
                'quality': self.quality.currentData(), 'framed': self.framed.isChecked(), 'purpose': 'portrait' if self.portrait_mode else 'card',
                'layerOrder': self._legacy_layer_order or 'front', 'includeBackground': self.background.isChecked(),
                'frameInset': self.frame_inset.value()}
        if self.source_mode:
            result['selectionSpace'] = 'source'
        return result

    def foreground_mask(self):
        return self.canvas.mask_bytes('foreground')

    def clip_mask(self):
        return self.view.selection_bytes() if self.source_mode else self.canvas.mask_bytes('clip')

    def current_layers(self):
        from .media import frame_layers
        key = (self.quality.currentData(), self.width.value(), self.height.value(), self.frame_inset.value())
        if key != self._layers_key:
            layers = frame_layers(key[0], (key[1], key[2]), inset=key[3]/100)
            self._layers, self._layers_key = layers, key
        return self._layers

    def render_preview(self, *_args, quiet=False):
        from .media import crop_image, make_card
        self._preview_timer.stop()
        try:
            for field in self.coords + [self.width, self.height, self.brush_size]:
                field.interpretText()
            entered_box = tuple(field.value() for field in self.coords)
            if not (0 <= entered_box[0] < entered_box[2] <= self.image_width and 0 <= entered_box[1] < entered_box[3] <= self.image_height):
                raise ValueError('选框必须位于原图内，右边和下边必须大于左边和上边。')
            box = self.view.source_box() if self.source_mode else tuple(field.value() for field in self.coords)
            if not (0 <= box[0] < box[2] <= self.image_width and 0 <= box[1] < box[3] <= self.image_height):
                raise ValueError('裁剪框必须在原图范围内，右边和下边必须大于左边和上边。')
            size = (self.width.value(), self.height.value())
            if self.portrait_mode:
                from .media import make_portrait, portrait_size
                size = portrait_size(self.quality.currentData())
                self.canvas.configure(size)
                self.output = make_portrait(self.data,self.quality.currentData(),box)
                detail = f'原版立绘画布 {size[0]} × {size[1]}；等比完整适配，空余透明。'
            elif self.framed.isChecked() or self.source_mode:
                layers = self.current_layers()
                self.canvas.configure(size, layers['clip'])
                self.output = make_card(self.data, self.quality.currentData(), size, box,
                    layer_order=self._legacy_layer_order or 'front', foreground_mask=self.foreground_mask(),
                    content_mask=None if self.source_mode else self.clip_mask(),
                    source_selection=self.clip_mask() if self.source_mode else None,
                    frame_inset=self.frame_inset.value()/100, include_frame=self.framed.isChecked(),
                    include_background=self.background.isChecked() and self.framed.isChecked())
                native = layers['native_size']
                detail = f'原版框原画布 {native[0]} × {native[1]}；人物/框等比适配。'
            else:
                self.canvas.configure(size)
                self.output = crop_image(self.data, box, size)
                detail = '普通裁剪输出；未叠加品质框。'
            self.canvas.set_preview(self.output)
            self.canvas.setEnabled(True)
            self.status.setStyleSheet('color:#88dcc6;')
            self.status.setText(f'RGBA PNG {size[0]} × {size[1]}；{len(self.output):,} 字节。\n'+detail)
            return True
        except Exception as error:
            self.output = None
            self.canvas.set_preview(None)
            self.canvas.setEnabled(False)
            self.status.setStyleSheet('color:#f1ad81;')
            self.status.setText('尚未生成：'+str(error))
            if not quiet:
                QMessageBox.warning(self, '图片处理未完成', str(error))
            return False

    def active_mask_name(self):
        name = self.mask_target.currentData()
        if name is None:
            raise ValueError('请先选择“前景出框蒙版”或“框内裁剪蒙版”。')
        return name

    def reset_current_mask(self):
        try:
            self.canvas.reset_mask(self.active_mask_name())
        except Exception as error:
            QMessageBox.warning(self, '蒙版未重置', str(error))

    def import_current_mask(self):
        try:
            name = self.active_mask_name()
            path, _ = QFileDialog.getOpenFileName(self, '导入当前图层的 PNG 蒙版', '', 'PNG 蒙版 (*.png)')
            if not path:
                return
            if not 0 < Path(path).stat().st_size <= 32*1024*1024:
                raise ValueError('蒙版单文件必须在 32 MiB 以内。')
            self.canvas.import_mask(name, Path(path).read_bytes())
            self.render_preview(quiet=True)
        except Exception as error:
            QMessageBox.warning(self, '蒙版未导入', str(error))

    def save_current_mask(self):
        try:
            name = self.active_mask_name()
            if self.framed.isChecked():
                self.canvas.configure((self.width.value(), self.height.value()), self.current_layers()['clip'])
            path, _ = QFileDialog.getSaveFileName(self, '另存蒙版（白色显示 / 黑色隐藏）', name+'-mask.png', 'PNG (*.png)')
            if path:
                Path(path if Path(path).suffix else path+'.png').write_bytes(self.canvas.mask_bytes(name, effective=True))
        except Exception as error:
            QMessageBox.warning(self, '蒙版未保存', str(error))

    def save_native_frame(self):
        try:
            from .media import frame_layers
            layers = self.current_layers()
            native = frame_layers(self.quality.currentData(), layers['native_size'])['frame']
            path, _ = QFileDialog.getSaveFileName(self, '另存独立原版透明框（原尺寸，不含人物）', 'native-frame-'+str(self.quality.currentData())+'.png', 'PNG (*.png)')
            if path:
                Path(path if Path(path).suffix else path+'.png').write_bytes(native)
        except Exception as error:
            QMessageBox.warning(self, '原版框未保存', str(error))

    def accept_output(self):
        if self.render_preview():
            self.accept()


class BenchmarkDialog(QDialog):
    def __init__(self, catalog, quality=6, role='', parent=None):
        super().__init__(parent)
        self.catalog = catalog
        self.setWindowTitle('英雄面板平衡性基准 · 真实游戏配置')
        self.resize(1060, 640)
        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.quality = combo([(v, k) for k, v in QUALITY.items()], quality)
        roles = sorted({str(row.get('role') or '') for row in catalog.heroes} - {''})
        self.role = combo([('全部定位', '')] + [(r, r) for r in roles], role)
        self.level = integer(1, 1, 99)
        for label, field in [('品质', self.quality), ('定位', self.role), ('等级', self.level)]:
            filters.addWidget(QLabel(label))
            filters.addWidget(field)
        filters.addStretch()
        layout.addLayout(filters)
        self.conditions = QLabel()
        self.conditions.setWordWrap(True)
        layout.addWidget(self.conditions)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(['英雄 / ID', '定位', '生命', '攻击', '物防', '魔防', '速度', '射程', '领导力'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        self.medians = QLabel()
        self.medians.setWordWrap(True)
        layout.addWidget(self.medians)
        self.quality.currentIndexChanged.connect(self.refresh)
        self.role.currentIndexChanged.connect(self.refresh)
        self.level.valueChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        try:
            result = self.catalog.benchmarks(self.quality.currentData(), self.role.currentData(), self.level.value())
            rows = result.get('rows', [])
            self.table.setRowCount(len(rows))
            keys = ['role', 'health', 'attack', 'physicalDefense', 'magicDefense', 'speed', 'attackRange', 'leadership']
            for i, row in enumerate(rows):
                values = [f'{row.get("name", "")}  {row.get("id", "")}'] + [row.get(k, '') for k in keys]
                for j, value in enumerate(values):
                    self.table.setItem(i, j, QTableWidgetItem(str(round(value, 3) if isinstance(value, float) else value)))
            self.table.resizeColumnsToContents()
            self.conditions.setText(f'符合条件的真实英雄：{result.get("count", len(rows))}。' + str(result.get('conditions', '基础值 + 成长 × (等级 − 1)；不含装备、缘分、进阶附加。')))
            names = {**STATS, 'speed': '速度', 'attackRange': '射程', 'leadership': '领导力'}
            self.medians.setText('同条件中位数（参考值，不强制修改）：' + '　'.join(f'{names.get(k,k)} {v:g}' if isinstance(v,(int,float)) else f'{k} {v}' for k,v in result.get('medians', {}).items()))
        except Exception as error:
            self.conditions.setText('无法读取基准：' + str(error))
