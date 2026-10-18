"""Transparent layer preview and explicit, user-painted grayscale masks."""
from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageOps
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView


def mask_image(data, size):
    """Match media._mask: real transparency means alpha, otherwise luminance."""
    if not isinstance(data, bytes) or not 0 < len(data) <= 32 * 1024 * 1024:
        raise ValueError('蒙版必须是 1 字节至 32 MiB 的 PNG 文件。')
    with Image.open(BytesIO(data)) as source:
        if source.format != 'PNG' or source.width * source.height > 64_000_000:
            raise ValueError('请使用不超过 6400 万像素的单帧 PNG 蒙版。')
        if getattr(source, 'n_frames', 1) != 1:
            raise ValueError('蒙版不能是动画。')
        rgba = source.convert('RGBA')
        alpha = rgba.getchannel('A')
        channel = alpha if alpha.getextrema()[0] < 255 else source.convert('L')
        # Masks live in full output-canvas coordinates; do not invent a subject.
        channel = channel.resize(size, Image.Resampling.LANCZOS)
        grey = channel.convert('RGBA')
        raw = grey.tobytes()
        return QImage(raw, size[0], size[1], size[0]*4, QImage.Format.Format_RGBA8888).copy().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


def png_bytes(image, grayscale=False):
    if grayscale:
        image = image.convertToFormat(QImage.Format.Format_Grayscale8)
    data = QByteArray()
    stream = QBuffer(data)
    stream.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(stream, 'PNG'):
        raise ValueError('无法编码蒙版 PNG。')
    stream.close()
    return bytes(data)


class LayerCanvas(QGraphicsView):
    """Paint full-canvas masks; overlay color is an editor aid, never output."""
    maskChanged = Signal(str)
    strokeFinished = Signal()
    zoomChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene_ = QGraphicsScene(self)
        self.setScene(self.scene_)
        self.picture = self.scene_.addPixmap(QPixmap())
        self.overlay = self.scene_.addPixmap(QPixmap())
        self.overlay.setZValue(2)
        self.cursor_item = self.scene_.addEllipse(QRectF(), QPen(QColor('#f3f5f8'), 0))
        self.cursor_item.setZValue(3)
        self.cursor_item.hide()
        tile = QPixmap(16, 16)
        tile.fill(QColor('#202a36'))
        painter = QPainter(tile)
        painter.fillRect(0, 0, 8, 8, QColor('#354251'))
        painter.fillRect(8, 8, 8, 8, QColor('#354251'))
        painter.end()
        self.checker = QBrush(tile)
        self.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMinimumSize(320, 330)
        self.setMouseTracking(True)
        self.output_size = (160, 160)
        self.masks = {}
        self.overrides = {'foreground': False, 'clip': False}
        self.default_clip = None
        self.active_mask = None
        self.brush_size = 12
        self.erase = False
        self.show_overlay = True
        self.painting = False
        self.last_point = None
        self.auto_fit = True
        self.configure(self.output_size)

    def drawBackground(self, painter, rect):
        painter.fillRect(rect, self.checker)

    def blank_mask(self, white=False):
        image = QImage(*self.output_size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor('white' if white else 'black'))
        return image

    def configure(self, size, default_clip=None):
        size = tuple(int(part) for part in size)
        changed_size = size != self.output_size
        previous = self.masks
        self.output_size = size
        if default_clip is not None:
            self.default_clip = mask_image(default_clip, size)
        elif changed_size:
            self.default_clip = None
        if changed_size:
            self.masks = {}
            for name, image in previous.items():
                if self.overrides[name]:
                    fitted = image.scaled(*size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    target = self.blank_mask()
                    painter = QPainter(target)
                    painter.drawImage((size[0]-fitted.width())//2, (size[1]-fitted.height())//2, fitted)
                    painter.end()
                    self.masks[name] = target
        if 'foreground' not in self.masks:
            self.masks['foreground'] = self.blank_mask()
        if not self.overrides['clip'] or 'clip' not in self.masks:
            self.masks['clip'] = self.default_clip.copy() if self.default_clip is not None else self.blank_mask(True)
        self.scene_.setSceneRect(0, 0, *size)
        self.update_overlay()
        if self.auto_fit:
            self.fit_canvas()

    def set_preview(self, data):
        pixmap = QPixmap()
        if data:
            pixmap.loadFromData(data, 'PNG')
        self.picture.setPixmap(pixmap)

    def import_mask(self, name, data):
        image = mask_image(data, self.output_size)
        self.masks[name] = image
        self.overrides[name] = True
        self.update_overlay()
        self.maskChanged.emit(name)

    def mask_bytes(self, name, effective=False):
        if not effective and not self.overrides[name]:
            return None
        return png_bytes(self.masks[name], grayscale=True)

    def reset_mask(self, name):
        self.overrides[name] = False
        self.masks[name] = (self.default_clip.copy() if self.default_clip is not None else self.blank_mask(True)) if name == 'clip' else self.blank_mask()
        self.update_overlay()
        self.maskChanged.emit(name)
        self.strokeFinished.emit()

    def set_tool(self, name=None, erase=False, brush_size=12, overlay=True):
        self.active_mask, self.erase = name, erase
        self.brush_size, self.show_overlay = brush_size, overlay
        self.setDragMode(QGraphicsView.DragMode.NoDrag if name else QGraphicsView.DragMode.ScrollHandDrag)
        self.setCursor(Qt.CursorShape.CrossCursor if name else Qt.CursorShape.OpenHandCursor)
        self.cursor_item.setVisible(False)
        self.update_overlay()

    def update_overlay(self):
        if not self.active_mask or not self.show_overlay:
            self.overlay.setPixmap(QPixmap())
            return
        mask = self.masks[self.active_mask].convertToFormat(QImage.Format.Format_RGBA8888)
        raw = bytes(mask.constBits())
        source = Image.frombytes('RGBA', self.output_size, raw, 'raw', 'RGBA', mask.bytesPerLine())
        alpha = source.getchannel('R').point(lambda value: round(value * .32))
        colored = Image.new('RGBA', self.output_size, (48, 220, 174, 0) if self.active_mask == 'foreground' else (174, 118, 242, 0))
        colored.putalpha(alpha)
        pixels = colored.tobytes()
        image = QImage(pixels, *self.output_size, self.output_size[0]*4, QImage.Format.Format_RGBA8888).copy()
        self.overlay.setPixmap(QPixmap.fromImage(image))

    def fit_canvas(self):
        self.auto_fit = True
        self.fitInView(self.scene_.sceneRect().adjusted(-8, -8, 8, 8), Qt.AspectRatioMode.KeepAspectRatio)
        self.zoomChanged.emit(round(self.transform().m11()*100))

    def set_zoom(self, percentage):
        self.auto_fit = False
        self.resetTransform()
        self.scale(percentage/100, percentage/100)
        self.zoomChanged.emit(percentage)

    def wheelEvent(self, event):
        percent = round(self.transform().m11()*100 * (1.2 if event.angleDelta().y() > 0 else 1/1.2))
        self.set_zoom(max(10, min(1600, percent)))
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.auto_fit:
            self.fit_canvas()

    def paint_segment(self, start, end):
        image = self.masks[self.active_mask]
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor('black' if self.erase else 'white'), self.brush_size,
                   Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        if start == end:
            painter.drawPoint(end)
        else:
            painter.drawLine(start, end)
        painter.end()
        self.overrides[self.active_mask] = True
        self.update_overlay()
        self.maskChanged.emit(self.active_mask)

    def mousePressEvent(self, event):
        if self.active_mask and event.button() == Qt.MouseButton.LeftButton:
            point = self.mapToScene(event.position().toPoint())
            if self.scene_.sceneRect().contains(point):
                self.painting = True
                self.last_point = point
                self.paint_segment(point, point)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        point = self.mapToScene(event.position().toPoint())
        if self.active_mask:
            radius = self.brush_size/2
            self.cursor_item.setRect(point.x()-radius, point.y()-radius, self.brush_size, self.brush_size)
            self.cursor_item.setVisible(self.scene_.sceneRect().contains(point))
        if self.painting and self.active_mask:
            self.paint_segment(self.last_point, point)
            self.last_point = point
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.painting:
            self.painting = False
            self.last_point = None
            self.strokeFinished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        self.cursor_item.hide()
        super().leaveEvent(event)
