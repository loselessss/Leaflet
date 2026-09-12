"""In-page line editing with a small non-modal typography palette."""

from PyQt5.QtCore import Qt, QEvent, QObject, QPointF, QRectF
from PyQt5.QtGui import QColor, QFont, QFontDatabase
from PyQt5.QtWidgets import (QLineEdit, QDialog, QFormLayout, QVBoxLayout,
    QComboBox, QDoubleSpinBox, QPushButton, QColorDialog, QFileDialog,
    QDialogButtonBox, QLabel)

from .i18n import localize


class LineInput(QLineEdit):
    def event(self, event):
        if event.type() == QEvent.ShortcutOverride and event.modifiers() & Qt.ControlModifier:
            if event.key() in (Qt.Key_Z, Qt.Key_Y, Qt.Key_A, Qt.Key_C, Qt.Key_V, Qt.Key_X):
                event.accept()
                return True
        return super().event(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.session.cancel()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.session.commit()
            return
        super().keyPressEvent(event)


class InlineTextSession(QObject):
    def __init__(self, host, point, span=None):
        super().__init__(host)
        self.host, self.document, self.page = host, host.doc, host.page_index
        self.span = span
        self.point = tuple(span['origin']) if span else (point.x(), point.y())
        self.bbox = tuple(span['bbox']) if span else (
            point.x(), point.y() - 12, point.x() + 140, point.y() + 5)
        self.scanned = self.document.is_scanned_area(self.page, self.bbox)
        self.bg, sampled_fg = self.document.sample_bg_fg(self.page, self.bbox)
        color = sampled_fg if self.scanned else (span['rgb'] if span else (0, 0, 0))
        self.color = QColor.fromRgbF(*color)
        self.initial_color = color
        self.initial_text = span['text'] if span else ''
        self.initial_size = span['size'] if span else 11
        self.fontfile = None
        self.font_id = -1
        self.done = False
        self.input = LineInput(self.initial_text, host.view.viewport())
        self.input.setAttribute(Qt.WA_NativeWindow)
        self.input.session = self
        self.input.setAccessibleName(localize('Edit text on page', '페이지에서 텍스트 편집'))
        self.input.setTextMargins(0, 0, 0, 0)
        self.palette = QDialog(host, Qt.Tool)
        self.palette.setWindowTitle(localize('Text properties', '글자 속성'))
        layout = QVBoxLayout(self.palette)
        form = QFormLayout()
        self.font = QComboBox()
        for label, name, family in [
                (localize('Default (Korean)', '기본 (한글 지원)'), 'korea', 'Malgun Gothic'),
                ('Helvetica', 'helv', 'Arial'), ('Times', 'tiro', 'Times New Roman'),
                ('Courier', 'cour', 'Courier New')]:
            self.font.addItem(label, (name, family))
        form.addRow(localize('Font', '글꼴'), self.font)
        font_file = QPushButton(localize('Choose font file…', '글꼴 파일 선택…'))
        font_file.clicked.connect(self.choose_font)
        form.addRow('', font_file)
        self.size = QDoubleSpinBox()
        self.size.setRange(1, 1000)
        self.size.setDecimals(1)
        self.size.setSuffix(' pt')
        self.size.setValue(self.initial_size)
        form.addRow(localize('Size', '크기'), self.size)
        self.color_button = QPushButton(self.color.name())
        self.color_button.clicked.connect(self.choose_color)
        form.addRow(localize('Color', '색상'), self.color_button)
        layout.addLayout(form)
        note = QLabel(localize(
            'Enter: apply · Esc: cancel\nOne line at a time. Replacement fonts may differ.',
            'Enter: 적용 · Esc: 취소\n한 줄씩 수정합니다. 대체 글꼴은 원본과 다를 수 있습니다.'))
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Apply).setText(localize('Apply', '적용'))
        buttons.button(QDialogButtonBox.Cancel).setText(localize('Cancel', '취소'))
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self.commit)
        buttons.rejected.connect(self.cancel)
        layout.addWidget(buttons)
        self.palette.rejected.connect(self.cancel)
        self.font.currentIndexChanged.connect(self.update_preview)
        self.size.valueChanged.connect(self.update_preview)
        host.view.viewport().installEventFilter(self)
        host.view.zoom_changed.connect(self.update_preview)
        host.view.viewport_changed.connect(self.update_preview)
        self.update_preview()
        self.palette.show()
        self.palette.move(host.mapToGlobal(host.rect().topRight()) - self.palette.rect().topRight())
        self.input.show()
        self.input.setFocus()
        self.input.selectAll()

    def choose_font(self):
        path, _ = QFileDialog.getOpenFileName(self.palette,
            localize('Choose font', '글꼴 선택'), '', 'Fonts (*.ttf *.otf)')
        if not path:
            return
        font_id = QFontDatabase.addApplicationFont(path)
        families = QFontDatabase.applicationFontFamilies(font_id)
        if not families:
            return
        if self.font_id >= 0:
            QFontDatabase.removeApplicationFont(self.font_id)
        self.font_id, self.fontfile = font_id, path
        if self.font.count() > 4:
            self.font.removeItem(4)
        self.font.addItem(families[0], ('spdfuser', families[0]))
        self.font.setCurrentIndex(4)

    def choose_color(self):
        color = QColorDialog.getColor(self.color, self.palette)
        if color.isValid():
            self.color = color
            self.color_button.setText(color.name())
            self.update_preview()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Resize:
            self.update_preview()
        return False

    def update_preview(self, *_):
        if self.done:
            return
        view = self.host.view
        canvas = view.canvas
        z = view.zoom
        x, y, right, bottom = self.bbox
        transforms = getattr(view, '_page_transforms', None)
        if transforms is not None and self.page in transforms:
            rect = transforms[self.page].mapRect(QRectF(x, y, right-x, bottom-y))
            rect = view.mapFromScene(rect).boundingRect()
            left, top, width, height = rect.x(), rect.y(), rect.width(), rect.height()
        else:
            origin = canvas.active_page_rect().topLeft()
            point = canvas.mapTo(view.viewport(), (origin + QPointF(x*z, y*z)).toPoint())
            left, top, width, height = point.x(), point.y(), (right-x)*z, (bottom-y)*z
        font = QFont(self.font.currentData()[1])
        font.setPixelSize(max(1, round(self.size.value() * z)))
        self.input.setFont(font)
        self.input.setStyleSheet('QLineEdit { background: %s; color: %s; border: 1px solid #4389d6; }' %
            (QColor.fromRgbF(*self.bg).name(), self.color.name()))
        width = min(max(width + 8, 180), max(40, view.viewport().width() - left))
        self.input.setGeometry(round(left), round(top), round(width),
            max(round(height), self.input.sizeHint().height()))
        self.input.raise_()

    def cancel(self):
        self.close()

    def close(self):
        if self.done:
            return
        self.done = True
        self.host.view.viewport().removeEventFilter(self)
        self.host.view.zoom_changed.disconnect(self.update_preview)
        self.host.view.viewport_changed.disconnect(self.update_preview)
        self.input.hide()
        self.palette.hide()
        self.input.deleteLater()
        self.palette.deleteLater()
        if self.font_id >= 0:
            QFontDatabase.removeApplicationFont(self.font_id)
        self.host._inline_text = None
        self.deleteLater()

    def commit(self):
        if self.done:
            return True
        host = self.host
        if host.doc is not self.document or host.page_index != self.page:
            self.close()
            return False
        text, size = self.input.text(), self.size.value()
        rgb = (self.color.redF(), self.color.greenF(), self.color.blueF())
        name = self.font.currentData()[0]
        options = dict(fontname=name, fontfile=self.fontfile if name == 'spdfuser' else None)
        unchanged = (text == self.initial_text and abs(size-self.initial_size) < .05
            and name == 'korea' and all(abs(a-b) < 1/255 for a,b in zip(rgb,self.initial_color)))
        if unchanged or (self.span is None and not text.strip()):
            self.close()
            return True
        if self.span:
            if self.scanned:
                operation = lambda: host.doc.replace_scanned_text(self.page, self.bbox,
                    self.point, text, size, bg=self.bg, fg=rgb, **options)
            else:
                operation = lambda: host.doc.replace_span(self.page, self.bbox,
                    self.point, text, size, rgb, **options)
        else:
            operation = lambda: host.doc.add_text_box(self.page, self.point, text,
                size=size, bg=self.bg if self.scanned else None, fg=rgb, **options)
        # Rendering refreshes clear old editing overlays. Keep this session
        # available for correction if the PDF operation is rolled back.
        host._inline_text = None
        success = host._perform_text_edit(operation)
        if success:
            self.close()
        else:
            host._inline_text = self
            self.input.setFocus()
        return success
