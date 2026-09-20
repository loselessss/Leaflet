"""Inline multiline editor using the existing typography palette and history."""

import fitz
from PyQt5.QtCore import Qt, QEvent, QTimer, QRectF
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QPlainTextEdit, QDoubleSpinBox, QComboBox, QCheckBox, QLabel, QPushButton

from .inline_text import InlineTextSession
from .i18n import localize
from .text_regions import layout_region


class ParagraphInput(QPlainTextEdit):
    def __init__(self, text, parent):
        super().__init__(parent)
        self.setPlainText(text)

    def text(self):
        return self.toPlainText()

    def setText(self, text):
        self.setPlainText(text)

    def setTextMargins(self, *args):
        self.document().setDocumentMargin(0)

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
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ControlModifier:
            self.session.commit()
            return
        super().keyPressEvent(event)


class ParagraphTextSession(InlineTextSession):
    def make_input(self, text, parent):
        return ParagraphInput(text, parent)

    def __init__(self, host, point, region):
        self.ready = False
        self.region = region
        super().__init__(host, point, region)
        self.palette.setWindowTitle(localize('Text box properties', '문장·문단 속성'))
        original_font = region['font'].lower()
        self.initial_font = (1 if original_font in ('helvetica', 'arialmt', 'arial')
                             else 2 if original_font in ('times-roman', 'timesnewromanpsmt')
                             else 3 if original_font == 'courier' else 0)
        self.font.setCurrentIndex(self.initial_font)
        self.width = QDoubleSpinBox()
        self.height = QDoubleSpinBox()
        for control, value, label in (
                (self.width, self.bbox[2]-self.bbox[0], localize('Box width', '상자 너비')),
                (self.height, self.bbox[3]-self.bbox[1], localize('Box height', '상자 높이'))):
            control.setRange(.1, 10000)
            control.setDecimals(2)
            control.setSuffix(' mm')
            control.setValue(value * 25.4 / 72)
            self.form.addRow(label, control)
            control.valueChanged.connect(self.update_preview)
        fit_height = QPushButton(localize('Fit box height to text', '글에 맞춰 상자 높이 늘리기'))
        fit_height.clicked.connect(self.fit_height)
        self.form.addRow(fit_height)
        self.alignment = QComboBox()
        self.alignment.addItems([localize('Left', '왼쪽'), localize('Center', '가운데'),
                                 localize('Right', '오른쪽')])
        self.form.addRow(localize('Alignment', '정렬'), self.alignment)
        self.leading = QDoubleSpinBox()
        self.leading.setRange(1, 3)
        self.leading.setSingleStep(.1)
        self.leading.setValue(1.2)
        self.form.addRow(localize('Line spacing', '줄 간격'), self.leading)
        self.unify = QCheckBox(localize('Use one font, size and color for this selection',
                                       '선택한 글의 글꼴·크기·색상을 통일'))
        self.unify.setVisible(region['mixed'])
        self.form.addRow(self.unify)
        self.preview = QLabel()
        self.preview.setFixedSize(340, 140)
        self.preview.setAlignment(Qt.AlignCenter)
        self.form.addRow(localize('PDF output preview', 'PDF 출력 미리보기'), self.preview)
        self.initial_box = (self.width.value(), self.height.value())
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self.validate)
        self.input.textChanged.connect(self.update_preview)
        self.alignment.currentIndexChanged.connect(self.update_preview)
        self.leading.valueChanged.connect(self.update_preview)
        self.unify.toggled.connect(self.update_preview)
        self.ready = True
        self.update_preview()

    def options(self):
        name = self.font.currentData()[0]
        return dict(box=self.bbox, fontname=name,
                    fontfile=self.fontfile if name == 'spdfuser' else None,
                    align=self.alignment.currentIndex(), lineheight=self.leading.value())

    def unchanged(self):
        rgb = self.rgb()
        return (self.input.text() == self.initial_text
                and abs(self.size.value()-self.initial_size) < .05
                and self.font.currentIndex() == self.initial_font
                and all(abs(a-b) < 1/255 for a, b in zip(rgb, self.initial_color))
                and (self.width.value(), self.height.value()) == self.initial_box
                and self.alignment.currentIndex() == 0 and self.leading.value() == 1.2)

    def rgb(self):
        return self.color.redF(), self.color.greenF(), self.color.blueF()

    def fit_height(self):
        """Only grow the box after an explicit request, staying inside the page."""
        options = self.options()
        x, y, right, bottom = self.bbox
        page = self.document._doc[self.page]
        maximum = (page.rect * page.derotation_matrix).y1
        def fits(edge):
            options['box'] = (x, y, right, edge)
            layout_region(self.document, self.page, self.region, self.input.text(),
                          self.size.value(), self.rgb(), **options)
        try:
            fits(maximum)
        except Exception as error:
            self.note.setText(str(error))
            return
        low, high = bottom, maximum
        for _ in range(14):
            mid = (low+high)/2
            try:
                fits(mid)
                high = mid
            except ValueError:
                low = mid
        import math
        self.height.setValue(math.ceil((high-y)*25.4/72*100)/100)

    def validate(self):
        if self.done:
            return False
        instructions = localize('Enter: new line · Ctrl+Enter: apply · Esc: cancel',
                                'Enter: 줄 바꿈 · Ctrl+Enter: 적용 · Esc: 취소')
        try:
            if not self.unchanged():
                if self.region['mixed'] and not self.unify.isChecked():
                    raise ValueError(localize('Mixed formatting. Confirm formatting unification first.',
                                             '여러 서식이 섞여 있습니다. 서식 통일에 체크해 주세요.'))
                drawing = layout_region(self.document, self.page, self.region, self.input.text(),
                                        self.size.value(), self.rgb(), **self.options())
                if drawing:
                    with fitz.open(stream=drawing, filetype='pdf') as pdf:
                        rect = fitz.Rect(self.bbox)
                        scale = min(2, 340/rect.width, 140/rect.height)
                        pix = pdf[0].get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect)
                        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
                        self.preview.setPixmap(QPixmap.fromImage(image))
                else:
                    self.preview.clear()
            else:
                self.preview.setText(localize('Original formatting is preserved until edited.',
                                             '수정 전에는 원본 서식을 유지합니다.'))
        except Exception as error:
            self.preview.clear()
            self.note.setText(instructions + '\n' + str(error))
            self.note.setStyleSheet('color: #c54c32')
            return False
        self.note.setStyleSheet('')
        self.note.setText(instructions + '\n' + localize(
            'Wraps inside this box. Replacement fonts may differ.',
            '이 상자 안에서 줄을 바꿉니다. 대체 글꼴은 원본과 다를 수 있습니다.'))
        return True

    def update_preview(self, *_):
        if not self.ready or self.done:
            return
        x, y = self.region['bbox'][:2]
        self.bbox = (x, y, x+self.width.value()*72/25.4,
                     y+self.height.value()*72/25.4)
        super().update_preview()
        view = self.host.view
        rect = fitz.Rect(self.bbox) * self.document._doc[self.page].rotation_matrix
        transforms = getattr(view, '_page_transforms', {})
        if self.page in transforms:
            mapped = view.mapFromScene(transforms[self.page].mapRect(
                QRectF(rect.x0, rect.y0, rect.width, rect.height))).boundingRect()
            self.input.setGeometry(mapped.adjusted(0, 0, 2, 2))
        self.input.setStyleSheet('QPlainTextEdit { background: %s; color: %s; border: 1px solid #4389d6; }'
                                % (self.palette.palette().base().color().name(), self.color.name()))
        # Formatting is visual only: keep local text undo/redo untouched.
        self.input.document().setDefaultTextOption(self._text_option())
        self.timer.start()

    def _text_option(self):
        option = self.input.document().defaultTextOption()
        option.setAlignment((Qt.AlignLeft, Qt.AlignHCenter, Qt.AlignRight)[self.alignment.currentIndex()])
        return option

    def commit(self):
        if self.done:
            return True
        if self.host.doc is not self.document or self.host.page_index != self.page:
            self.close()
            return False
        if self.unchanged():
            self.close()
            return True
        if not self.validate():
            return False
        host = self.host
        host._inline_text = None
        success = host._perform_text_edit(lambda: self.document.replace_text_region(
            self.page, self.region, self.input.text(), self.size.value(), self.rgb(), **self.options()))
        if success:
            self.close()
        else:
            host._inline_text = self
            self.input.setFocus()
        return success

    def close(self):
        if hasattr(self, 'timer'):
            self.timer.stop()
        self.host.view.canvas.set_selection([])
        super().close()
