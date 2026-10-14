"""Per-save cleanup and explicit Illustrator round-trip policy."""

from PyQt5.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from .i18n import localize


def choose_save_options(parent, *, compatibility_only=False):
    dialog = QDialog(parent)
    dialog.setWindowTitle(localize("PDF save options", "PDF 저장 옵션"))
    layout = QVBoxLayout(dialog)
    metadata = QCheckBox(localize(
        "Remove document metadata (title, author, software, dates and XMP)",
        "문서 메타데이터 제거 (제목·작성자·제작 프로그램·날짜·XMP)"))
    editing = QCheckBox(localize(
        "Remove Leaflet object re-editing information", "Leaflet 개체 재편집 정보 제거"))
    if not compatibility_only:
        layout.addWidget(metadata)
        layout.addWidget(editing)
    illustrator = QCheckBox(localize(
        "Illustrator-compatible save (use current PDF content)",
        "Illustrator 호환 저장 (현재 PDF 내용 기준)"))
    illustrator.setObjectName("illustratorCompatibleSave")
    illustrator.setChecked(True)
    layout.addWidget(illustrator)
    explanation = localize(
        "Illustrator-compatible saving removes its private editing data so reopening uses "
        "the current PDF content. Original AI layer/effect editing information is not preserved; "
        "this does not create an AI file or guarantee full Illustrator editability. "
        "Unchecking it preserves existing Illustrator data, which may reopen old pages or content.",
        "Illustrator 호환 저장은 기존 Illustrator 재편집 데이터를 제거하여 현재 PDF 내용으로 "
        "열도록 합니다. 원본 AI의 레이어·효과 편집 정보는 보존하지 않으며, AI 파일 생성이나 "
        "완전한 Illustrator 편집을 보장하지 않습니다. 체크를 해제하면 기존 정보를 보존하지만 "
        "Illustrator에서 이전 페이지·내용이 다시 나타날 수 있습니다.")
    if not compatibility_only:
        explanation = localize(
            "Removing Leaflet re-editing information preserves visible content, but Leaflet-added "
            "shapes lose their object editing information. Annotations and attachments are preserved.\n\n",
            "Leaflet 재편집 정보를 제거해도 보이는 내용은 유지되지만 Leaflet에서 추가한 도형의 "
            "개체 편집 정보는 사라집니다. 주석과 첨부파일은 유지됩니다.\n\n") + explanation
    hint = QLabel(explanation)
    hint.setWordWrap(True)
    layout.addWidget(hint)
    buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
    buttons.button(QDialogButtonBox.Save).setText(localize("Save", "저장"))
    buttons.button(QDialogButtonBox.Cancel).setText(localize("Cancel", "취소"))
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.resize(560, 320 if not compatibility_only else 240)
    if dialog.exec_() != QDialog.Accepted:
        return None
    return (metadata.isChecked() if not compatibility_only else False,
            editing.isChecked() if not compatibility_only else False,
            illustrator.isChecked())
