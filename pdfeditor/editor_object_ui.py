"""Editor-only object selection, outline preview and numeric placement panel."""

import fitz
from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QPen
from PyQt5.QtWidgets import (QAction, QDockWidget, QDoubleSpinBox, QFileDialog,
                             QFormLayout, QLabel, QPushButton, QWidget)

from . import editor_objects as model
from .i18n import localize


class ObjectController:
    def __init__(self, tab):
        self.tab = tab
        self.active = False
        self.selected = None
        self.items = []
        self.context = None
        self.drag = None
        self.preview = None
        self.action = QAction(localize("Select object", "개체 선택"), tab)
        self.action.setCheckable(True)
        self.action.triggered.connect(self.activate)
        self.rectangle_action = QAction(localize("Add rectangle", "사각형 추가"), tab)
        self.rectangle_action.triggered.connect(lambda: self.add("rectangle"))
        self.image_action = QAction(localize("Place image…", "이미지 배치…"), tab)
        self.image_action.triggered.connect(self.add_image)
        self.dock = QDockWidget(localize("Object properties", "개체 속성"), tab)
        self.dock.setObjectName("editorObjectProperties")
        self.dock.setAllowedAreas(Qt.RightDockWidgetArea)
        panel = QWidget()
        layout = QFormLayout(panel)
        self.label = QLabel(localize("Select an sPDF object.", "sPDF에서 추가한 개체를 선택하세요."))
        self.label.setWordWrap(True)
        layout.addRow(self.label)
        self.fields = []
        for title in ("X (mm)", "Y (mm)", localize("Width (mm)", "너비 (mm)"),
                      localize("Height (mm)", "높이 (mm)")):
            field = QDoubleSpinBox()
            field.setDecimals(3)
            field.setRange(-100000, 100000)
            field.setKeyboardTracking(False)
            layout.addRow(title, field)
            self.fields.append(field)
        for field in self.fields[2:]:
            field.setMinimum(.1)
        self.apply_button = QPushButton(localize("Apply", "적용"))
        self.apply_button.clicked.connect(self.apply)
        layout.addRow(self.apply_button)
        self.delete_button = QPushButton(localize("Delete object", "개체 삭제"))
        self.delete_button.clicked.connect(self.delete)
        layout.addRow(self.delete_button)
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
        self.active = False
        self.action.setChecked(False)
        self.cancel()
        self.tab.view.viewport().update()

    def refresh(self):
        tab = self.tab
        context = (id(tab.doc), tab.page_index,
                   getattr(tab.doc, "_render_generation", -1))
        if context != self.context:
            self.cancel()
            if self.context is None or context[:2] != self.context[:2]:
                self.selected = None
            self.context = context
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
        else:
            self.label.setText(localize("Select an sPDF object.", "sPDF에서 추가한 개체를 선택하세요."))
        tab.view.viewport().update()

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
        self.commit(fitz.Rect(x, y, x + w, y + h))

    def commit(self, rect):
        item = self.current()
        if item and list(rect) != item["rect"] and not self.tab.read_only:
            self.tab._perform_text_edit(lambda: model.transform(
                self.tab.doc, self.tab.page_index, item["id"], rect))
        self.refresh()

    def delete(self):
        item = self.current()
        if item and not self.tab.read_only:
            self.tab._perform_text_edit(lambda: model.delete(
                self.tab.doc, self.tab.page_index, item["id"]))
        self.refresh()

    def cancel(self):
        self.drag = None
        self.preview = None

    def mouse(self, name, event):
        if not self.active or self.tab.doc is None or self.tab.read_only:
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
            self.refresh()
            item = self.current()
            tolerance = 7 / max(.1, view.zoom)
            resize = item and abs(point.x - item["rect"][2]) <= tolerance and abs(point.y - item["rect"][3]) <= tolerance
            if not resize:
                item = next((x for x in reversed(self.items) if point in fitz.Rect(x["rect"])), None)
            self.selected = item["id"] if item else None
            self.refresh()
            if item:
                self.drag = (point, fitz.Rect(item["rect"]), bool(resize))
            view.setFocus()
        elif name == "mouseMoveEvent" and self.drag:
            start, original, resize = self.drag
            dx, dy = point.x - start.x, point.y - start.y
            self.preview = (fitz.Rect(original.x0, original.y0,
                                     max(original.x0 + .3, original.x1 + dx),
                                     max(original.y0 + .3, original.y1 + dy)) if resize else
                            fitz.Rect(original.x0 + dx, original.y0 + dy,
                                      original.x1 + dx, original.y1 + dy))
            view.viewport().update()
        elif name == "mouseReleaseEvent":
            rect = self.preview
            self.cancel()
            if rect is not None:
                self.commit(rect)
        return True

    def outlines(self):
        item = self.current()
        if not self.active or not item or self.tab.doc is None:
            return []
        page = self.tab.doc._doc[self.tab.page_index]
        rect = self.preview if self.preview is not None else fitz.Rect(item["rect"])
        display = rect * page.rotation_matrix
        corner = fitz.Point(rect.x1, rect.y1) * page.rotation_matrix
        radius = 3 / max(.1, self.tab.view.zoom)
        return [QRectF(display.x0, display.y0, display.width, display.height),
                QRectF(corner.x - radius, corner.y - radius, radius * 2, radius * 2)]

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
