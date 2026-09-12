"""Guide settings with a preview of the current page."""

from PyQt5.QtCore import Qt, QPointF
from PyQt5.QtGui import QPainter, QPen, QColor, QPixmap
from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QComboBox,
    QDoubleSpinBox, QCheckBox, QLineEdit, QLabel, QDialogButtonBox, QMessageBox)
from .i18n import localize
from .page_ranges import parse_page_groups
from .binding_guides import guide_points
from .widgets import qimage_from_render

PT_PER_MM = 72 / 25.4


class BindingGuideDialog(QDialog):
    def __init__(self, document, page, parent=None):
        super().__init__(parent)
        self.document, self.page = document, page
        self.setWindowTitle(localize('Binding / folding guide', '제본·접기 안내선'))
        layout = QVBoxLayout(self)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.preview)
        self.page_width, self.page_height = document.page_size(page)
        scale = min(320/self.page_width, 230/self.page_height)
        self.image = qimage_from_render(*document.render(page, scale))
        form = QFormLayout()
        self.edge = QComboBox()
        for en, ko, value in [('Left', '왼쪽에서', 'left'), ('Right', '오른쪽에서', 'right'),
                ('Top', '위에서', 'top'), ('Bottom', '아래에서', 'bottom'),
                ('Vertical center', '세로 중앙 (접기)', 'vertical-center'),
                ('Horizontal center', '가로 중앙 (접기)', 'horizontal-center')]:
            self.edge.addItem(localize(en, ko), value)
        form.addRow(localize('Position', '위치'), self.edge)
        self.offset = self.spin(15, 0, 5000, ' mm')
        form.addRow(localize('Distance from edge', '가장자리에서 거리'), self.offset)
        self.inset = self.spin(5, 0, 5000, ' mm')
        form.addRow(localize('Line end inset', '선 끝 여백'), self.inset)
        self.width = self.spin(.5, .1, 10, ' pt')
        form.addRow(localize('Line width', '선 두께'), self.width)
        self.style = QComboBox()
        self.style.addItems([localize('Dashed', '점선'), localize('Solid', '실선')])
        form.addRow(localize('Line style', '선 모양'), self.style)
        self.color = QComboBox()
        self.color.addItem(localize('Gray', '회색'), .45)
        self.color.addItem(localize('Black', '검정'), 0.)
        form.addRow(localize('Color', '색상'), self.color)
        self.range = QLineEdit('1-%d' % document.page_count)
        form.addRow(localize('Pages (e.g. 1,3-5)', '페이지 (예: 1,3-5)'), self.range)
        layout.addLayout(form)
        self.mirror = QCheckBox(localize('Mirror left/right on even pages', '짝수 페이지에서 좌우 반전'))
        layout.addWidget(self.mirror)
        self.save_copy = QCheckBox(localize('Save as PDF after adding', '추가 후 PDF로 다른 이름으로 저장'))
        self.save_copy.setChecked(True)
        layout.addWidget(self.save_copy)
        self.note = QLabel(localize('Preview: current page. Guides will be printed.',
                                    '미리보기: 현재 페이지. 안내선은 인쇄에도 포함됩니다.'))
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText(localize('Add guides', '안내선 추가'))
        buttons.button(QDialogButtonBox.Cancel).setText(localize('Cancel', '취소'))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for widget in (self.edge, self.style, self.color):
            widget.currentIndexChanged.connect(self.update_preview)
        for widget in (self.offset, self.inset, self.width):
            widget.valueChanged.connect(self.update_preview)
        self.mirror.toggled.connect(self.update_preview)
        self.update_preview()

    @staticmethod
    def spin(value, minimum, maximum, suffix):
        widget = QDoubleSpinBox()
        widget.setRange(minimum, maximum)
        widget.setDecimals(2)
        widget.setValue(value)
        widget.setSuffix(suffix)
        return widget

    def values(self):
        return dict(edge=self.edge.currentData(), offset=self.offset.value()*PT_PER_MM,
            inset=self.inset.value()*PT_PER_MM, width=self.width.value(),
            dashed=self.style.currentIndex() == 0, gray=self.color.currentData(),
            mirror=self.mirror.isChecked())

    def update_preview(self, *_):
        values = self.values()
        self.offset.setEnabled('center' not in values['edge'])
        self.mirror.setEnabled(values['edge'] in ('left', 'right'))
        pix = QPixmap.fromImage(self.image)
        try:
            points = guide_points(self.page_width, self.page_height, values['edge'],
                values['offset'], values['inset'], values['mirror'], self.page)
        except ValueError:
            self.preview.setPixmap(pix)
            return
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        scale = pix.width()/self.page_width
        pen = QPen(QColor.fromRgbF(*([values['gray']]*3)), max(1, values['width']*scale))
        pen.setStyle(Qt.DashLine if values['dashed'] else Qt.SolidLine)
        painter.setPen(pen)
        painter.drawLine(*(QPointF(x*scale,y*scale) for x,y in points))
        painter.end()
        self.preview.setPixmap(pix)

    def accept(self):
        try:
            groups = parse_page_groups(self.range.text(), self.document.page_count)
            self.pages = sorted({page for group in groups for page in group})
            v = self.values()
            for page in self.pages:
                guide_points(*self.document.page_size(page), v['edge'], v['offset'],
                             v['inset'], v['mirror'], page)
        except ValueError as error:
            QMessageBox.warning(self, localize('Guide settings', '안내선 설정'), str(error))
            return
        super().accept()
