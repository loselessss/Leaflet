"""Editor-only object selection, outline preview and numeric placement panel."""

import pymupdf as fitz
from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QPen
from PyQt5.QtWidgets import (QAction, QCheckBox, QDockWidget, QDoubleSpinBox, QFileDialog,
                             QFormLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton,
                             QVBoxLayout, QWidget)

from . import editor_objects as model
from .i18n import localize
from .icons import fluent_icon


class ObjectController:
    def __init__(self, tab):
        self.tab = tab
        self.active = False
        self.auto_selected = False
        self._consume_release = False
        self.selected = None
        self.items = []
        self.context = None
        self.drag = None
        self.preview = None
        self.hovered = None
        self._temporary_mode = None
        self._ratios = {}
        self.action = QAction(localize("Select object", "개체 선택"), tab)
        self.action.setIcon(fluent_icon("object_select"))
        self.action.setCheckable(True)
        self.action.triggered.connect(self.activate)
        self.rectangle_action = QAction(localize("Add rectangle", "사각형 추가"), tab)
        self.rectangle_action.setIcon(fluent_icon("rectangle"))
        self.rectangle_action.triggered.connect(lambda: self.add("rectangle"))
        self.image_action = QAction(localize("Place image…", "이미지 배치…"), tab)
        self.image_action.setIcon(fluent_icon("image"))
        self.image_action.triggered.connect(self.add_image)
        self.dock = QDockWidget(localize("Object properties", "개체 속성"), tab)
        self.dock.setObjectName("editorObjectProperties")
        self.dock.setAllowedAreas(Qt.RightDockWidgetArea)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        self.label = QLabel(localize("Select an image or a Leaflet object.", "이미지 또는 Leaflet에서 추가한 개체를 선택하세요."))
        self.label.setWordWrap(True)
        self.label.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.label)
        self.geometry_group = QGroupBox(localize("Position and size", "위치와 크기"))
        geometry = QFormLayout(self.geometry_group)
        layout.addWidget(self.geometry_group)
        self.fields = []
        for title in ("X (mm)", "Y (mm)", localize("Width (mm)", "너비 (mm)"),
                      localize("Height (mm)", "높이 (mm)")):
            field = QDoubleSpinBox()
            field.setDecimals(3)
            field.setRange(-100000, 100000)
            field.setKeyboardTracking(False)
            geometry.addRow(title, field)
            self.fields.append(field)
        for field in self.fields[2:]:
            field.setMinimum(.1)
        self.ratio_lock = QCheckBox(localize("Keep image proportions", "이미지 비율 유지"))
        self.ratio_lock.toggled.connect(self._set_ratio_lock)
        geometry.addRow(self.ratio_lock)
        self.measurement = QLabel()
        self.measurement.setWordWrap(True)
        layout.addWidget(self.measurement)
        buttons = QHBoxLayout()
        layout.addLayout(buttons)
        self.apply_button = QPushButton(localize("Apply", "적용"))
        self.apply_button.clicked.connect(self.apply)
        buttons.addWidget(self.apply_button)
        self.delete_button = QPushButton(localize("Delete object", "개체 삭제"))
        self.delete_button.clicked.connect(self.delete)
        buttons.addWidget(self.delete_button)
        layout.addStretch()
        self.dock.setWidget(panel)
        tab.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.hide()
        self.refresh()

    def activate(self, checked=True):
        if not checked:
            self.deactivate()
            return
        if self.tab.doc is None or self.tab.read_only:
            self.action.setChecked(False)
            return
        self.tab.set_edit_mode(False)
        self.tab.cancel_note_mode()
        self.tab.set_interaction_mode("select", announce=False)
        self.active = True
        self.action.setChecked(True)
        self.dock.show()
        self.refresh()

    def deactivate(self):
        self.restore_hand()
        self.active = False
        self.auto_selected = False
        self.action.setChecked(False)
        self.cancel()
        self.hovered = None
        self.tab.view.viewport().unsetCursor()
        self.tab.view.viewport().update()

    def refresh(self):
        tab = self.tab
        context = (id(tab.doc), tab.page_index,
                   getattr(tab.doc, "_render_generation", -1))
        changed = context != self.context
        if changed:
            self.cancel()
            self.hovered = None
            self.tab.view.viewport().unsetCursor()
            if (self.context is None or context[:2] != self.context[:2]
                    or (self.selected or "").startswith("existing-image:")):
                self.selected = None
                self.auto_selected = False
            self.context = context
        if changed:
            self.items = model.objects(tab.doc, tab.page_index) if tab.doc is not None else []
        item = self.current()
        editable = tab.doc is not None and not tab.read_only
        for action in (self.action, self.rectangle_action, self.image_action):
            action.setEnabled(editable)
        for widget in (*self.fields, self.apply_button, self.delete_button):
            widget.setEnabled(editable and item is not None)
        if item:
            rect = fitz.Rect(item["rect"])
            self.label.setText(localize("Rectangle", "사각형") if item["kind"] == "rectangle"
                               else localize("Image", "이미지"))
            for field, value in zip(self.fields, (rect.x0, rect.y0, rect.width, rect.height)):
                field.setValue(value * 25.4 / 72)
            self.ratio_lock.blockSignals(True)
            self.ratio_lock.setChecked(self._ratios.get(item["id"], True))
            self.ratio_lock.blockSignals(False)
            self._show_measurement(rect)
        else:
            self.label.setText(localize("Click an image or object. Click text to edit it with the text palette.", "이미지나 개체를 클릭하세요. 글자를 클릭하면 문자 팔레트로 편집합니다."))
            if tab.doc is None:
                self.measurement.clear()
            else:
                page_rect = tab.doc._doc[tab.page_index].rect
                self.measurement.setText(localize("Page", "페이지") + " %d / %d\n%.2f × %.2f mm" %
                                         (tab.page_index + 1, tab.doc.page_count,
                                          page_rect.width * 25.4 / 72, page_rect.height * 25.4 / 72))
        self.geometry_group.setVisible(item is not None)
        self.apply_button.setVisible(item is not None)
        self.delete_button.setVisible(item is not None)
        self.ratio_lock.setVisible(bool(item and item["kind"] == "image"))
        self.ratio_lock.setEnabled(editable)
        tab.view.viewport().update()

    def _set_ratio_lock(self, checked):
        if self.selected:
            self._ratios[self.selected] = checked

    def _show_measurement(self, rect):
        self.measurement.setText("X %.2f · Y %.2f\n%.2f × %.2f mm" %
                                 tuple(value * 25.4 / 72 for value in
                                       (rect.x0, rect.y0, rect.width, rect.height)))

    def current(self):
        return next((item for item in self.items if item["id"] == self.selected), None)

    def add(self, kind, image=None, aspect=1.5):
        tab = self.tab
        if tab.doc is None or tab.read_only:
            return
        page = tab.doc._doc[tab.page_index]
        bounds = page.rect * page.derotation_matrix
        width = min(160, bounds.width * .5)
        height = min(width / aspect, bounds.height * .5)
        width = height * aspect
        rect = fitz.Rect(bounds.x0 + (bounds.width - width) / 2,
                         bounds.y0 + (bounds.height - height) / 2, 0, 0)
        rect.x1, rect.y1 = rect.x0 + width, rect.y0 + height
        result = []
        if tab._perform_text_edit(lambda: result.append(
                model.create(tab.doc, tab.page_index, kind, rect, image=image))):
            self.selected = result[0]
            self.activate()

    def add_image(self):
        if self.tab.doc is None or self.tab.read_only:
            return
        path, _ = QFileDialog.getOpenFileName(self.tab, localize("Place image", "이미지 배치"),
                                             "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        from PyQt5.QtWidgets import QMessageBox
        try:
            import os
            if os.path.getsize(path) > 32 * 1024 * 1024:
                raise ValueError(localize("Choose an image smaller than 32 MB.", "32 MB보다 작은 이미지를 선택하세요."))
            with open(path, "rb") as source:
                data = source.read()
            info = fitz.image_profile(data)
            if not info or info["width"] * info["height"] > 40_000_000:
                raise ValueError(localize("Image is invalid or too large.", "이미지가 올바르지 않거나 너무 큽니다."))
            self.add("image", data, info["width"] / info["height"])
        except (OSError, ValueError, RuntimeError) as error:
            QMessageBox.warning(self.tab, localize("Image error", "이미지 오류"), str(error))

    def apply(self):
        item = self.current()
        if not item or self.tab.read_only:
            return
        old = fitz.Rect(item["rect"])
        # Preserve full precision for fields the user has not changed.
        values = [old.x0, old.y0, old.width, old.height]
        for index, field in enumerate(self.fields):
            if abs(field.value() - round(values[index] * 25.4 / 72, 3)) > .0001:
                values[index] = field.value() * 72 / 25.4
        x, y, w, h = values
        if item["kind"] == "image" and self.ratio_lock.isChecked():
            if w != old.width:
                h = w * old.height / old.width
            elif h != old.height:
                w = h * old.width / old.height
            scale = max(1, .3 / w, .3 / h)
            w, h = w * scale, h * scale
        self.commit(fitz.Rect(x, y, x + w, y + h))

    def commit(self, rect):
        item = self.current()
        if item and list(rect) != item["rect"] and not self.tab.read_only:
            result = []
            if self.tab._perform_text_edit(lambda: result.append(model.transform(
                    self.tab.doc, self.tab.page_index, item["id"], rect))):
                if item["id"] in self._ratios:
                    self._ratios[result[0]] = self._ratios.pop(item["id"])
                self.selected = result[0]
                self.auto_selected = not self.active and self._automatic_enabled()
        self.refresh()

    def delete(self):
        item = self.current()
        if item and not self.tab.read_only:
            if self.tab._perform_text_edit(lambda: model.delete(
                    self.tab.doc, self.tab.page_index, item["id"])):
                self.selected = None
        self.refresh()

    def cancel(self):
        self.drag = None
        self.preview = None

    def restore_hand(self):
        if self._temporary_mode is not None:
            canvas = self.tab.view.canvas
            canvas.set_interaction_mode(self._temporary_mode)
            self._temporary_mode = None

    def _handles(self, rect):
        return [(fitz.Point(rect.x0 + rect.width * x, rect.y0 + rect.height * y), (x, y))
                for x, y in ((0, 0), (.5, 0), (1, 0), (1, .5), (1, 1), (.5, 1), (0, 1), (0, .5))]

    def _handle_at(self, point, item):
        if not item or not (self.active or self.auto_selected):
            return None
        tolerance = 7 / max(.1, self.tab.view.zoom)
        return next((handle for center, handle in self._handles(fitz.Rect(item["rect"]))
                     if abs(point.x - center.x) <= tolerance and abs(point.y - center.y) <= tolerance), None)

    def _cursor(self, handle=None, item=None):
        cursor = Qt.OpenHandCursor if item else Qt.ArrowCursor
        if handle is not None:
            x, y = handle
            rotation = self.tab.doc._doc[self.tab.page_index].rotation
            if x == .5 or y == .5:
                horizontal = y == .5
                if rotation in (90, 270):
                    horizontal = not horizontal
                cursor = Qt.SizeHorCursor if horizontal else Qt.SizeVerCursor
            else:
                forward = x == y
                if rotation in (90, 270):
                    forward = not forward
                cursor = Qt.SizeFDiagCursor if forward else Qt.SizeBDiagCursor
        self.tab.view.viewport().setCursor(cursor)

    def key(self, event, release=False):
        view = self.tab.view
        if release and event.key() == Qt.Key_Space and self._temporary_mode is not None:
            if not event.isAutoRepeat():
                self.restore_hand()
            return True
        if release or self.tab.doc is None or self.tab.read_only or not view.hasFocus():
            return False
        if event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier):
            return False
        if event.key() == Qt.Key_Space and (self.active or self._automatic_enabled()):
            if self.drag or getattr(self.tab, "_inline_text", None):
                return False
            if self._temporary_mode is None:
                self._temporary_mode = view.canvas.interaction_mode
                view.canvas.set_interaction_mode("hand")
            return True
        if not (self.active or self.auto_selected):
            return False
        if event.key() == Qt.Key_Escape:
            if self.drag or self.preview is not None:
                self.cancel()
            else:
                self.selected = None
                self.auto_selected = False
            self.refresh()
            return True
        item = self.current()
        if not item:
            return False
        if event.key() == Qt.Key_Delete:
            self.delete()
            return True
        directions = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}
        if event.key() in directions and not self.drag:
            step = 10 if event.modifiers() & Qt.ShiftModifier else 1
            dx, dy = directions[event.key()]
            page = self.tab.doc._doc[self.tab.page_index]
            delta = fitz.Point(dx * step, dy * step) * page.derotation_matrix - fitz.Point(0, 0) * page.derotation_matrix
            rect = fitz.Rect(item["rect"])
            self.commit(fitz.Rect(rect.x0 + delta.x, rect.y0 + delta.y, rect.x1 + delta.x, rect.y1 + delta.y))
            return True
        return False

    def _automatic_enabled(self):
        return (self.tab.view.canvas.interaction_mode == "select"
                and not self.tab._note_mode)

    def mouse(self, name, event):
        if self._temporary_mode is not None:
            return False
        automatic = not self.active and self._automatic_enabled()
        if (not self.active and not automatic) or self.tab.doc is None or self.tab.read_only:
            return False
        if event.button() not in (Qt.LeftButton, Qt.NoButton):
            return False
        view = self.tab.view
        page_index = self.tab.page_index
        transform = view._page_transforms.get(page_index)
        if transform is None:
            return False
        inverse, valid = transform.inverted()
        if not valid:
            return False
        point = inverse.map(view.mapToScene(event.pos()))
        page = self.tab.doc._doc[page_index]
        point = fitz.Point(point.x(), point.y()) * page.derotation_matrix
        if name == "mousePressEvent":
            self._consume_release = False
            self.refresh()
            item = self.current()
            resize = self._handle_at(point, item)
            # Text remains clickable even over a full-page scanned image.
            if automatic and resize is None and self.tab._span_at(QPointF(point.x, point.y)):
                self.selected = None
                self.auto_selected = False
                self.refresh()
                return False
            if resize is None:
                item = next((x for x in reversed(self.items) if point in fitz.Rect(x["rect"])), None)
            if automatic and item:
                self._consume_release = True
                if not self.tab._commit_inline_text():
                    return True
                self.refresh()
                item = self.current() if resize is not None else next(
                    (x for x in reversed(self.items) if point in fitz.Rect(x["rect"])), None)
            self.selected = item["id"] if item else None
            self.auto_selected = automatic and item is not None
            if self.auto_selected:
                self.dock.show()
            self.refresh()
            if item:
                self.drag = (point, fitz.Rect(item["rect"]), resize)
                self._consume_release = True
            elif automatic:
                return False
            view.setFocus()
        elif name == "mouseMoveEvent" and self.drag:
            start, original, resize = self.drag
            dx, dy = point.x - start.x, point.y - start.y
            if resize is None:
                if event.modifiers() & Qt.ShiftModifier:
                    # Constrain in screen axes, including rotated pages.
                    delta = fitz.Point(dx, dy) * page.rotation_matrix - fitz.Point(0, 0) * page.rotation_matrix
                    delta = fitz.Point(delta.x, 0) if abs(delta.x) >= abs(delta.y) else fitz.Point(0, delta.y)
                    delta = delta * page.derotation_matrix - fitz.Point(0, 0) * page.derotation_matrix
                    dx, dy = delta.x, delta.y
                self.preview = fitz.Rect(original.x0 + dx, original.y0 + dy, original.x1 + dx, original.y1 + dy)
                view.viewport().setCursor(Qt.ClosedHandCursor)
            else:
                x, y = resize
                width = max(.3, original.width + dx * (1 if x == 1 else -1)) if x != .5 else original.width
                height = max(.3, original.height + dy * (1 if y == 1 else -1)) if y != .5 else original.height
                if self.current()["kind"] == "image" and self.ratio_lock.isChecked():
                    if x == .5 or (y != .5 and abs(height / original.height - 1) > abs(width / original.width - 1)):
                        width = height * original.width / original.height
                    else:
                        height = width * original.height / original.width
                    scale = max(1, .3 / width, .3 / height)
                    width, height = width * scale, height * scale
                left = original.x1 - width if x == 0 else (original.x0 + (original.width - width) / 2 if x == .5 else original.x0)
                top = original.y1 - height if y == 0 else (original.y0 + (original.height - height) / 2 if y == .5 else original.y0)
                self.preview = fitz.Rect(left, top, left + width, top + height)
                self._cursor(resize)
            self._show_measurement(self.preview)
            view.viewport().update()
        elif name == "mouseMoveEvent":
            if event.buttons() != Qt.NoButton:
                self.hovered = None
                view.viewport().unsetCursor()
                view.viewport().update()
                return False
            item = self.current()
            handle = self._handle_at(point, item)
            hovered = next((x for x in reversed(self.items) if point in fitz.Rect(x["rect"])), None)
            if automatic and handle is None and self.tab._span_at(QPointF(point.x, point.y)):
                hovered = None
            self.hovered = hovered["id"] if hovered else None
            self._cursor(handle, hovered)
            view.viewport().update()
            return handle is not None or hovered is not None
        elif name == "mouseReleaseEvent":
            if not self._consume_release and automatic:
                return False
            self._consume_release = False
            rect = self.preview
            self.cancel()
            if rect is not None:
                self.commit(rect)
            self._cursor(item=self.current())
        elif name == "mouseDoubleClickEvent" and self.auto_selected:
            item = self.current()
            return item is not None and point in fitz.Rect(item["rect"])
        return self.active or self.drag is not None or name == "mouseReleaseEvent"

    def outlines(self):
        item = self.current()
        if not (self.active or self.auto_selected) or not item or self.tab.doc is None:
            return self.hover_outline()
        page = self.tab.doc._doc[self.tab.page_index]
        rect = self.preview if self.preview is not None else fitz.Rect(item["rect"])
        display = rect * page.rotation_matrix
        radius = 3 / max(.1, self.tab.view.zoom)
        corners = [center * page.rotation_matrix for center, _ in self._handles(rect)]
        return self.hover_outline() + [QRectF(display.x0, display.y0, display.width, display.height)] + [
            QRectF(corner.x - radius, corner.y - radius, radius * 2, radius * 2) for corner in corners]

    def hover_outline(self):
        item = next((item for item in self.items if item["id"] == self.hovered and item["id"] != self.selected), None)
        if item is None or self.tab.doc is None:
            return []
        rect = fitz.Rect(item["rect"]) * self.tab.doc._doc[self.tab.page_index].rotation_matrix
        return [QRectF(rect.x0, rect.y0, rect.width, rect.height)]

    def paint(self, painter):
        painter.save()
        painter.setBrush(Qt.NoBrush)
        pen = QPen(QColor("#2563eb"))
        pen.setWidthF(1.5 / max(.1, self.tab.view.zoom))
        painter.setPen(pen)
        for rect in self.outlines():
            painter.drawRect(rect)
        painter.restore()

    def paint_native(self, surface):
        for rect in self.outlines():
            surface.stroke_rect(rect.left(), rect.top(), rect.right(), rect.bottom(),
                                0xff2563eb, 1.5 / max(.1, self.tab.view.zoom))
