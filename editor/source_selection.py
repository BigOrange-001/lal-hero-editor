"""A movable shield selection and additive/subtractive brushes on source art."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap, QTransform
from PIL import Image, ImageChops
from io import BytesIO
from .compositor_widgets import LayerCanvas, mask_image, png_bytes
from .media import frame_layers


class SourceShieldView(LayerCanvas):
    frameChanged = Signal(tuple)

    def __init__(self, image, quality=6, parent=None):
        super().__init__(parent)
        self.source_size = (image.width(), image.height())
        small = image.scaled(1600, 1600, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation) if max(self.source_size) > 1600 else image
        self.configure((small.width(), small.height()))
        self.picture.setPixmap(QPixmap.fromImage(small))
        self.quality = quality
        self.mode = 'move'
        self.frame_rect = QRectF()
        self.drag_origin = None
        self.drag_rect = None
        self.drag_corner = None
        self.drag_mask = None
        self.drag_modified = False
        self.guide = self.scene_.addPixmap(QPixmap())
        self.guide.setZValue(2.2)
        self.guide.setOpacity(.65)
        self.handles = [self.scene_.addRect(QRectF(), QPen(QColor('#7ef2da'), 0), QColor('#182b33')) for _ in range(4)]
        for handle in self.handles:
            handle.setZValue(3)
        self.set_quality(quality)
        width, height = self.output_size
        ratio = self.native_size[0] / self.native_size[1]
        h = min(height * .78, width * .78 / ratio)
        self.set_rect(QRectF((width-h*ratio)/2, (height-h)/2, h*ratio, h), emit=False)
        self.set_mode('move')

    def set_quality(self, quality):
        self.quality = quality
        info = frame_layers(quality)
        self.native_size = info['native_size']
        self.native = frame_layers(quality, self.native_size)
        pixmap = QPixmap()
        pixmap.loadFromData(self.native['frame'])
        self.guide.setPixmap(pixmap)
        if not self.frame_rect.isEmpty():
            self.update_guide()

    def set_mode(self, mode, brush_size=12):
        self.mode = mode
        self.set_tool('clip' if mode in ('add', 'subtract') else None,
                      mode == 'subtract', brush_size, True)
        self.setDragMode(self.DragMode.ScrollHandDrag if mode == 'pan' else self.DragMode.NoDrag)
        self.setCursor(Qt.CursorShape.CrossCursor if mode in ('add', 'subtract') else Qt.CursorShape.SizeAllCursor)
        self.update_guide()
        self.update_overlay()

    def source_box(self):
        sx, sy = self.source_size[0]/self.output_size[0], self.source_size[1]/self.output_size[1]
        return (max(0., self.frame_rect.left()*sx), max(0., self.frame_rect.top()*sy),
                min(self.source_size[0], self.frame_rect.right()*sx),
                min(self.source_size[1], self.frame_rect.bottom()*sy))

    def set_box(self, box):
        sx, sy = self.output_size[0]/self.source_size[0], self.output_size[1]/self.source_size[1]
        rect = QRectF(box[0]*sx, box[1]*sy, (box[2]-box[0])*sx, (box[3]-box[1])*sy)
        self.set_rect(rect)

    def default_selection(self):
        result = self.blank_mask()
        # Frame pixels are holes in the initial selection. Art is painted above
        # the frame, so including its stroke would hide the original gold rim.
        with Image.open(BytesIO(self.native['clip'])) as clip, Image.open(BytesIO(self.native['frame'])) as frame:
            stroke=frame.getchannel('A').point(lambda v:255 if v else 0)
            selected=ImageChops.multiply(clip.convert('L'),ImageChops.invert(stroke))
            stream=BytesIO();selected.save(stream,format='PNG')
            image = mask_image(stream.getvalue(), self.native_size)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(self.frame_rect, image)
        painter.end()
        return result

    def set_rect(self, rect, emit=True):
        width, height = self.output_size
        ratio = self.native_size[0]/self.native_size[1]
        h = min(max(4., rect.height()), height, width/ratio)
        w = h*ratio
        x = min(max(0., rect.center().x()-w/2), width-w)
        y = min(max(0., rect.center().y()-h/2), height-h)
        target = QRectF(x, y, w, h)
        previous = self.frame_rect
        modified = self.overrides['clip'] and not previous.isEmpty()
        if modified:
            old = self.masks['clip']
            changed = self.blank_mask()
            painter = QPainter(changed)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.translate(target.x(), target.y())
            painter.scale(target.width()/previous.width(), target.height()/previous.height())
            painter.translate(-previous.x(), -previous.y())
            painter.drawImage(0, 0, old)
            painter.end()
            self.masks['clip'] = changed
        self.frame_rect = target
        self.default_clip = self.default_selection()
        if not modified:
            self.masks['clip'] = self.default_clip.copy()
        self.update_guide()
        self.update_overlay()
        if emit:
            self.frameChanged.emit(self.source_box())

    def update_guide(self):
        self.guide.setPos(self.frame_rect.topLeft())
        self.guide.setTransform(QTransform.fromScale(self.frame_rect.width()/self.native_size[0],
                                                    self.frame_rect.height()/self.native_size[1]))
        radius = max(2., 5/max(.01, self.transform().m11()))
        for handle, corner in zip(self.handles, (self.frame_rect.topLeft(), self.frame_rect.topRight(),
                                                self.frame_rect.bottomRight(), self.frame_rect.bottomLeft())):
            handle.setRect(corner.x()-radius, corner.y()-radius, radius*2, radius*2)
            handle.setVisible(self.mode == 'move')

    def update_overlay(self):
        if not hasattr(self, 'frame_rect') or self.frame_rect.isEmpty():
            return
        # A dark veil hides unselected pixels while retaining context to paint
        # additional hair, weapons or effects outside the initial shield.
        mask = self.masks['clip'].convertToFormat(QImage.Format.Format_RGBA8888)
        from PIL import Image
        source = Image.frombytes('RGBA', self.output_size, bytes(mask.constBits()),
                                 'raw', 'RGBA', mask.bytesPerLine())
        alpha = source.getchannel('R').point(lambda value: round((255-value)*.72))
        overlay = Image.new('RGBA', self.output_size, (6, 12, 20, 0))
        overlay.putalpha(alpha)
        raw = overlay.tobytes()
        self.overlay.setPixmap(QPixmap.fromImage(QImage(raw, *self.output_size, self.output_size[0]*4,
                                                       QImage.Format.Format_RGBA8888).copy()))

    def selection_bytes(self):
        return self.mask_bytes('clip', effective=True)

    def reset_selection(self):
        self.overrides['clip'] = False
        self.masks['clip'] = self.default_selection()
        self.update_overlay()
        self.maskChanged.emit('clip')
        self.strokeFinished.emit()

    def mousePressEvent(self, event):
        if self.mode == 'move' and event.button() == Qt.MouseButton.LeftButton:
            point = self.mapToScene(event.position().toPoint())
            corners = (self.frame_rect.topLeft(), self.frame_rect.topRight(), self.frame_rect.bottomRight(), self.frame_rect.bottomLeft())
            radius = 12/max(.01, self.transform().m11())
            corner = next((i for i, p in enumerate(corners) if (p-point).manhattanLength() < radius), None)
            if corner is not None or self.frame_rect.contains(point):
                self.drag_origin, self.drag_rect, self.drag_corner = point, QRectF(self.frame_rect), corner
                self.drag_mask = self.masks['clip'].copy()
                self.drag_modified = self.overrides['clip']
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_origin is not None:
            point = self.mapToScene(event.position().toPoint())
            if self.drag_corner is None:
                target = self.drag_rect.translated(point-self.drag_origin)
            else:
                corners = (self.drag_rect.topLeft(), self.drag_rect.topRight(),
                           self.drag_rect.bottomRight(), self.drag_rect.bottomLeft())
                anchor = corners[(self.drag_corner+2) % 4]
                ratio = self.native_size[0]/self.native_size[1]
                h = max(4., abs(point.y()-anchor.y()), abs(point.x()-anchor.x())/ratio)
                left = anchor.x()-h*ratio if self.drag_corner in (0, 3) else anchor.x()
                top = anchor.y()-h if self.drag_corner in (0, 1) else anchor.y()
                target = QRectF(left, top, h*ratio, h)
            # Transform from the start of the drag, never from the preceding
            # resampled frame; a long drag must not blur a carefully painted edge.
            self.frame_rect = QRectF(self.drag_rect)
            self.masks['clip'] = self.drag_mask
            self.overrides['clip'] = self.drag_modified
            self.set_rect(target)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.drag_origin is not None:
            self.drag_origin = self.drag_rect = self.drag_corner = None
            self.drag_mask = None
            self.strokeFinished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)
