"""Explicit, per-save cleanup options; both are disabled by default."""

from PyQt5.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from .i18n import localize


def choose_save_options(parent):
    dialog = QDialog(parent)
    dialog.setWindowTitle(localize("PDF save options", "PDF 저장 옵션"))
    layout = QVBoxLayout(dialog)
    metadata = QCheckBox(localize(
        "Remove document metadata (title, author, software, dates and XMP)",
        "문서 메타데이터 제거 (제목·작성자·제작 프로그램·날짜·XMP)"))
    editing = QCheckBox(localize(
        "Remove Leaflet object re-editing information", "Leaflet 개체 재편집 정보 제거"))
    layout.addWidget(metadata)
    layout.addWidget(editing)
    hint = QLabel(localize(
        "Removing re-editing information preserves visible content, but Leaflet-added "
        "shapes lose their object editing information. Annotations and attachments are preserved.",
        "재편집 정보를 제거해도 보이는 내용은 유지되지만 Leaflet에서 추가한 도형의 "
        "개체 편집 정보는 사라집니다. 주석과 첨부파일은 유지됩니다."))
    hint.setWordWrap(True)
    layout.addWidget(hint)
    buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
    buttons.button(QDialogButtonBox.Save).setText(localize("Save", "저장"))
    buttons.button(QDialogButtonBox.Cancel).setText(localize("Cancel", "취소"))
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.resize(520, 190)
    if dialog.exec_() != QDialog.Accepted:
        return None
    return metadata.isChecked(), editing.isChecked()
