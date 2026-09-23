"""Windows/Qt 인쇄 대화상자를 통한 PDF 문서 인쇄."""

import os

from .i18n import tr


def selected_page_indices(page_count, current_index=0, mode="all",
                          from_page=0, to_page=0, reverse=False):
    """인쇄 대화상자의 1-based 범위를 0-based 페이지 목록으로 바꾼다."""
    if page_count <= 0:
        return []
    if mode == "current":
        pages = [max(0, min(current_index, page_count - 1))]
    elif mode == "range" and from_page > 0 and to_page > 0:
        start = max(1, min(from_page, page_count)) - 1
        end = max(start + 1, min(to_page, page_count))
        pages = list(range(start, end))
    else:
        pages = list(range(page_count))
    return list(reversed(pages)) if reverse else pages


def apply_print_options(printer, options):
    """Apply the unified dialog values to a preview or physical printer."""
    from PyQt5.QtPrintSupport import QPrinter

    printer_name = options.get("printer_name")
    if printer_name:
        printer.setPrinterName(printer_name)
    mode = options.get("mode", "all")
    printer.setPrintRange({
        "current": QPrinter.CurrentPage,
        "range": QPrinter.PageRange,
    }.get(mode, QPrinter.AllPages))
    printer.setFromTo(
        max(1, int(options.get("from_page", 1))),
        max(1, int(options.get("to_page", 1))),
    )
    printer.setPageOrder(
        QPrinter.LastPageFirst if options.get("reverse")
        else QPrinter.FirstPageFirst)
    printer.setDuplex({
        "long": QPrinter.DuplexLongSide,
        "short": QPrinter.DuplexShortSide,
    }.get(options.get("duplex"), QPrinter.DuplexNone))
    printer.setCopyCount(max(1, int(options.get("copies", 1))))
    orientation = options.get("orientation", "auto")
    if orientation in ("portrait", "landscape"):
        printer.setOrientation(
            QPrinter.Landscape if orientation == "landscape"
            else QPrinter.Portrait)


def create_print_dialog(host):
    """Create one dialog containing preview and all commonly used options."""
    from PyQt5.QtCore import QTimer
    from PyQt5.QtPrintSupport import QPrinterInfo, QPrintPreviewWidget
    from PyQt5.QtWidgets import (
        QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
        QFrame, QHBoxLayout, QLabel, QSpinBox, QVBoxLayout, QWidget,
    )

    from . import settings
    from .icons import fluent_icon

    class IntegratedPrintDialog(QDialog):
        def __init__(self):
            super().__init__(host)
            self.setWindowTitle(tr("인쇄"))
            self.resize(1050, 720)
            self._preview_printer = host._new_printer()

            layout = QHBoxLayout(self)
            controls = QFrame()
            controls.setObjectName("printSettingsCard")
            controls.setMinimumWidth(270)
            controls.setMaximumWidth(340)
            side = QVBoxLayout(controls)
            side.setContentsMargins(18, 18, 18, 18)
            side.setSpacing(12)

            settings_header = QHBoxLayout()
            settings_icon = QLabel()
            settings_icon.setPixmap(fluent_icon("print", size=20).pixmap(20, 20))
            settings_title = QLabel(tr("인쇄 설정"))
            settings_title.setProperty("role", "cardTitle")
            settings_header.addWidget(settings_icon)
            settings_header.addWidget(settings_title)
            settings_header.addStretch(1)
            side.addLayout(settings_header)

            description = QLabel(tr(
                "미리보기를 확인하면서 출력 옵션을 선택하세요."))
            description.setProperty("role", "secondary")
            description.setWordWrap(True)
            side.addWidget(description)
            form = QFormLayout()
            form.setVerticalSpacing(10)

            self.printer = QComboBox()
            printers = QPrinterInfo.availablePrinters()
            for info in printers:
                self.printer.addItem(info.printerName(), info.printerName())
            current_name = self._preview_printer.printerName()
            current_index = self.printer.findData(current_name)
            if current_index >= 0:
                self.printer.setCurrentIndex(current_index)
            elif current_name:
                self.printer.insertItem(0, current_name, current_name)
            if self.printer.count() == 0:
                self.printer.addItem(tr("기본 프린터"), "")
                self.printer.setEnabled(False)
            form.addRow(tr("프린터:"), self.printer)

            self.mode = QComboBox()
            self.mode.addItem(tr("전체 페이지"), "all")
            self.mode.addItem(tr("현재 페이지"), "current")
            self.mode.addItem(tr("지정한 페이지"), "range")
            form.addRow(tr("인쇄 범위:"), self.mode)

            range_box = QWidget()
            range_layout = QHBoxLayout(range_box)
            range_layout.setContentsMargins(0, 0, 0, 0)
            self.from_page = QSpinBox()
            self.to_page = QSpinBox()
            for spin in (self.from_page, self.to_page):
                spin.setRange(1, host.doc.page_count)
            self.from_page.setValue(1)
            self.to_page.setValue(host.doc.page_count)
            range_layout.addWidget(self.from_page)
            range_layout.addWidget(QLabel("–"))
            range_layout.addWidget(self.to_page)
            self.range_box = range_box
            form.addRow(tr("쪽 지정:"), range_box)

            self.reverse = QCheckBox(tr("역순 인쇄"))
            form.addRow("", self.reverse)

            self.orientation = QComboBox()
            self.orientation.addItem(tr("자동 (문서 방향)"), "auto")
            self.orientation.addItem(tr("세로"), "portrait")
            self.orientation.addItem(tr("가로"), "landscape")
            form.addRow(tr("용지 방향:"), self.orientation)

            self.duplex = QComboBox()
            self.duplex.addItem(tr("단면 인쇄"), "simplex")
            self.duplex.addItem(tr("양면 인쇄 (긴 쪽 넘김)"), "long")
            self.duplex.addItem(tr("양면 인쇄 (짧은 쪽 넘김)"), "short")
            saved_duplex = settings.print_duplex_mode()
            saved_index = self.duplex.findData(saved_duplex)
            self.duplex.setCurrentIndex(max(0, saved_index))
            form.addRow(tr("인쇄 방식:"), self.duplex)

            self.copies = QSpinBox()
            self.copies.setRange(1, 999)
            form.addRow(tr("매수:"), self.copies)
            side.addLayout(form)
            side.addStretch(1)

            buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
            print_button = buttons.addButton(
                tr("인쇄"), QDialogButtonBox.AcceptRole)
            print_button.setIcon(fluent_icon("print"))
            buttons.button(QDialogButtonBox.Cancel).setText(tr("취소"))
            print_button.setProperty("accent", True)
            buttons.accepted.connect(self.accept)
            buttons.rejected.connect(self.reject)
            side.addWidget(buttons)

            preview_card = QFrame()
            preview_card.setObjectName("printPreviewCard")
            preview_column = QVBoxLayout(preview_card)
            preview_column.setContentsMargins(14, 14, 14, 14)
            preview_column.setSpacing(10)
            preview_title = QLabel(tr("인쇄 미리보기"))
            preview_title.setProperty("role", "cardTitle")
            preview_column.addWidget(preview_title)
            self.preview = QPrintPreviewWidget(self._preview_printer, self)
            self.preview.setObjectName("printPreviewWidget")
            self.preview.setZoomMode(QPrintPreviewWidget.FitInView)
            self.preview.paintRequested.connect(
                lambda printer: host._paint_document(
                    printer, False, self.options()))
            preview_column.addWidget(self.preview, 1)

            layout.addWidget(controls)
            layout.addWidget(preview_card, 1)

            for signal in (
                    self.printer.currentIndexChanged,
                    self.mode.currentIndexChanged,
                    self.from_page.valueChanged,
                    self.to_page.valueChanged,
                    self.reverse.toggled,
                    self.orientation.currentIndexChanged,
                    self.duplex.currentIndexChanged,
                    self.copies.valueChanged):
                signal.connect(self._schedule_preview)
            self.mode.currentIndexChanged.connect(self._update_range_state)
            self.from_page.valueChanged.connect(self._update_range_bounds)
            self._preview_timer = QTimer(self)
            self._preview_timer.setSingleShot(True)
            self._preview_timer.setInterval(80)
            self._preview_timer.timeout.connect(self._refresh_preview)
            self._update_range_state()
            self._preview_timer.start(0)

        def options(self):
            return {
                "printer_name": self.printer.currentData() or "",
                "mode": self.mode.currentData(),
                "from_page": self.from_page.value(),
                "to_page": self.to_page.value(),
                "reverse": self.reverse.isChecked(),
                "orientation": self.orientation.currentData(),
                "duplex": self.duplex.currentData(),
                "copies": self.copies.value(),
            }

        def _update_range_state(self, _index=None):
            self.range_box.setEnabled(self.mode.currentData() == "range")

        def _update_range_bounds(self, value):
            self.to_page.setMinimum(int(value))

        def _schedule_preview(self, _value=None):
            self._preview_timer.start()

        def _refresh_preview(self):
            preview_options = self.options()
            preview_options["copies"] = 1
            host._prepare_print_orientation(
                self._preview_printer, preview_options)
            apply_print_options(self._preview_printer, preview_options)
            self.preview.updatePreview()

        def accept(self):
            settings.set_print_duplex_mode(self.duplex.currentData())
            super().accept()

    return IntegratedPrintDialog()


class PrintMixin:
    """DocumentTab에 인쇄 기능을 제공한다."""

    MAX_PRINT_ZOOM = 300.0 / 72.0

    def _new_printer(self):
        from PyQt5.QtPrintSupport import QPrinter

        from . import settings

        printer = QPrinter(QPrinter.HighResolution)
        printer.setDocName(os.path.basename(self.doc.path or "Leaflet 문서"))
        duplex = {
            "simplex": QPrinter.DuplexNone,
            "long": QPrinter.DuplexLongSide,
            "short": QPrinter.DuplexShortSide,
        }.get(settings.print_duplex_mode(), QPrinter.DuplexNone)
        printer.setDuplex(duplex)
        return printer

    def print_document(self):
        if self.doc is None or self.doc.page_count <= 0:
            return

        from PyQt5.QtWidgets import QDialog

        dialog = create_print_dialog(self)
        if dialog.exec_() != QDialog.Accepted:
            return

        printer = self._new_printer()
        options = dialog.options()
        self._prepare_print_orientation(printer, options)
        apply_print_options(printer, options)
        self._paint_document(printer, True, options)

    def _prepare_print_orientation(self, printer, options):
        """Set the initial paper direction, including document-aware auto."""
        from PyQt5.QtPrintSupport import QPrinter

        orientation = options.get("orientation", "auto")
        if orientation == "auto":
            pages = selected_page_indices(
                self.doc.page_count, self.page_index,
                options.get("mode", "all"),
                options.get("from_page", 1),
                options.get("to_page", self.doc.page_count),
                bool(options.get("reverse")),
            )
            if pages:
                width, height = self.doc.page_size(pages[0])
                printer.setOrientation(
                    QPrinter.Landscape if width > height
                    else QPrinter.Portrait)
        return printer.orientation()

    def _paint_document(self, printer, show_progress=True, options=None):
        from PyQt5.QtCore import QRectF, Qt
        from PyQt5.QtGui import QPainter
        from PyQt5.QtPrintSupport import QPrinter
        from PyQt5.QtWidgets import QApplication, QMessageBox, QProgressDialog

        from .widgets import qimage_from_render

        if options is not None:
            mode = options.get("mode", "all")
            from_page = options.get("from_page", 1)
            to_page = options.get("to_page", self.doc.page_count)
            reverse = bool(options.get("reverse"))
        else:
            print_range = printer.printRange()
            if print_range == QPrinter.CurrentPage:
                mode = "current"
            elif print_range == QPrinter.PageRange:
                mode = "range"
            else:
                mode = "all"
            from_page = printer.fromPage()
            to_page = printer.toPage()
            reverse = printer.pageOrder() == QPrinter.LastPageFirst
        pages = selected_page_indices(
            self.doc.page_count,
            self.page_index,
            mode,
            from_page,
            to_page,
            reverse,
        )
        if not pages:
            return False

        progress = None
        if show_progress:
            progress = QProgressDialog(
                tr("인쇄용 페이지를 준비하는 중입니다…"), tr("취소"),
                0, len(pages), self,
            )
            progress.setWindowTitle(tr("인쇄"))
            progress.setMinimumDuration(0)
            progress.setWindowModality(Qt.WindowModal)

        painter = QPainter()
        self._prepare_print_orientation(printer, options or {})
        if not painter.begin(printer):
            if progress is not None:
                progress.close()
            QMessageBox.warning(
                self, tr("인쇄 실패"),
                tr("선택한 프린터에서 인쇄를 시작할 수 없습니다."))
            return False

        cancelled = False
        error = None
        try:
            for position, page_index in enumerate(pages):
                if progress is not None and progress.wasCanceled():
                    cancelled = True
                    printer.abort()
                    break
                page_width, page_height = self.doc.page_size(page_index)
                if page_width <= 0 or page_height <= 0:
                    raise RuntimeError(
                        "%d쪽 크기를 읽을 수 없습니다." % (page_index + 1))
                if position > 0:
                    if options is not None and options.get(
                            "orientation", "auto") == "auto":
                        printer.setOrientation(
                            QPrinter.Landscape
                            if page_width > page_height else QPrinter.Portrait)
                    if not printer.newPage():
                        raise RuntimeError(
                            "프린터에서 다음 페이지를 만들 수 없습니다.")
                printable = QRectF(printer.pageRect(QPrinter.DevicePixel))
                render_zoom = min(
                    self.MAX_PRINT_ZOOM,
                    printable.width() / page_width,
                    printable.height() / page_height,
                )
                image = qimage_from_render(
                    *self.doc.render(page_index, render_zoom))
                image_aspect = image.width() / max(1.0, image.height())
                target_width = printable.width()
                target_height = target_width / image_aspect
                if target_height > printable.height():
                    target_height = printable.height()
                    target_width = target_height * image_aspect
                target = QRectF(
                    printable.center().x() - target_width / 2,
                    printable.center().y() - target_height / 2,
                    target_width,
                    target_height,
                )
                painter.drawImage(target, image)
                if progress is not None:
                    progress.setLabelText(tr(
                        "%d쪽 인쇄 준비 중…" % (page_index + 1)))
                    progress.setValue(position + 1)
                    QApplication.processEvents()
        except Exception as exc:  # 프린터/드라이버 오류는 사용자에게 설명한다.
            error = str(exc)
        finally:
            painter.end()
            if progress is not None:
                progress.close()

        if error:
            QMessageBox.warning(self, tr("인쇄 실패"), error)
        elif cancelled:
            self.statusBar().showMessage("인쇄를 취소했습니다", 3000)
        elif show_progress:
            self.statusBar().showMessage(
                "%d쪽을 프린터로 보냈습니다" % len(pages), 5000)
        return not error and not cancelled
