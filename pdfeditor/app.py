"""AppWindow(셸) + DocumentTab — 탭 기반 다중 문서/창.

구조: 문서 하나 = DocumentTab(QMainWindow, 믹스인 전부). 바깥 AppWindow가
탭들을 QTabWidget에 담고, 활성 탭의 메뉴바를 자기 창에 reparent한다(믹스인은
여전히 자기 탭의 statusBar/QAction/docks를 쓰므로 거의 수정이 없다).
문서가 하나도 없으면 시작 페이지를 보여준다.
"""

import json
import os
import subprocess
import tempfile
import uuid

from PyQt5.QtCore import QEvent, QMimeData, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QDrag
from PyQt5.QtWidgets import (
    QAction, QActionGroup, QApplication, QCheckBox, QDialog, QDialogButtonBox,
    QDockWidget, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QMainWindow, QMenuBar, QMessageBox, QProgressDialog, QPushButton,
    QSpinBox, QSplitter, QStackedWidget, QStatusBar, QTabBar, QTabWidget, QToolBar,
    QToolButton, QVBoxLayout, QWidget,
)

from . import settings
from .access import command_allowed, editing_command
from .annotation_ui import AnnotationPersistenceMixin
from .annots import AnnotMixin
from .editing import EditMixin
from .editor_workspace import EditorWorkspaceMixin
from .document_tools import DocumentToolsMixin
from .d2d_backend import probe_d2d_backend
from .icons import fluent_icon
from .filetypes import (
    DOCUMENT_OPEN_FILTER, is_illustrator_document, is_supported_document)
from .i18n import install as install_i18n, localize, tr, translate_tree
from .meta import APP_NAME, APP_VERSION
from .ocr import OcrMixin
from .pages import PagesMixin
from .printing import PrintMixin
from .startpage import StartPage
from .textsel import TextSelectMixin
from .update_dialog import UpdateCheckWorker, UpdateDialog
from .update_service import GitHubUpdateService, UpdateError
from .viewer import ViewerMixin
from .widgets import BookmarkTree, PageView, ThumbList
from .workspaces import WindowWorkspaceMixin, workspace_policy
# Initialize QtNetwork's SIP types before constructing any window. Importing
# them for the first time during a save can trigger cyclic Qt-widget collection
# in the middle of extension initialization on Windows. This loads only the
# lightweight transport; it does not start a server or an editor process.
from .process_workspace import application_bridge


def _make_action(parent, text, shortcut, slot, icon_name=None):
    """QAction 생성 — triggered의 checked 인자가 슬롯 첫 인자에 잘못 꽂히지
    않게 항상 람다로 감싼다."""
    a = QAction(tr(text), parent)
    if icon_name:
        a.setIcon(fluent_icon(icon_name))
    if shortcut:
        a.setShortcut(shortcut)
    a.triggered.connect(lambda _checked=False, s=slot: s())
    kind = getattr(slot, "access_kind", None)
    if kind:
        a.setProperty("spdfAccessKind", kind)
        allowed = command_allowed(parent, kind)
        a.setEnabled(allowed)
        a.setVisible(allowed)
    return a


class _TranslatedStatusBar(QStatusBar):
    def showMessage(self, message, timeout=0):
        super().showMessage(tr(message), timeout)


def _render_diagnostic_summary(info):
    mode = info.get("mode", "cpu")
    reason = str(info.get("reason", "") or "")
    features = tuple(info.get("features", ()))
    labels = {
        "direct": localize("GPU rendering", "GPU 렌더링"),
        "composite": localize(
            "GPU rendering (composited)", "GPU 렌더링(합성)"),
        "fallback": localize("CPU rendering", "CPU 렌더링"),
        "pending": localize(
            "CPU now · GPU preparing", "현재 CPU · GPU 준비 중"),
        "cpu": localize("CPU rendering", "CPU 렌더링"),
    }
    reason_labels = (
        (("begin-mask", "end-mask"), localize("soft mask", "소프트 마스크")),
        (("clip-image-mask",), localize("clip mask", "클리핑 마스크")),
        (("non-uniform stroked text transform",),
         localize("transformed stroked text", "변형된 윤곽선 글자")),
        (("transparency group", "begin-group", "end-group"),
         localize("blend/transparency", "혼합·투명도")),
        (("GPU scene limit", "shading data exceeds"),
         localize("scene memory limit", "장면 메모리 상한")),
    )
    short_reason = ""
    for needles, label in reason_labels:
        if any(needle in reason for needle in needles):
            short_reason = label
            break
    text = labels.get(mode, labels["cpu"])
    if reason == "OpenGL CPU tiles":
        text = localize("CPU rendering · OpenGL composition",
                        "CPU 렌더링 · OpenGL 합성")
    if mode == "composite" and {"raster-shading", "cpu-island"}.intersection(features):
        text = localize("CPU+GPU rendering", "CPU+GPU 렌더링")
    if mode == "fallback" and short_reason:
        text += " · " + short_reason
    feature_names = {
        "vector": localize("vector", "벡터"),
        "vector-clip": localize("vector clip", "벡터 클리핑"),
        "text": localize("text", "글자"),
        "text-clip": localize("text clip", "글자 클리핑"),
        "image": localize("decoded image", "디코딩 이미지"),
        "stencil": localize("stencil image", "스텐실 이미지"),
        "shading": localize("shading", "그라데이션"),
        "vector-shading": localize("GPU gradient drawing", "GPU 그라데이션 그리기"),
        "gradient-primitive": localize("native gradient brush", "네이티브 그라데이션 브러시"),
        "raster-shading": localize("CPU-prepared gradient bitmap", "CPU에서 준비한 그라데이션 비트맵"),
        "cpu-island": localize("CPU-prepared composite region", "CPU에서 준비한 합성 영역"),
        "transparency-group": localize(
            "transparency group", "투명도 그룹"),
        "soft-mask": localize("soft mask", "소프트 마스크"),
        "clip-mask": localize("clip mask", "클리핑 마스크"),
        "stroke-style": localize("stroke style", "선 스타일"),
        "blend-mode": localize("blend mode", "혼합 모드"),
        "stroked-text": localize("stroked text", "윤곽선 글자"),
        "stroked-text-clip": localize(
            "stroked text clip", "윤곽선 글자 클리핑"),
        "stroked-vector-clip": localize(
            "stroked vector clip", "선 클리핑"),
        "deferred-scene": localize(
            "background GPU preparation", "백그라운드 GPU 준비"),
    }
    detail = reason
    if reason == "GPU scene deferred by complexity probe":
        detail = localize(
            "This complex page is displayed by the CPU while its GPU scene is prepared in the background.",
            "복잡한 쪽을 CPU로 먼저 표시하면서 GPU 장면을 백그라운드에서 준비하고 있습니다.")
    elif reason == "GPU scene time budget exceeded":
        detail = localize(
            "The page did not finish GPU preparation within the interactive budget, so CPU display remains visible while background preparation continues.",
            "대화형 준비 시간 안에 GPU 장면이 끝나지 않아 CPU 화면을 유지하면서 백그라운드 준비를 계속합니다.")
    tooltip = localize(
        "Current page rendering: ", "현재 페이지 렌더링: ") + text
    # Describe responsibilities of this display path, not instantaneous CPU
    # activity: scene extraction/decoding may already be cached.
    cpu_tasks = [localize("PDF interpretation", "PDF 해석")]
    raster_path = mode in ("cpu", "fallback", "pending") or reason == "OpenGL CPU tiles"
    if reason == "Direct2D WARP":
        cpu_tasks.append(localize(
            "Direct2D software rendering and composition",
            "Direct2D 소프트웨어 렌더링·합성"))
    elif raster_path:
        cpu_tasks.append(localize(
            "page preview and tile rasterization (text, vectors, images)",
            "페이지 미리보기·타일 래스터화(글자·벡터·이미지)"))
    else:
        cpu_tasks.append(localize(
            "GPU scene preparation (paths, glyphs, draw commands)",
            "GPU 장면 준비(경로·글리프·그리기 명령)"))
        if {"image", "stencil"}.intersection(features):
            cpu_tasks.append(localize("image decoding and pixel preparation",
                                      "이미지 디코딩·픽셀 준비"))
        if "raster-shading" in features:
            cpu_tasks.append(localize("shading bitmap preparation",
                                      "그라데이션 비트맵 준비"))
        if "vector-shading" in features:
            cpu_tasks.append(localize("gradient colors and geometry preparation",
                                      "그라데이션 색상·기하 정보 준비"))
        if "cpu-island" in features:
            cpu_tasks.append(localize("blend/transparency region rasterization",
                                      "혼합·투명도 영역 래스터화"))
    if mode == "pending":
        cpu_tasks.append(localize("GPU scene preparation", "GPU 장면 준비"))
    tooltip += "\n" + localize("CPU responsibilities: ", "CPU 담당 작업: ") + ", ".join(cpu_tasks)
    tooltip += "\n" + localize(
        "Tasks describe the rendering path; cached work may not run every frame.",
        "렌더링 경로별 담당 작업이며 캐시된 작업은 매 프레임 반복하지 않습니다.")
    if features:
        tooltip += "\n" + localize(
            "GPU scene contents: ", "GPU 장면 구성: ") + ", ".join(
            feature_names.get(feature, feature) for feature in features)
    if detail:
        tooltip += "\n" + localize("Status: ", "상태: ") + detail
    if info.get("backend_failure"):
        tooltip += "\n" + localize(
            "Direct2D unavailable: ", "Direct2D 사용 불가: ") + str(
                info["backend_failure"])
    return text, tooltip


def _show_default_app_settings(parent):
    from .defaultapp import (
        browser_external_pdf_enabled, friendly_handler_name, is_spdf_default,
        open_default_apps_settings, set_browser_external_pdf,
    )
    dialog = QDialog(parent)
    dialog.setWindowTitle("PDF 기본 프로그램 및 브라우저 설정")
    dialog.setMinimumWidth(500)
    layout = QVBoxLayout(dialog)

    current = friendly_handler_name()
    spdf_default = is_spdf_default()
    default_label = QLabel("Windows PDF 기본 앱: <b>%s</b>" % current)
    default_label.setTextFormat(Qt.RichText)
    layout.addWidget(default_label)
    if not spdf_default:
        warning = QLabel(
            "아래 옵션을 켜도 현재 기본 PDF 앱으로 열립니다. 먼저 Windows "
            "기본 앱에서 sPDF를 선택하세요.")
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #b45309;")
        layout.addWidget(warning)

    defaults = QPushButton("Windows 기본 앱 설정 열기")
    defaults.setIcon(fluent_icon("settings"))
    layout.addWidget(defaults)
    layout.addSpacing(8)

    labels = {
        "edge": "Microsoft Edge에서 PDF를 sPDF로 열기",
        "chrome": "Google Chrome에서 PDF를 sPDF로 열기",
        "firefox": "Mozilla Firefox에서 PDF를 sPDF로 열기",
    }
    states = {}
    checks = {}
    for browser, label in labels.items():
        states[browser] = browser_external_pdf_enabled(browser)
        check = QCheckBox(label)
        check.setChecked(states[browser])
        checks[browser] = check
        layout.addWidget(check)

    note = QLabel(
        "브라우저의 내장 PDF 뷰어 대신 Windows 기본 앱을 사용합니다. "
        "적용 후 브라우저를 완전히 종료했다 다시 실행하세요. Firefox는 "
        "웹페이지에 삽입된 PDF를 계속 브라우저에 표시할 수 있습니다.\n\n"
        "이 설정은 사용자별 브라우저 정책을 사용하므로 브라우저에 "
        "'조직에서 관리'가 표시될 수 있습니다.")
    note.setWordWrap(True)
    layout.addSpacing(6)
    layout.addWidget(note)

    buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Close)
    buttons.button(QDialogButtonBox.Save).setText("적용")
    buttons.button(QDialogButtonBox.Save).setIcon(fluent_icon("save"))
    buttons.button(QDialogButtonBox.Close).setText("닫기")
    buttons.button(QDialogButtonBox.Close).setIcon(fluent_icon("close"))
    layout.addWidget(buttons)

    def _open_defaults():
        if not open_default_apps_settings():
            QMessageBox.warning(
                dialog, "설정 열기 실패",
                "설정 화면을 열지 못했습니다.\n"
                "Windows 설정 → 앱 → 기본 앱에서 직접 변경하세요.")

    def _apply_browser_settings():
        changed = []
        applied = []
        try:
            for browser, check in checks.items():
                enabled = check.isChecked()
                if enabled != states[browser]:
                    set_browser_external_pdf(browser, enabled)
                    applied.append(browser)
                    changed.append(labels[browser].split("에서", 1)[0])
        except (OSError, ValueError) as e:
            # 일부 브라우저만 바뀐 채 남지 않도록 이번 적용분을 되돌린다.
            for browser in reversed(applied):
                try:
                    set_browser_external_pdf(browser, states[browser])
                except OSError:
                    pass
            QMessageBox.critical(
                dialog, "브라우저 설정 실패",
                "PDF 열기 설정을 변경하지 못했습니다.\n\n%s" % e)
            return
        if changed:
            QMessageBox.information(
                dialog, "브라우저 설정 완료",
                "%s 설정을 변경했습니다.\n"
                "브라우저를 완전히 종료한 뒤 다시 실행하세요."
                % ", ".join(changed))
        dialog.accept()

    defaults.clicked.connect(lambda _checked=False: _open_defaults())
    buttons.button(QDialogButtonBox.Save).clicked.connect(
        lambda _checked=False: _apply_browser_settings())
    buttons.rejected.connect(dialog.reject)
    dialog.exec_()


_TAB_MIME = "application/x-spdf-tab"
_dragged_tabs = {}


def _decode_tab_drag(mime):
    if not mime.hasFormat(_TAB_MIME):
        return None
    try:
        return json.loads(bytes(mime.data(_TAB_MIME)).decode("utf-8"))
    except (TypeError, ValueError, UnicodeDecodeError):
        return None


class TransferTabBar(QTabBar):
    """창 안 재정렬은 Qt에 맡기고, 탭 막대 밖으로 나가면 창 간 드래그한다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._pressed_tab = None

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            i = self.tabAt(ev.pos())
            self._pressed_tab = self.window()._tabs.widget(i) if i >= 0 else None
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        super().mouseReleaseEvent(ev)
        self._pressed_tab = None

    def mouseMoveEvent(self, ev):
        tab = self._pressed_tab
        if tab is not None and ev.buttons() & Qt.LeftButton and \
                not self.rect().adjusted(-10, -10, 10, 10).contains(ev.pos()):
            self._pressed_tab = None
            self._start_transfer(tab)
            return
        super().mouseMoveEvent(ev)

    def _start_transfer(self, tab):
        shell = self.window()
        if not isinstance(shell, AppWindow) or shell._tabs.indexOf(tab) < 0 or \
                tab.doc is None:
            return

        token = uuid.uuid4().hex
        snapshot_path = None
        if tab._dirty:
            try:
                fd, snapshot_path = tempfile.mkstemp(
                    prefix="spdf-tab-", suffix=".pdf")
                with os.fdopen(fd, "wb") as stream:
                    stream.write(tab.doc.snapshot())
            except Exception as e:
                if snapshot_path and os.path.exists(snapshot_path):
                    os.remove(snapshot_path)
                tab.statusBar().showMessage(
                    "탭 이동용 임시 저장에 실패했습니다: %s" % e, 5000)
                return

        payload = {
            "pid": os.getpid(),
            "token": token,
            "path": tab.doc.path,
            "dirty": bool(tab._dirty),
            "read_only": shell.read_only,
            "annotations_enabled": shell.annotations_enabled,
            "autosave_annotations": shell.autosave_annotations,
            "workspace_mode": shell.workspace_mode,
            "snapshot": snapshot_path,
        }
        mime = QMimeData()
        mime.setData(_TAB_MIME, json.dumps(payload).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        i = shell._tabs.indexOf(tab)
        if i >= 0:
            drag.setPixmap(self.grab(self.tabRect(i)))

        _dragged_tabs[token] = (shell, tab)
        try:
            result = drag.exec_(Qt.MoveAction)
        finally:
            _dragged_tabs.pop(token, None)

        # 같은 프로세스면 dropEvent에서 이미 위젯을 떼어 대상 창에 붙인다.
        # 아직 원래 창에 남아 있으면 다른 sPDF 프로세스가 경로를 받은 경우다.
        moved_to_external_process = result == Qt.MoveAction and \
            shell._tabs.indexOf(tab) >= 0
        if moved_to_external_process:
            shell._finish_external_tab_move(tab)
        elif snapshot_path and os.path.exists(snapshot_path):
            # 같은 프로세스 이동이나 취소에서는 임시본을 받을 프로세스가 없다.
            os.remove(snapshot_path)

    def dragEnterEvent(self, ev):
        if self._can_accept(ev.mimeData()):
            ev.setDropAction(Qt.MoveAction)
            ev.accept()
        else:
            ev.ignore()

    def dragMoveEvent(self, ev):
        if self._can_accept(ev.mimeData()):
            ev.setDropAction(Qt.MoveAction)
            ev.accept()
        else:
            ev.ignore()

    def dropEvent(self, ev):
        payload = _decode_tab_drag(ev.mimeData())
        if payload is None:
            ev.ignore()
            return

        index = self.tabAt(ev.pos())
        if index < 0:
            index = self.count()
        elif ev.pos().x() > self.tabRect(index).center().x():
            index += 1

        if self.window()._receive_tab_drop(payload, index):
            ev.setDropAction(Qt.MoveAction)
            ev.accept()
        else:
            ev.ignore()

    def _can_accept(self, mime):
        payload = _decode_tab_drag(mime)
        if not payload or not payload.get("path"):
            return False
        if payload.get("pid") == os.getpid():
            entry = _dragged_tabs.get(payload.get("token"))
            return entry is not None and entry[0] is not self.window()
        if not os.path.isfile(payload["path"]):
            return False
        if not payload.get("dirty"):
            return True
        snapshot = payload.get("snapshot")
        if not snapshot or not self._is_transfer_snapshot(snapshot):
            return False
        return self.window()._find_open_tab(payload["path"]) is None

    @staticmethod
    def _is_transfer_snapshot(path):
        try:
            full = os.path.abspath(path)
            return os.path.dirname(full) == os.path.abspath(tempfile.gettempdir()) \
                and os.path.basename(full).startswith("spdf-tab-") \
                and full.lower().endswith(".pdf") and os.path.isfile(full)
        except (TypeError, ValueError):
            return False


# ======================================================================
# DocumentTab — 문서 한 개의 뷰어/편집기 (믹스인 조립)
# ======================================================================

# MRO 주의: TextSelectMixin이 ViewerMixin보다 앞이어야 show_page 훅
# (페이지 전환 시 선택 초기화/검색 오버레이 재적용)이 동작한다.
class DocumentTab(QMainWindow, EditorWorkspaceMixin, AnnotationPersistenceMixin, DocumentToolsMixin, EditMixin, PagesMixin, OcrMixin, AnnotMixin,
                  PrintMixin, TextSelectMixin, ViewerMixin):

    title_changed = pyqtSignal()  # 탭 라벨/창 제목 갱신 신호(셸이 받는다)
    load_finished = pyqtSignal(bool)
    selection_changed = pyqtSignal(object)

    @property
    def read_only(self):
        return self._shell.read_only

    def __init__(self, shell):
        super().__init__()
        self.setStatusBar(_TranslatedStatusBar(self))
        self._shell = shell
        self._init_viewer_state()
        self._init_textsel_state()
        self._init_annot_state()
        self._init_annotation_persistence()
        self._init_ocr_state()
        self._init_edit_state()
        from .recovery_ui import TabRecovery
        self._recovery = TabRecovery(self, shell._recovery_store)
        self._recovered_unsaved = False
        self._build_ui()
        self._menubar = self.menuBar()  # 활성화 시 셸로 reparent (참조 보관)

    # --- UI 구성 -------------------------------------------------------

    def _build_ui(self):
        viewer = QWidget()
        lay = QHBoxLayout(viewer)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.thumbs = ThumbList()
        self.bookmarks = BookmarkTree(read_only=self.read_only)
        self._sidebar_stack = QStackedWidget()
        self._sidebar_stack.addWidget(self.thumbs)
        self._sidebar_stack.addWidget(self.bookmarks)
        if self._shell.workspace_mode in ("reader", "editor"):
            from .reader_view import TiledPageView
            self.view = TiledPageView()
            self.view.render_failed.connect(lambda error: self.statusBar().showMessage(
                localize("Detailed rendering failed: ", "선명한 화면 표시 실패: ") + error, 6000))
            self.view.render_device_changed.connect(
                lambda _device: self._on_render_device_changed())
        else:
            self.view = PageView()

        right = QWidget()
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(0, 0, 0, 0)
        rlay.setSpacing(0)
        rlay.addWidget(self._build_search_bar())
        rlay.addWidget(self.view, 1)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._sidebar_stack)
        splitter.addWidget(right)
        splitter.setCollapsible(0, True)
        splitter.setCollapsible(1, False)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([settings.thumbnail_width(), 900])
        splitter.splitterMoved.connect(self.on_thumbnail_splitter_moved)
        lay.addWidget(splitter)
        self._viewer_splitter = splitter
        self.setCentralWidget(self._init_editor_workspace(viewer))

        self.thumbs.page_selected.connect(self.show_page)
        self.thumbs.page_position_requested.connect(
            self.navigate_from_thumbnail)
        self.bookmarks.page_selected.connect(self.show_page)
        self.bookmarks.add_requested.connect(self.add_current_bookmark)
        self.bookmarks.rename_requested.connect(self.rename_bookmark)
        self.bookmarks.delete_requested.connect(self.delete_bookmark)
        self.bookmarks.reorder_requested.connect(self.reorder_bookmarks)
        self.thumbs.verticalScrollBar().valueChanged.connect(
            lambda _v: self._schedule_thumbs())
        self.thumbs.thumbnail_width_changed.connect(
            self.on_thumbnail_width_changed)
        self.view.zoom_changed.connect(self.on_zoom_changed)
        self.view.viewport_changed.connect(
            self.update_thumbnail_viewport_marker)
        self.view.viewport_changed.connect(self.schedule_reading_position)
        self.view.page_flip.connect(self.on_wheel_flip)
        self.view.canvas.drag_selected.connect(self.on_drag_selected)
        self.view.canvas.selection_cleared.connect(self._clear_selection)
        self.view.canvas.word_picked.connect(self.on_word_picked)
        self.view.canvas.clicked.connect(self._dispatch_click)
        self.view.canvas.ctrl_clicked.connect(self.activate_link_at)
        self.view.canvas.context_requested.connect(self.on_context_menu)
        self.view.canvas.hovered.connect(self.on_canvas_hover)
        self.view.canvas.page_activated.connect(self.show_page)

        # 메모 모아보기 독 (기본 숨김) — 탭마다 독립
        self._notes_list = QListWidget()
        self._notes_list.itemClicked.connect(self.on_note_item_clicked)
        self._notes_list.itemDoubleClicked.connect(self.on_note_item_double)
        self._notes_dock = QDockWidget("메모 모아보기", self)
        self._notes_dock.setWidget(self._notes_list)
        self.addDockWidget(Qt.RightDockWidgetArea, self._notes_dock)
        self._notes_dock.hide()

        self._page_label = QLabel("")
        self._page_size_label = QLabel("")
        self._render_diagnostic_label = QLabel("")
        self._render_diagnostic_label.setProperty("role", "secondary")
        self._render_diagnostic_label.setVisible(
            settings.render_diagnostics())
        self._page_size_label.setProperty("role", "secondary")
        self._page_size_label.setVisible(self._shell.workspace_mode == "editor")
        self.statusBar().addPermanentWidget(self._render_diagnostic_label)
        self.statusBar().addPermanentWidget(self._page_size_label)
        self.statusBar().addPermanentWidget(self._page_label)
        self._zoom_input = QSpinBox()
        self._zoom_input.setRange(
            round(self.view.ZOOM_MIN * 100), round(self.view.ZOOM_MAX * 100))
        self._zoom_input.setSingleStep(1)
        self._zoom_input.setSuffix("%")
        self._zoom_input.setKeyboardTracking(False)
        self._zoom_input.setValue(100)
        self._zoom_input.setToolTip(localize(
            "Zoom in 1% steps, based on the screen's physical DPI",
            "화면의 실제 DPI 기준 배율을 1% 단위로 입력"))
        self._zoom_input.valueChanged.connect(
            self.set_zoom_percent)
        self.statusBar().addPermanentWidget(self._zoom_input)

        self._build_menus()
        self.set_sidebar_mode(settings.sidebar_mode(), persist=False)

    def _build_search_bar(self):
        bar = QWidget()
        bar.setObjectName("searchBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(6, 4, 6, 4)
        self._search_edit = QLineEdit()
        self._search_edit.addAction(
            fluent_icon("search", size=16), QLineEdit.LeadingPosition)
        self._search_edit.setPlaceholderText("검색어 입력 후 Enter (F3 다음 / Shift+F3 이전)")
        self._search_edit.returnPressed.connect(
            lambda: self.search_start(self._search_edit.text()))
        self._search_count = QLabel("")
        prev_btn = QToolButton(); prev_btn.setIcon(fluent_icon("chevron_up", size=16))
        next_btn = QToolButton(); next_btn.setIcon(fluent_icon("chevron_down", size=16))
        prev_btn.setToolTip("이전 검색 결과 (Shift+F3)")
        next_btn.setToolTip("다음 검색 결과 (F3)")
        prev_btn.clicked.connect(lambda _c=False: self.search_prev())
        next_btn.clicked.connect(lambda _c=False: self.search_next())
        close_btn = QPushButton("닫기")
        close_btn.setIcon(fluent_icon("close", size=16))
        close_btn.clicked.connect(lambda _c=False: self.hide_search())
        for w in (self._search_edit, self._search_count, prev_btn, next_btn, close_btn):
            h.addWidget(w)
        h.setStretch(0, 1)
        bar.hide()
        self._search_bar = bar
        return bar

    def show_search(self):
        if self.is_editor_overview():
            self.open_page_editor(edit_text=False)
        self._search_bar.show()
        self._search_edit.setFocus()
        self._search_edit.selectAll()

    def hide_search(self):
        self._search_bar.hide()
        self.search_clear()

    def _act(self, menu, text, shortcut, slot, icon_name=None):
        a = _make_action(self, text, shortcut, slot, icon_name)
        menu.addAction(a)
        return a

    def _build_menus(self):
        m = self.menuBar().addMenu("파일(&F)")
        self._open_act = self._act(
            m, "열기...", "Ctrl+O", lambda: self._shell.open_dialog(), "open")
        self._act(m, "새 탭", "Ctrl+T", lambda: self._shell.open_dialog(),
                  "new_tab")
        self._act(m, "새 창", "Ctrl+Shift+N",
                  lambda: self._shell.new_window(), "new_window")
        if self._shell.workspace_mode == "editor":
            self._act(m, localize("Open reader", "읽기 창 열기"), None,
                      self._shell.open_reader, "open")
        self._recent_menu = m.addMenu("최근 파일")
        self._recent_menu.setIcon(fluent_icon("recent"))
        self._recent_menu.setToolTipsVisible(True)
        self._recent_menu.aboutToShow.connect(self._rebuild_recent_menu)
        self._fav_menu = m.addMenu("즐겨찾기")
        self._fav_menu.setIcon(fluent_icon("star"))
        self._fav_menu.setToolTipsVisible(True)
        self._fav_menu.aboutToShow.connect(self._rebuild_fav_menu)
        m.addSeparator()
        annotation_mode = self.read_only and self.annotations_enabled
        save_label = localize("Save annotations", "주석 저장") if annotation_mode else "저장"
        export_label = localize("Save PDF with annotations...", "주석 포함 PDF 저장...") \
            if annotation_mode else "다른 이름으로 저장..."
        self._save_act = self._act(m, save_label, "Ctrl+S", self.save, "save")
        self._act(m, export_label, "Ctrl+Shift+S",
                  self.save_as_dialog, "save_as")
        self._act(m, "PDF 용량 줄이기...", None,
                  self.compress_pdf, "download")
        self._act(m, "이미지를 PDF로...", None,
                  self._shell.images_to_pdf_dialog, "pages")
        self._act(m, "PDF를 이미지로...", None,
                  self.export_pdf_images, "extract")
        if self._shell._recovery_store is not None:
            self._act(m, "미저장 작업 복구...", None,
                      self._shell.show_recovery, "undo")
        self._print_act = self._act(
            m, "인쇄...", "Ctrl+P", self.print_document, "print")
        self._act(m, "탐색기에서 현재 위치 열기", None,
                  self.open_current_location, "external")
        m.addSeparator()
        self._act(m, "탭 닫기", "Ctrl+W",
                  lambda: self._shell.close_tab(self), "close")
        self._act(m, "종료", "Ctrl+Q", lambda: self._shell.request_exit(), "power")

        e = self.menuBar().addMenu("편집(&E)")
        self._undo_act = self._act(
            e, "실행 취소", "Ctrl+Z", self.undo, "undo")
        self._redo_act = self._act(
            e, "다시 실행", "Ctrl+Y", self.redo, "redo")
        self._undo_act.setEnabled(False)
        self._redo_act.setEnabled(False)
        e.addSeparator()
        self._act(e, "복사", "Ctrl+C", self.copy_selection, "copy")
        self._act(e, "현재 페이지 모두 선택", "Ctrl+A", self.select_all,
                  "select_all")
        e.addSeparator()
        self._edit_act = self._act(e, "텍스트 편집 모드", "Ctrl+E",
                                   self.toggle_edit_mode, "edit")
        self._edit_act.setCheckable(True)
        self._open_editor_act = None
        if self._shell.workspace_mode == "reader":
            self._edit_act.setShortcut("")
            self._open_editor_act = self._act(
                e, localize("Open in editor", "편집 창에서 열기"), "Ctrl+E",
                lambda: self._shell.open_editor(self), "edit")
        e.addSeparator()
        self._search_act = self._act(
            e, "찾기...", "Ctrl+F", self.show_search, "search")
        self._act(e, "다음 찾기", "F3", self.search_next, "chevron_down")
        self._act(e, "이전 찾기", "Shift+F3", self.search_prev, "chevron_up")

        p = self.menuBar().addMenu("페이지 구성(&P)")
        self._pages_act = self._act(
            p, "페이지 구성...", "Ctrl+Shift+P",
            self.show_page_organizer, "pages")
        p.addSeparator()
        reader = self._shell.workspace_mode == "reader"
        self._rotate_cw_act = self._act(
            p, "오른쪽으로 회전", "Ctrl+]",
            self.rotate_reader_cw if reader else self.rotate_page_cw,
            "rotate_cw")
        self._rotate_ccw_act = self._act(
            p, "왼쪽으로 회전", "Ctrl+[",
            self.rotate_reader_ccw if reader else self.rotate_page_ccw,
            "rotate_ccw")
        if reader:
            for action in (self._rotate_cw_act, self._rotate_ccw_act):
                action.setToolTip(localize(
                    "Rotate the current page view only (does not modify the PDF)",
                    "현재 쪽 화면만 회전 (PDF 파일은 변경하지 않음)"))
        self._act(p, "현재 페이지 삭제", "Ctrl+Delete",
                  self.delete_current_page, "delete")
        p.addSeparator()
        self._act(p, "PDF 병합...", None, self.merge_pdf, "merge")
        self._act(p, "PDF 분리...", None, self.split_pdf, "split")
        self._act(p, "현재 페이지 추출...", None,
                  self.extract_current_page, "extract")
        p.addSeparator()
        self._act(p, "페이지 여백 자르기...", None,
                  self.crop_page_margins, "edit")
        self._act(p, localize("Canvas size...", "캔버스 크기..."), None,
                  self.edit_canvas_size, "edit")
        self._act(p, localize("Bleed...", "도련 설정..."), None,
                  self.edit_page_bleed, "fit_page")
        self._act(p, "현재 페이지 책갈피 추가", "Ctrl+B",
                  self.add_current_bookmark, "notes")
        self._act(p, "TXT 책갈피 가져오기...", None,
                  self.import_outline_text, "notes")
        self._act(p, "워터마크 추가...", None,
                  self.add_watermark_dialog, "edit")

        a = self.menuBar().addMenu("주석(&A)")
        self._act(a, "선택 영역 형광펜", "Ctrl+H",
                  self.highlight_selection, "highlight")
        self._act(a, "메모 추가 (위치 클릭)", "Ctrl+M",
                  self.start_note_mode, "note")
        a.addSeparator()
        self._act(a, "메모 모아보기", "Ctrl+Shift+M",
                  self.toggle_notes_panel, "notes")

        o = self.menuBar().addMenu("OCR(&O)")
        self._act(o, "현재 페이지 OCR", "Ctrl+R", self.ocr_current_page,
                  "ocr")
        self._act(o, "전체 문서 OCR (텍스트 없는 페이지만)", "Ctrl+Shift+R",
                  self.ocr_document, "ocr")
        o.addSeparator()
        self._act(o, "AI 고품질 OCR 설정...", None,
                  self.show_ocr_engine_dialog, "ai")
        if self.read_only:
            p.menuAction().setVisible(False)
            o.menuAction().setVisible(False)

        v = self.menuBar().addMenu("보기(&V)")
        if reader:
            v.addAction(self._rotate_ccw_act)
            v.addAction(self._rotate_cw_act)
            v.addSeparator()
        self._back_view_act = self._act(
            v, "이전 보기", "Alt+Left", self.navigate_history, "back")
        self._forward_view_act = self._act(
            v, "다음 보기", "Alt+Right",
            lambda: self.navigate_history(False), "external")
        self._sync_navigation_actions()
        v.addSeparator()
        self._zoom_in_act = self._act(
            v, "확대", "Ctrl++", self.zoom_in, "zoom_in")
        self._zoom_out_act = self._act(
            v, "축소", "Ctrl+-", self.zoom_out, "zoom_out")
        self._act(v, "1% 확대", "Alt++", self.zoom_in_fine, "zoom_in")
        self._act(v, "1% 축소", "Alt+-", self.zoom_out_fine, "zoom_out")
        self._fit_width_act = self._act(
            v, "폭 맞춤", "Ctrl+0", self.zoom_fit, "fit_width")
        self._fit_page_act = self._act(
            v, "쪽 맞춤", None, self.zoom_page_fit, "fit_page")
        self._two_page_act = self._act(
            v, "두 장 보기", "Ctrl+Shift+2", self.toggle_two_page_mode,
            "two_page")
        self._two_page_act.setCheckable(True)
        v.addSeparator()
        sidebar_menu = v.addMenu("왼쪽 패널")
        sidebar_menu.setIcon(fluent_icon("pages"))
        self._sidebar_group = QActionGroup(self)
        self._sidebar_group.setExclusive(True)
        self._sidebar_actions = {}
        for mode, label, icon_name in (
                ("none", "없음", "close"),
                ("thumbnails", "페이지 미리보기", "pages"),
                ("bookmarks", "책갈피", "notes")):
            action = self._act(
                sidebar_menu, label, None,
                lambda _checked=False, selected=mode:
                self.set_sidebar_mode(selected), icon_name)
            action.setCheckable(True)
            self._sidebar_group.addAction(action)
            self._sidebar_actions[mode] = action
        self._sidebar_cycle_act = _make_action(
            self, "왼쪽 패널 전환", "Ctrl+Shift+B",
            self.cycle_sidebar_mode, "pages")
        v.addAction(self._sidebar_cycle_act)
        v.addSeparator()
        self._presentation_act = self._act(
            v, "프레젠테이션 모드", "F5", self.toggle_presentation_mode,
            "presentation")
        self._presentation_act.setCheckable(True)
        self._full_screen_act = self._act(
            v, "전체화면", "F11", self.toggle_full_screen,
            "fullscreen")
        self._full_screen_act.setCheckable(True)
        if self._shell.workspace_mode == "editor":
            for action in (self._presentation_act, self._full_screen_act):
                action.setVisible(False)
                action.setEnabled(False)
                action.setShortcut("")
        v.addSeparator()
        self._act(v, "다음 페이지", "PgDown", self.next_page,
                  "chevron_down")
        self._act(v, "이전 페이지", "PgUp", self.prev_page, "chevron_up")
        v.addSeparator()
        self._interaction_group = QActionGroup(self)
        self._interaction_group.setExclusive(True)
        self._select_tool_act = self._act(
            v, "텍스트 선택 도구", None,
            lambda: self.set_interaction_mode("select"), "text_select")
        self._hand_tool_act = self._act(
            v, "손 도구", None,
            lambda: self.set_interaction_mode("hand"), "hand")
        for action in (self._select_tool_act, self._hand_tool_act):
            action.setCheckable(True)
            self._interaction_group.addAction(action)
        self._select_tool_act.setChecked(True)
        self._favorite_act = _make_action(
            self, "즐겨찾기 추가", None, self._toggle_favorite, "star")
        self._favorite_act.setEnabled(False)

        if self._shell.workspace_mode == "editor":
            tool_bar = self.build_editor_command_bar()
        else:
            tool_bar = QToolBar("명령 모음", self)
            tool_bar.setObjectName("command_bar")
            tool_bar.setMovable(False)
            tool_bar.setFloatable(False)
            tool_bar.setIconSize(QSize(20, 20))
            tool_bar.setToolButtonStyle(Qt.ToolButtonIconOnly)
            if self._open_editor_act is not None:
                self.add_editor_mode_button(tool_bar)
            tool_bar.addAction(self._open_act)
            tool_bar.addAction(self._back_view_act)
            tool_bar.addAction(self._forward_view_act)
            tool_bar.addAction(self._save_act)
            tool_bar.addAction(self._print_act)
            tool_bar.addSeparator()
            tool_bar.addAction(self._undo_act)
            tool_bar.addAction(self._redo_act)
            tool_bar.addSeparator()
            tool_bar.addAction(self._hand_tool_act)
            tool_bar.addAction(self._select_tool_act)
            if self._open_editor_act is None:
                tool_bar.addAction(self._edit_act)
            tool_bar.addSeparator()
            tool_bar.addAction(self._pages_act)
            tool_bar.addAction(self._rotate_ccw_act)
            tool_bar.addAction(self._rotate_cw_act)
            tool_bar.addAction(self._search_act)
            tool_bar.addSeparator()
            tool_bar.addAction(self._favorite_act)
            tool_bar.addSeparator()
            self._sidebar_button = QToolButton(tool_bar)
            self._sidebar_button.setObjectName("sidebarRibbonButton")
            self._sidebar_button.setText(tr("왼쪽 패널"))
            self._sidebar_button.setIcon(fluent_icon("pages"))
            self._sidebar_button.setIconSize(QSize(20, 20))
            self._sidebar_button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            self._sidebar_button.setToolTip(tr("왼쪽 패널"))
            self._sidebar_button.setAccessibleName(tr("왼쪽 패널"))
            self._sidebar_button.setPopupMode(QToolButton.InstantPopup)
            self._sidebar_button.setMenu(sidebar_menu)
            tool_bar.addWidget(self._sidebar_button)
            tool_bar.addAction(self._zoom_in_act)
            tool_bar.addAction(self._zoom_out_act)
            tool_bar.addAction(self._fit_width_act)
            tool_bar.addAction(self._fit_page_act)
            tool_bar.addAction(self._two_page_act)
            if self._shell.workspace_mode != "editor":
                tool_bar.addSeparator()
                tool_bar.addAction(self._presentation_act)
                tool_bar.addAction(self._full_screen_act)
        self.addToolBar(Qt.TopToolBarArea, tool_bar)
        self._interaction_toolbar = tool_bar

        h = self.menuBar().addMenu("도움말(&H)")
        self._act(h, "사용법", "F1", self.show_help, "help")
        if self._shell.updates_enabled:
            self._act(h, "업데이트 확인...", None,
                      lambda: self._shell.check_for_updates(True), "update")
        self._act(h, "PDF 기본 프로그램 / 브라우저 설정...", None,
                  self.check_default_app, "settings")
        self._shell._add_language_menu(h)
        self._act(h, "오픈소스 라이선스", None, self.show_licenses,
                  "license")
        self._act(h, "정보", None, self.show_about, "info")

    # --- 페이지 넘김/클릭 ---------------------------------------------

    @editing_command
    def compress_pdf(self):
        if self.doc is None:
            return
        from .compression import compress_document
        result = compress_document(self, self.doc)
        if result:
            self.statusBar().showMessage(localize(
                "Compressed PDF saved: %s" % result,
                "압축한 PDF 저장됨: %s" % result), 5000)

    def set_interaction_mode(self, mode, announce=True):
        controller = getattr(self, "_object_controller", None)
        if controller is not None:
            controller.deactivate()
        if mode == "hand":
            if self._edit_mode:
                self.set_edit_mode(False)
            if self._note_mode:
                self.cancel_note_mode()
        self.view.set_interaction_mode(mode)
        self._hand_tool_act.setChecked(mode == "hand")
        self._select_tool_act.setChecked(mode == "select")
        if announce:
            message = (
                "손 도구 — PDF를 클릭한 채 드래그해 이동합니다"
                if mode == "hand" else
                "텍스트 선택 도구 — 글자를 드래그해 선택합니다"
            )
            self.statusBar().showMessage(message, 3000)

    def toggle_full_screen(self):
        self._shell.toggle_full_screen()

    def toggle_presentation_mode(self):
        self._shell.toggle_presentation(self)

    def set_presentation_chrome_hidden(self, hidden):
        """Hide document chrome while preserving its previous visibility."""
        if hidden:
            if hasattr(self, "_presentation_ui_state"):
                return
            self._presentation_ui_state = {
                "workspace_header": self._workspace_header is not None and not self._workspace_header.isHidden(),
                "sidebar": not self._sidebar_stack.isHidden(),
                "toolbar": not self._interaction_toolbar.isHidden(),
                "status": not self.statusBar().isHidden(),
                "search": not self._search_bar.isHidden(),
                "notes": not self._notes_dock.isHidden(),
            }
            self._sidebar_stack.hide()
            self._interaction_toolbar.hide()
            self.statusBar().hide()
            self._search_bar.hide()
            self._notes_dock.hide()
            if self._workspace_header is not None:
                self._workspace_header.hide()
            if self.doc is not None:
                QTimer.singleShot(0, self.zoom_page_fit)
        else:
            state = getattr(self, "_presentation_ui_state", None)
            if state is None:
                return
            self._sidebar_stack.setVisible(state["sidebar"])
            self._interaction_toolbar.setVisible(state["toolbar"])
            self.statusBar().setVisible(state["status"])
            self._search_bar.setVisible(state["search"])
            self._notes_dock.setVisible(state["notes"])
            if self._workspace_header is not None:
                self._workspace_header.setVisible(state["workspace_header"])
            del self._presentation_ui_state
            if self.doc is not None:
                QTimer.singleShot(0, self.zoom_fit)

    def on_wheel_flip(self, direction):
        """휠로 페이지 끝에 닿았을 때 다음/이전 장으로."""
        if self._shell.workspace_mode == "editor" or self._edit_mode:
            # 편집 중에는 페이지 바닥의 개체를 작업하며 휠을
            # 계속 쓴다. 경계에서 다음 장으로 넘어가지 않게 한다.
            self.view.reset_flip()
            return
        if self.doc is None:
            return
        if direction > 0 and self.page_index < self.doc.page_count - 1:
            self.next_page()
            self.view.verticalScrollBar().setValue(
                self.view.verticalScrollBar().minimum())
        elif direction < 0 and self.page_index > 0:
            self.prev_page()
            self.view.verticalScrollBar().setValue(
                self.view.verticalScrollBar().maximum())
        self.view.reset_flip()

    def _dispatch_click(self, pt):
        """canvas 클릭 라우팅 — 편집 모드면 편집, 아니면 기존(메모 열기 등)."""
        if self._edit_mode:
            self.edit_span_at(pt)
        else:
            self.on_canvas_clicked(pt)

    # --- 최근 파일 / 즐겨찾기 (열기는 셸의 탭으로) ---------------------

    def _rebuild_recent_menu(self):
        self._recent_menu.clear()
        paths = settings.recent_files()
        if not paths:
            act = self._recent_menu.addAction("(비어 있음)")
            act.setEnabled(False)
            return
        for p in paths:
            label = "%s  —  %s" % (os.path.basename(p), os.path.dirname(p))
            if len(label) > 100:
                label = label[:60] + "…" + label[-39:]
            act = self._recent_menu.addAction(label)
            act.setIcon(fluent_icon("open"))
            act.setToolTip(p)
            act.triggered.connect(lambda _c=False, p=p: self._shell.open_recent(p))
        self._recent_menu.addSeparator()
        clear_action = self._recent_menu.addAction(
            "목록 지우기", lambda _c=False: settings.clear_recent())
        clear_action.setIcon(fluent_icon("delete"))

    def _rebuild_fav_menu(self):
        self._fav_menu.clear()
        self._sync_favorite_action()
        if self.doc is not None:
            if settings.is_favorite(self.doc.path):
                action = self._fav_menu.addAction(
                    "현재 파일을 즐겨찾기에서 제거",
                    lambda _c=False: self._toggle_favorite())
                action.setIcon(fluent_icon("star_filled", "#0f6cbd"))
            else:
                action = self._fav_menu.addAction(
                    "★ 현재 파일을 즐겨찾기에 추가",
                    lambda _c=False: self._toggle_favorite())
                action.setIcon(fluent_icon("star"))
            self._fav_menu.addSeparator()
        favs = list(reversed(settings.favorites()))
        if not favs:
            act = self._fav_menu.addAction("(비어 있음)")
            act.setEnabled(False)
            return
        for p in favs:
            label = "%s  —  %s" % (os.path.basename(p), os.path.dirname(p))
            if len(label) > 100:
                label = label[:60] + "…" + label[-39:]
            act = self._fav_menu.addAction(label)
            act.setIcon(fluent_icon("open"))
            act.setToolTip(p)
            act.triggered.connect(lambda _c=False, p=p: self._shell.open_recent(p))

    def _sync_favorite_action(self):
        """현재 문서의 즐겨찾기 여부를 도구 모음에 반영한다."""
        if self.doc is None or not self.doc.path:
            self._favorite_act.setText(tr("즐겨찾기 추가"))
            self._favorite_act.setIcon(fluent_icon("star"))
            self._favorite_act.setToolTip(tr("PDF를 연 뒤 즐겨찾기에 추가할 수 있습니다"))
            self._favorite_act.setEnabled(False)
            return
        favorite = settings.is_favorite(self.doc.path)
        self._favorite_act.setEnabled(True)
        self._favorite_act.setText(tr(
            "즐겨찾기 해제" if favorite else "즐겨찾기 추가"))
        self._favorite_act.setIcon(fluent_icon(
            "star_filled" if favorite else "star",
            "#0f6cbd" if favorite else "#424242"))
        self._favorite_act.setToolTip(tr(
            "현재 PDF를 즐겨찾기에서 제거합니다" if favorite else
            "현재 PDF를 즐겨찾기에 추가합니다"))

    def _toggle_favorite(self):
        if self.doc is None:
            return
        if settings.is_favorite(self.doc.path):
            settings.remove_favorite(self.doc.path)
            self.statusBar().showMessage("즐겨찾기에서 제거됨", 3000)
        else:
            settings.add_favorite(self.doc.path)
            self.statusBar().showMessage("즐겨찾기에 추가됨", 3000)
        self._sync_favorite_action()
        self._shell.refresh_start_page()

    # --- 문서 로드/정리 ------------------------------------------------

    def open_path(self, path):
        """이 탭에 문서를 연다(탭 생성 직후 한 번). 실패하면 doc=None으로 둔다."""
        from .core import Document, PasswordRequired
        password = None
        while True:
            try:
                doc = Document(path, password, read_only=self.read_only,
                               annotations_enabled=self._shell.annotations_enabled,
                               isolated=self._shell.workspace_mode is not None)
                if self._shell.workspace_mode == "editor":
                    try:
                        doc.ensure_editable()
                    except Exception:
                        doc.close()
                        raise
                break
            except PasswordRequired:
                password, ok = QInputDialog.getText(
                    self, "암호 필요",
                    "이 PDF는 암호가 걸려 있습니다.\n비밀번호를 입력하세요:",
                    QLineEdit.Password)
                if not ok:
                    return
            except Exception as e:
                if is_illustrator_document(path):
                    message = localize(
                        "This Illustrator file cannot be opened. Only .ai "
                        "files saved with PDF compatibility enabled are supported.",
                        "이 Illustrator 파일은 열 수 없습니다. PDF 호환 옵션을 "
                        "켜고 저장한 .ai 파일만 지원합니다.")
                else:
                    message = "파일을 열 수 없습니다.\n\n%s" % e
                QMessageBox.critical(self, "열기 실패", message)
                return

        self._set_document(doc, path)

    @editing_command
    def open_snapshot(self, data, original_path):
        """다른 실행 창의 미저장 스냅샷을 원래 파일의 dirty 탭으로 연다."""
        from .core import Document
        try:
            doc = Document.from_snapshot(original_path, data)
        except Exception as e:
            QMessageBox.critical(
                self, "탭 이동 실패", "편집 중인 문서를 옮길 수 없습니다.\n\n%s" % e)
            return False
        self._set_document(doc, original_path)
        self.mark_dirty()
        return True

    def _set_document(self, doc, path):
        """파일/전송 스냅샷에 공통인 문서 탭 초기화를 한곳에서 수행한다."""
        self.doc = doc
        self._view_ready = False
        self.clear_navigation_history()
        self._restore_initial_view = bool(getattr(self, "_pending_view_state", None))
        self._initial_reading_state = (getattr(self, "_pending_view_state", None)
                                       or settings.reading_position(path))
        self._pending_view_state = None
        self.page_index = 0
        self._sync_favorite_action()
        self.thumbs.reset_pages(doc.page_count)
        self.bookmarks.set_bookmarks(doc.bookmarks())
        self._update_title()
        try:
            settings.push_recent(path)
        except OSError:
            pass  # Preferences must not invalidate an otherwise usable PDF.
        initial = self._initial_reading_state
        target = max(0, min(initial["page"], doc.page_count - 1)) if initial else 0
        if initial:
            self._two_page_mode = initial["two_page"]
            self._two_page_act.setChecked(self._two_page_mode)
        self._set_fit_zoom(target)
        self.show_page(target)
        # 탭이 실제 화면에 배치된 뒤 확정된 폭과 모니터 DPR로 다시 맞춘다.
        QTimer.singleShot(0, lambda d=doc: self.finish_initial_layout(d))
        self._schedule_thumbs()
        self._notes_changed()
        self._sync_annotation_access()
        if self.read_only:
            self.statusBar().showMessage(localize(
                "Read-only mode — document editing is disabled.",
                "읽기 전용 모드 — 문서 편집을 사용할 수 없습니다."), 6000)
            if self._shell.workspace_mode == "reader":
                self.statusBar().showMessage(localize(
                    "Reader — Ctrl+E opens this document in a separate editor.",
                    "읽기 모드 — Ctrl+E를 누르면 별도 편집 창에서 열립니다."), 6000)
            if doc.annotation_mode and doc.annotations_enabled:
                self.statusBar().showMessage(localize(
                    "Annotations enabled; autosave is " +
                    ("ON." if self._shell.autosave_annotations else "OFF (Ctrl+S to save)."),
                    "주석 사용 가능 · 자동저장 " +
                    ("켜짐" if self._shell.autosave_annotations else "꺼짐 (Ctrl+S로 저장)")), 6000)
        elif not doc.has_text(0):
            self.statusBar().showMessage(
                "텍스트 레이어가 없는 문서입니다 (스캔본) — 복사/검색은 OCR 후 가능", 6000)

    def prepare_close_doc(self):
        """화면에서 탭을 떼기 전에 타이머와 OCR을 즉시 중단한다."""
        if getattr(self, "_closing_doc", False):
            return
        self._closing_doc = True
        if self._page_grid is not None:
            self._page_grid.stop_rendering()
        stop_rendering = getattr(self.view, "stop_rendering", None)
        if stop_rendering is not None:
            stop_rendering()
        self._annotation_timer.stop()
        self.save_reading_position()
        self._position_timer.stop()
        self._zoom_render_timer.stop()
        self._recovery.clear()
        self._thumb_timer.stop()
        self._thumbnail_width_timer.stop()
        self._save_thumbnail_width()
        w = getattr(self, "_ocr_worker", None)
        if w is not None:
            try:
                w.cancel()
            except Exception:
                pass
        dlg = getattr(self, "_ocr_dlg", None)
        if dlg is not None:
            dlg.close()

    def close_doc(self):
        """탭 자원을 정리한다. UI 분리 후 호출해 느린 해제를 눈에 띄지 않게 한다."""
        self.prepare_close_doc()
        w = getattr(self, "_ocr_worker", None)
        if w is not None:
            try:
                if not w.wait(2000):
                    w.kill_process()
                    w.wait(1000)
            except Exception:
                pass
        if self.doc is not None:
            self.doc.close()
            self.doc = None
        self._sync_favorite_action()
        self._cache.clear()
        self.view.clear()
        self.thumbs.reset_pages(0)
        self.bookmarks.set_bookmarks([])
        self._reset_textsel()
        self._reset_annots()
        self._reset_edit()

    # --- 제목/상태 ----------------------------------------------------

    def tab_title(self):
        if self.doc is None:
            return "(빈 탭)"
        name = ("*" if self._dirty else "") + os.path.basename(self.doc.path)
        if self._shell.workspace_mode in ("reader", "editor"):
            mode = localize("Read", "읽기") if self.read_only else localize("Edit", "편집")
            devices = {self.view.rasterization_device(page)
                       for page in self.visible_document_pages()}
            device = next(iter(devices)) if len(devices) == 1 else "CPU+GPU"
            name += " [%s/%s]" % (mode, device or "CPU")
        elif self.read_only:
            name += localize(" [Read-only]", " [읽기 전용]")
        return name

    def _update_title(self):
        # 탭은 자식 창이라 setWindowTitle은 안 보이지만, 셸이 라벨/제목을
        # 갱신하도록 신호를 쏜다.
        self.title_changed.emit()

    def _on_render_device_changed(self):
        self._update_title()
        self._update_render_diagnostic()

    def _update_render_diagnostic(self):
        visible = settings.render_diagnostics()
        self._render_diagnostic_label.setVisible(visible)
        if not visible or self.doc is None or not hasattr(
                self.view, "render_diagnostic"):
            self._render_diagnostic_label.setText("")
            self._render_diagnostic_label.setToolTip("")
            return
        text, tooltip = _render_diagnostic_summary(
            self.view.render_diagnostic(self.page_index))
        self._render_diagnostic_label.setText(text)
        self._render_diagnostic_label.setToolTip(tooltip)

    def _update_page_label(self):
        if self.doc is None:
            self._page_label.setText("")
            self._page_size_label.setText("")
        else:
            width, height = self.doc.page_size(self.page_index)
            width_mm, height_mm = width * 25.4 / 72.0, height * 25.4 / 72.0
            self._page_size_label.setText(
                "%g × %g mm" % (round(width_mm, 1), round(height_mm, 1)))
            visible = self.visible_document_pages()
            if len(visible) > 1:
                self._page_label.setText("%d–%d / %d" % (
                    visible[0] + 1, visible[-1] + 1, self.doc.page_count))
            else:
                self._page_label.setText("%d / %d" % (
                    self.page_index + 1, self.doc.page_count))
            if hasattr(self, "_zoom_input"):
                self._zoom_input.blockSignals(True)
                scale = self._actual_size_scale()
                self._zoom_input.setRange(
                    max(1, round(self.view.ZOOM_MIN / scale * 100)),
                    round(self.view.ZOOM_MAX / scale * 100))
                self._zoom_input.setValue(round(self.zoom_percent()))
                self._zoom_input.blockSignals(False)
        if hasattr(self, "_render_diagnostic_label"):
            self._update_render_diagnostic()
        self._update_title()

    def open_current_location(self):
        """현재 PDF를 선택한 상태로 Windows 탐색기를 연다."""
        if self.doc is None:
            return
        path = os.path.abspath(self.doc.path)
        if not os.path.exists(path):
            QMessageBox.warning(
                self, "파일 위치 열기", "현재 파일을 찾을 수 없습니다.\n%s" % path)
            return
        try:
            subprocess.Popen(["explorer.exe", "/select,", os.path.normpath(path)])
        except OSError as error:
            QMessageBox.warning(
                self, "파일 위치 열기",
                "Windows 탐색기를 열 수 없습니다.\n\n%s" % error)

    # --- 도움말/정보/OCR 설정 (탭 메뉴에서 호출) -----------------------

    def show_help(self):
        from .help import show_help
        show_help(self)

    def check_default_app(self):
        _show_default_app_settings(self)

    def show_about(self):
        QMessageBox.about(self, "정보", "%s %s" % (APP_NAME, APP_VERSION))

    def show_licenses(self):
        show_licenses(self)

    @editing_command
    def show_ocr_engine_dialog(self):
        from . import settings, vl
        _kind, desc = vl.runtime_summary()
        installed = vl.vl_installed()
        cur = settings.ocr_engine()

        box = QMessageBox(self)
        box.setWindowTitle("AI 고품질 OCR 설정")
        box.setIcon(QMessageBox.Question)
        box.setText(localize(
            "Choose an OCR engine.\n\n"
            "• RapidOCR: lightweight and fast; recognizes Korean and English on a CPU.\n"
            "• High-quality AI (VL): better for low-quality scans and complex layouts.\n"
            "  Requires torch + transformers (several GB), a model (about 2 GB), and preferably a GPU.\n\n"
            "Current accelerator: %s\n"
            "VL status: %s\n"
            "Current selection: %s",
            "OCR 엔진을 선택하세요.\n\n"
            "• RapidOCR: 가볍고 빠르며 CPU에서 한국어와 영어를 인식합니다.\n"
            "• AI 고품질(VL): 저품질 스캔과 복잡한 레이아웃에 강합니다.\n"
            "  torch+transformers(수 GB), 모델(약 2GB)과 GPU 사용을 권장합니다.\n\n"
            "현재 가속기: %s\n"
            "VL 상태: %s\n"
            "현재 선택: %s")
            % (desc, vl.install_hint(),
               localize("High-quality AI (VL)", "AI 고품질(VL)")
               if cur == "vl" else "RapidOCR"))
        b_basic = box.addButton("RapidOCR로", QMessageBox.AcceptRole)
        b_basic.setIcon(fluent_icon("ocr"))
        b_vl = box.addButton("AI 고품질로", QMessageBox.AcceptRole)
        b_vl.setIcon(fluent_icon("ai"))
        b_cancel = box.addButton("취소", QMessageBox.RejectRole)
        b_cancel.setIcon(fluent_icon("close"))
        box.exec_()
        clicked = box.clickedButton()
        if clicked is b_basic:
            settings.set_ocr_engine("rapidocr")
            self.statusBar().showMessage("OCR 엔진: RapidOCR", 4000)
        elif clicked is b_vl:
            level, _specs, reason = vl.vl_suitability()
            if level in ("poor", "marginal"):
                ret = QMessageBox.question(
                    self, "VL 사양 확인",
                    localize(
                        "%s\n\nUse High-quality AI (VL) anyway?",
                        "%s\n\n그래도 AI 고품질(VL)로 설정할까요?") % reason,
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if ret != QMessageBox.Yes:
                    self.statusBar().showMessage("RapidOCR 유지", 4000)
                    return
            settings.set_ocr_engine("vl")
            if installed:
                self.statusBar().showMessage("OCR 엔진: AI 고품질(VL)", 4000)
            elif vl.runtime_present() and vl.can_download():
                ret = QMessageBox.question(
                    self, "VL 모델 다운로드",
                    localize(
                        "High-quality AI (VL) is selected.\n"
                        "Download the model (about 2 GB) now?\n\n"
                        "RapidOCR will be used until the download completes.",
                        "AI 고품질(VL)을 선택했습니다.\n"
                        "모델(약 2GB)을 지금 다운로드할까요?\n\n"
                        "다운로드 전까지 OCR은 RapidOCR로 동작합니다."),
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
                if ret == QMessageBox.Yes:
                    self._download_vl_models()
            else:
                QMessageBox.information(
                    self, "VL 준비 필요",
                    localize(
                        "High-quality AI (VL) is selected.\n"
                        "Missing: %s\n\n"
                        "RapidOCR will be used until the required components are installed.\n\n"
                        "Setup:\n1) In Command Prompt, run\n"
                        "   pip install torch torchvision transformers "
                        "huggingface_hub\n"
                        "   (use a CUDA-enabled torch build for GPU acceleration)\n"
                        "2) Reopen this dialog and choose High-quality AI to download the model.",
                        "AI 고품질(VL)을 선택했습니다.\n"
                        "빠진 것: %s\n\n"
                        "필요한 구성요소를 설치할 때까지 OCR은 RapidOCR로 동작합니다.\n\n"
                        "설치 방법:\n1) 명령 프롬프트에서\n"
                        "   pip install torch torchvision transformers "
                        "huggingface_hub\n"
                        "   (GPU 사용 시 CUDA 지원 torch 빌드)\n"
                        "2) 이 대화상자를 다시 열어 AI 고품질을 선택하면 모델을 내려받습니다.")
                    % vl.install_hint())

    def _download_vl_models(self):
        from . import vl

        class _Dl(QThread):
            failed = pyqtSignal(str)

            def run(self):
                try:
                    vl.download_models()
                except Exception as e:
                    self.failed.emit(str(e))

        dlg = QProgressDialog(
            "VL 모델 다운로드 중... (약 2GB, 네트워크에 따라 수 분)",
            None, 0, 0, self)
        dlg.setWindowTitle("VL 모델 다운로드")
        dlg.setCancelButton(None)
        dlg.setMinimumDuration(0)

        th = _Dl(self)
        self._vl_dl_error = None

        def _on_fail(msg):
            self._vl_dl_error = msg

        def _on_done():
            dlg.close()
            th.deleteLater()
            if self._vl_dl_error:
                QMessageBox.critical(
                    self, "다운로드 실패",
                    "VL 모델 다운로드에 실패했습니다.\n\n%s" % self._vl_dl_error)
            elif vl.vl_installed():
                self.statusBar().showMessage(
                    "VL 모델 설치 완료 — OCR 엔진: AI 고품질(VL)", 6000)
            else:
                QMessageBox.warning(
                    self, "다운로드 미완료",
                    "다운로드가 끝났지만 모델 확인에 실패했습니다.\n"
                    "다시 시도해 주세요.")

        th.failed.connect(_on_fail)
        th.finished.connect(_on_done)
        th.start()
        dlg.exec_()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape and self._shell.presentation_active:
            self._shell.toggle_presentation(self)
        elif ev.key() == Qt.Key_Escape and self._note_mode:
            self.cancel_note_mode()
        elif ev.key() == Qt.Key_Escape and self._search_bar.isVisible():
            self.hide_search()
        elif ev.key() in (Qt.Key_Down, Qt.Key_Right):
            self.next_page()
        elif ev.key() in (Qt.Key_Up, Qt.Key_Left):
            self.prev_page()
        else:
            super().keyPressEvent(ev)


def show_licenses(parent):
    from .license_dialog import show_licenses as show_license_dialog
    show_license_dialog(parent)

# ======================================================================
# AppWindow — 탭들을 담는 셸
# ======================================================================

class AppWindow(QMainWindow, WindowWorkspaceMixin):
    """Embeddable window; read_only is fixed for this window's lifetime."""

    @property
    def read_only(self):
        return self._read_only

    @property
    def annotations_enabled(self):
        return self._annotations_enabled

    @property
    def autosave_annotations(self):
        return self._autosave_annotations

    @property
    def access_policy(self):
        return (self.read_only, self.annotations_enabled, self.autosave_annotations)

    def __init__(self, updates_enabled=False, *, read_only=False,
                 annotations_enabled=None, autosave_annotations=True,
                 workspace_mode=None):
        super().__init__()
        self._window_chrome = None
        self._workspace_mode = workspace_mode
        self._read_only, self._annotations_enabled = workspace_policy(
            workspace_mode, read_only, annotations_enabled)
        self._autosave_annotations = bool(autosave_annotations)
        application = QApplication.instance()
        if application is not None:
            install_i18n(application)
            # 페이지 뷰와 스크롤 영역이 화살표 키를 먼저 소비하므로, 발표
            # 중에는 셸이 자식 위젯의 키 입력을 선행해서 받는다.
            application.installEventFilter(self)
        self.updates_enabled = bool(updates_enabled)
        self._recovery_store = (
            getattr(application, "_spdf_recovery_store", None)
            if (self.updates_enabled or self.workspace_mode is not None) and
            (not self.read_only or self.workspace_mode == "reader") else None)
        self.setWindowTitle(self.workspace_title())
        self.resize(1100, 800)
        self.setAcceptDrops(True)
        self._update_service = (
            GitHubUpdateService(APP_VERSION, language=settings.ui_language())
            if self.updates_enabled else None)
        if self._update_service is not None and not getattr(
                application, "_spdf_update_cleanup_started", False):
            application._spdf_update_cleanup_started = True
            # The installer may still hold its own executable when the
            # post-install launch starts sPDF, so retry after it has exited.
            self._update_service.cleanup_downloads()
            QTimer.singleShot(2000, self._update_service.cleanup_downloads)
            QTimer.singleShot(10000, self._update_service.cleanup_downloads)
        self._update_worker = None
        self._available_update = None
        self._presentation_tab = None
        self._presentation_window_state = None

        self._start_page = StartPage()
        self._start_page.open_file.connect(self.open_in_tab)
        self._start_page.browse.connect(self.open_dialog)
        self._start_page.back_to_doc.connect(self._show_tabs_if_any)

        if workspace_mode in ("reader", "editor"):
            from .window_chrome import DocumentTabs, WindowChrome
            self.setWindowFlag(Qt.FramelessWindowHint, True)
            self.setMinimumSize(520, 320)
            self._tabs = DocumentTabs(TransferTabBar())
            self._window_chrome = WindowChrome(self, self._tabs.tabBar())
            self._tabs.currentChanged.connect(lambda _index:
                self._window_chrome.brand.setVisible(self._tabs.count() == 0))
            self.setMenuWidget(self._window_chrome)
        else:
            self._tabs = QTabWidget()
            self._tabs.setTabBar(TransferTabBar(self._tabs))
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.setDocumentMode(True)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._tabs.tabCloseRequested.connect(
            lambda i: self.close_tab(self._tabs.widget(i)))

        self._stack = QStackedWidget()
        self._stack.addWidget(self._start_page)  # 0
        self._stack.addWidget(self._tabs)        # 1
        self.setCentralWidget(self._stack)

        # 시작 페이지(탭 없음)일 때 쓰는 최소 메뉴바. 탭이 활성화되면 그 탭의
        # 메뉴바로 교체(reparent)한다.
        self._shell_menubar = self._build_shell_menu()
        self._switch_menubar(self._shell_menubar)
        self._show_start()
        if self.updates_enabled and not any(
                getattr(window, "_auto_update_started", False)
                for window in _app_windows):
            self._auto_update_started = True
            if settings.automatic_update_check_due():
                QTimer.singleShot(5000, self._run_automatic_update_check)

        self._fluent_backdrop_attempted = False
        self._fluent_backdrop_applied = False
        translate_tree(self)

        if self._recovery_store is not None and not getattr(
                application, "_spdf_recovery_prompted", False):
            application._spdf_recovery_prompted = True
            QTimer.singleShot(400, lambda: self.show_recovery(automatic=True))

    def show_recovery(self, automatic=False):
        if self.isHidden():
            return
        if getattr(self, "_recovery_dialog_open", False):
            return
        if automatic and getattr(self, "_recovery_prompt_handled", False):
            return
        if self.workspace_mode == "reader":
            if self._recovery_store is None:
                return
            try:
                available = self._recovery_store.available()
            except OSError as error:
                QMessageBox.warning(self, tr("미저장 작업 복구"), str(error))
                return
            if not available:
                if not automatic:
                    QMessageBox.information(self, tr("미저장 작업 복구"), localize(
                        "There are no recovery copies from interrupted sessions.",
                        "이전 실행에서 남은 복구용 사본이 없습니다."))
                return
            # Let the independent editor claim the abandoned recovery sessions.
            for folder, lock in list(self._recovery_store._locks.items()):
                if folder != self._recovery_store.session:
                    lock.unlock()
                    del self._recovery_store._locks[folder]
            return self.open_editor(recovery=True)
        if self.read_only:
            return
        if self.isHidden():
            return
        from .recovery_ui import show_recovery_dialog
        self._recovery_dialog_open = True
        self._recovery_prompt_handled = True
        try:
            show_recovery_dialog(self, automatic=automatic)
        finally:
            self._recovery_dialog_open = False

    def showEvent(self, event):
        super().showEvent(event)
        if not self._fluent_backdrop_attempted:
            from .windows_integration import apply_fluent_window_backdrop

            self._fluent_backdrop_attempted = True
            self._fluent_backdrop_applied = apply_fluent_window_backdrop(self)

    def nativeEvent(self, event_type, message):
        if getattr(self, "_window_chrome", None) is not None:
            from .window_chrome import native_frame_event
            result = native_frame_event(self, message)
            if result is not None:
                return True, result
        return super().nativeEvent(event_type, message)

    def menuBar(self):
        chrome = getattr(self, "_window_chrome", None)
        if chrome is not None and chrome.menubar is not None:
            return chrome.menubar
        return super().menuBar()

    @property
    def presentation_active(self):
        return self._presentation_tab is not None

    def _sync_view_mode_actions(self):
        for index in range(self._tabs.count()):
            tab = self._tabs.widget(index)
            tab._presentation_act.setChecked(tab is self._presentation_tab)
            tab._full_screen_act.setChecked(
                self.isFullScreen() and not self.presentation_active)

    def toggle_full_screen(self):
        if self.workspace_mode == "editor":
            return
        if self.presentation_active:
            self.toggle_presentation(self._presentation_tab)
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
        self._sync_view_mode_actions()

    def toggle_presentation(self, tab=None):
        if self.workspace_mode == "editor":
            return
        if self.presentation_active:
            active = self._presentation_tab
            state = self._presentation_window_state or {}
            active.set_presentation_chrome_hidden(False)
            self.menuBar().setVisible(state.get("menubar", True))
            self._tabs.tabBar().setVisible(state.get("tabbar", True))
            if self._window_chrome is not None:
                self._window_chrome.caption.show()
            self._presentation_tab = None
            self._presentation_window_state = None
            if state.get("fullscreen", False):
                self.showFullScreen()
            else:
                self.showNormal()
            self._sync_view_mode_actions()
            return

        tab = tab or self._tabs.currentWidget()
        if tab is None or tab.doc is None:
            return
        self._presentation_window_state = {
            "fullscreen": self.isFullScreen(),
            "menubar": not self.menuBar().isHidden(),
            "tabbar": not self._tabs.tabBar().isHidden(),
        }
        self._presentation_tab = tab
        tab.set_presentation_chrome_hidden(True)
        self.menuBar().hide()
        self._tabs.tabBar().hide()
        if self._window_chrome is not None:
            self._window_chrome.caption.hide()
        self.showFullScreen()
        self._sync_view_mode_actions()

    def _handle_presentation_key(self, event):
        if not self.presentation_active or event.modifiers() not in (
                Qt.NoModifier, Qt.KeypadModifier):
            return False
        if event.key() == Qt.Key_Escape:
            self.toggle_presentation(self._presentation_tab)
        elif event.key() in (Qt.Key_Right, Qt.Key_Down):
            self._presentation_tab.next_page()
        elif event.key() in (Qt.Key_Left, Qt.Key_Up):
            self._presentation_tab.prev_page()
        else:
            return False
        event.accept()
        return True

    def eventFilter(self, watched, event):
        inside_window = watched is self or (
            isinstance(watched, QWidget) and self.isAncestorOf(watched))
        if inside_window and event.type() in (
                QEvent.DragEnter, QEvent.DragMove, QEvent.Drop):
            if self._handle_document_drop(watched, event):
                return True
        if event.type() == QEvent.KeyPress and (
                watched is self or
                isinstance(watched, QWidget) and self.isAncestorOf(watched)):
            if self._handle_presentation_key(event):
                return True
        return super().eventFilter(watched, event)

    @staticmethod
    def _document_drop_paths(mime):
        if not mime.hasUrls():
            return []
        paths = [url.toLocalFile() for url in mime.urls() if url.isLocalFile()]
        return [path for path in paths
                if os.path.isfile(path) and is_supported_document(path)]

    @staticmethod
    def _page_organizer_owns_drop(watched):
        if not isinstance(watched, QWidget):
            return False
        from .page_organizer import PageOrganizerDialog, PageOrganizerList
        widget = watched
        while widget is not None:
            if isinstance(widget, (PageOrganizerDialog, PageOrganizerList)):
                return True
            widget = widget.parentWidget()
        return False

    def _handle_document_drop(self, watched, event):
        # The page organizer deliberately interprets PDF drops as page insert.
        if self._page_organizer_owns_drop(watched):
            return False
        paths = self._document_drop_paths(event.mimeData())
        if not paths:
            return False
        if event.type() == QEvent.Drop:
            for path in paths:
                self.open_in_tab(path)
        event.setDropAction(Qt.CopyAction)
        event.accept()
        return True

    def keyPressEvent(self, event):
        if self._handle_presentation_key(event):
            return
        super().keyPressEvent(event)

    def new_window(self):
        """Keep this window's embedding policy when opening another window."""
        return new_window(force_new=True, updates_enabled=self.updates_enabled,
                          read_only=self.read_only,
                          annotations_enabled=self.annotations_enabled,
                          autosave_annotations=self.autosave_annotations,
                          workspace_mode=self.workspace_mode)

    def _build_shell_menu(self):
        mb = QMenuBar(self)
        m = mb.addMenu("파일(&F)")
        m.addAction(_make_action(
            self, "열기...", "Ctrl+O", self.open_dialog, "open"))
        m.addAction(_make_action(
            self, "새 탭", "Ctrl+T", self.open_dialog, "new_tab"))
        m.addAction(_make_action(
            self, "새 창", "Ctrl+Shift+N", self.new_window,
            "new_window"))
        m.addAction(_make_action(
            self, "이미지를 PDF로...", None,
            self.images_to_pdf_dialog, "pages"))
        if self.workspace_mode == "reader":
            m.addAction(_make_action(
                self, localize("Open editor", "편집 창 열기"), "Ctrl+E",
                self.open_editor, "edit"))
        elif self.workspace_mode == "editor":
            m.addAction(_make_action(self, localize("Open reader", "읽기 창 열기"),
                                     None, self.open_reader, "open"))
        m.addSeparator()
        if self._recovery_store is not None:
            m.addAction(_make_action(
                self, "미저장 작업 복구...", None, self.show_recovery, "undo"))
        m.addAction(_make_action(
            self, "종료", "Ctrl+Q", self.request_exit, "power"))
        h = mb.addMenu("도움말(&H)")
        h.addAction(_make_action(
            self, "사용법", "F1", self._shell_help, "help"))
        if self.updates_enabled:
            h.addAction(_make_action(
                self, "업데이트 확인...", None,
                lambda: self.check_for_updates(True), "update"))
        h.addAction(_make_action(
            self, "PDF 기본 프로그램 / 브라우저 설정...", None,
            lambda: _show_default_app_settings(self), "settings"))
        self._add_language_menu(h)
        h.addAction(_make_action(self, "오픈소스 라이선스", None,
                                 lambda: show_licenses(self), "license"))
        h.addAction(_make_action(
            self, "정보", None, self._shell_about, "info"))
        return mb

    def _add_language_menu(self, parent_menu):
        if self.workspace_mode is not None:
            startup = parent_menu.addMenu(localize("Startup workspace", "시작 모드"))
            modes = QActionGroup(startup)
            modes.setExclusive(True)
            for mode, label in (("reader", localize("Reader first", "리더 우선")),
                                ("editor", localize("Editor first", "편집 우선"))):
                action = startup.addAction(label)
                action.setCheckable(True)
                action.setChecked(settings.startup_workspace() == mode)
                modes.addAction(action)
                action.triggered.connect(lambda _checked, mode=mode: self._select_startup_workspace(mode))
            if self.workspace_mode == "reader":
                resident = startup.addAction(localize(
                    "Keep reader in system tray", "리더를 트레이에 상주"))
                resident.setCheckable(True)
                resident.setChecked(settings.reader_resident())
                resident.setToolTip(localize(
                    "Close documents on exit, but keep reader modules ready. OCR is not kept running.",
                    "닫을 때 문서와 캐시는 정리하고 리더 모듈만 대기합니다. OCR은 상주하지 않습니다."))
                resident.triggered.connect(self._set_reader_resident)
        if self.updates_enabled:
            renderer = parent_menu.addMenu(tr("화면 렌더러"))
            renderer.setIcon(fluent_icon("settings"))
            renderers = QActionGroup(renderer)
            renderers.setExclusive(True)
            d2d = probe_d2d_backend()
            gpu_available = (
                d2d.available and d2d.driver == "hardware" and
                os.environ.get("SPDF_DISABLE_GPU", "").lower() not in
                ("1", "true", "yes"))
            for mode, label in (("auto", tr("자동 (권장)")),
                                ("gpu", "GPU (Direct2D)"),
                                ("cpu", "CPU (PyMuPDF)")):
                action = renderer.addAction(label)
                action.setCheckable(True)
                action.setChecked(settings.render_backend() == mode)
                if mode == "gpu" and not gpu_available:
                    action.setEnabled(False)
                    action.setToolTip(localize(
                        "Direct2D hardware rendering is unavailable.",
                        "Direct2D 하드웨어 렌더링을 사용할 수 없습니다."))
                renderers.addAction(action)
                action.triggered.connect(
                    lambda _checked=False, selected=mode:
                    self._select_render_backend(selected))
            renderer.addSeparator()
            diagnostic = renderer.addAction(localize(
                "Rendering diagnostics", "렌더링 진단 표시"))
            diagnostic.setCheckable(True)
            diagnostic.setChecked(settings.render_diagnostics())
            diagnostic.setToolTip(localize(
                "Show the actual rendering path and CPU fallback reason for the current page.",
                "현재 페이지의 실제 렌더링 경로와 CPU 대체 사유를 표시합니다."))
            diagnostic.triggered.connect(self._set_render_diagnostics)
            cache_menu = renderer.addMenu(localize("Disk cache limit", "디스크 캐시 최대 용량"))
            cache_group = QActionGroup(cache_menu)
            cache_group.setExclusive(True)
            for size in settings.DISK_CACHE_SIZES:
                label = localize("Off", "사용 안 함") if size == 0 else "%d MB" % size
                action = cache_menu.addAction(label)
                action.setCheckable(True)
                action.setChecked(settings.disk_cache_mb() == size)
                cache_group.addAction(action)
                action.triggered.connect(
                    lambda _checked=False, selected=size: self._set_disk_cache_size(selected))
        menu = parent_menu.addMenu(tr("언어"))
        menu.setIcon(fluent_icon("settings"))
        group = QActionGroup(menu)
        group.setExclusive(True)
        current = settings.ui_language()
        for code, label in (("en", "English"), ("ko", tr("한국어"))):
            action = QAction(label, menu)
            action.setCheckable(True)
            action.setChecked(code == current)
            action.setIcon(fluent_icon("settings"))
            action.triggered.connect(
                lambda _checked=False, selected=code:
                self._select_ui_language(selected))
            group.addAction(action)
            menu.addAction(action)
        return menu

    def _select_startup_workspace(self, mode):
        try:
            settings.set_startup_workspace(mode)
        except OSError as error:
            self.statusBar().showMessage(str(error), 8000)

    def _set_disk_cache_size(self, size):
        try:
            settings.set_disk_cache_mb(size)
            from .scene_disk_cache import trim
            trim()
        except OSError as error:
            self._show_shell_status(str(error), 8000)

    def _set_reader_resident(self, enabled):
        try:
            settings.set_reader_resident(enabled)
        except OSError as error:
            self._show_shell_status(str(error), 8000)
            return
        from .reader_resident import configure_residency
        if getattr(QApplication.instance(), "_spdf_standalone_reader", False):
            if not configure_residency(enabled, updates_enabled=self.updates_enabled):
                self._show_shell_status(localize(
                    "Tray residency is unavailable; closing will exit normally.",
                    "트레이 상주를 사용할 수 없어 닫을 때 정상 종료합니다."), 8000)

    def request_exit(self):
        resident = getattr(QApplication.instance(), "_spdf_reader_resident", None)
        if resident is not None and self.workspace_mode == "reader":
            resident.quit()
        else:
            self.close()

    def _select_render_backend(self, mode):
        if mode == settings.render_backend():
            return
        try:
            settings.set_render_backend(mode)
        except OSError as error:
            self.statusBar().showMessage(str(error), 8000)
            return
        QMessageBox.information(
            self, tr("화면 렌더러 변경"),
            tr("화면 렌더러 변경 사항은 sPDF를 다시 실행하면 적용됩니다."))

    def _set_render_diagnostics(self, enabled):
        try:
            settings.set_render_diagnostics(enabled)
        except OSError as error:
            self.statusBar().showMessage(str(error), 8000)
            return
        for index in range(self._tabs.count()):
            tab = self._tabs.widget(index)
            if isinstance(tab, DocumentTab):
                tab._update_render_diagnostic()

    def _select_ui_language(self, language_code):
        if language_code == settings.ui_language():
            return
        settings.set_ui_language(language_code)
        QMessageBox.information(
            self, tr("언어 변경"),
            tr("언어 변경 사항은 sPDF를 다시 실행하면 적용됩니다."))

    def _shell_help(self):
        from .help import show_help
        show_help(self)

    def _shell_about(self):
        QMessageBox.about(self, "정보", "%s %s" % (APP_NAME, APP_VERSION))

    # --- GitHub Releases 업데이트 ------------------------------------

    def _run_automatic_update_check(self):
        # 시작 시각을 먼저 기록해 네트워크 오류나 강제 종료가 있어도 다음
        # 실행 때마다 확인을 반복하지 않는다. 수동 확인은 이 제한과 무관하다.
        settings.mark_automatic_update_check()
        self.check_for_updates(False)

    def check_for_updates(self, manual=True):
        if not self.updates_enabled:
            return False
        if self._update_worker is not None and self._update_worker.isRunning():
            if manual:
                self._show_shell_status("업데이트를 확인하고 있습니다…", 3000)
            return
        if manual:
            self._show_shell_status("GitHub에서 최신 버전을 확인하는 중입니다…")
        worker = UpdateCheckWorker(self._update_service, self)
        worker.completed.connect(
            lambda update: self._update_check_completed(update, manual))
        worker.failed.connect(
            lambda message: self._update_check_failed(message, manual))
        worker.finished.connect(self._update_check_finished)
        self._update_worker = worker
        worker.start()
        return True

    def _update_check_completed(self, update, manual):
        self._clear_shell_status()
        if update is None:
            if manual:
                QMessageBox.information(
                    self, "업데이트 확인",
                    "현재 sPDF %s가 최신 버전입니다." % APP_VERSION)
            return
        self._available_update = update
        if manual:
            self._show_available_update()
        else:
            answer = QMessageBox.question(
                self, "sPDF 업데이트",
                "sPDF %s 업데이트가 있습니다.\n자세히 볼까요?"
                % update.version)
            if answer == QMessageBox.Yes:
                self._show_available_update()

    def _update_check_failed(self, message, manual):
        self._clear_shell_status()
        if manual:
            QMessageBox.warning(self, "업데이트 확인 실패", message)

    def _update_check_finished(self):
        worker = self._update_worker
        self._update_worker = None
        if worker is not None:
            worker.deleteLater()

    def _show_available_update(self):
        update = self._available_update
        if update is None:
            return
        self._available_update = None
        dialog = UpdateDialog(self._update_service, update, self)
        dialog.install_requested.connect(self._launch_update_installer)
        dialog.exec_()

    def _launch_update_installer(self, path):
        answer = QMessageBox.question(
            self, "업데이트 설치",
            "설치 프로그램을 실행합니다.\n"
            "저장하지 않은 문서를 확인한 뒤 sPDF를 종료합니다. 계속할까요?")
        if answer != QMessageBox.Yes:
            return
        for window in list(_app_windows):
            for index in range(window._tabs.count()):
                if not window._tabs.widget(index).maybe_save():
                    return
        try:
            self._update_service.launch_installer(path)
        except UpdateError as error:
            QMessageBox.warning(self, "업데이트 실행 실패", str(error))
            return
        QApplication.instance().quit()

    # --- 화면 전환 -----------------------------------------------------

    def _show_start(self):
        self._switch_menubar(self._shell_menubar)
        self._start_page.refresh()
        self._start_page.set_current_doc(None)
        self._stack.setCurrentIndex(0)
        self.setWindowTitle(self.workspace_title())

    def _show_tabs(self):
        self._stack.setCurrentIndex(1)

    def _show_tabs_if_any(self):
        if self._tabs.count() > 0:
            self._show_tabs()

    def refresh_start_page(self):
        self._start_page.refresh()

    def _document_status_bar(self):
        """Return the active document bar without creating an outer empty bar."""
        if not hasattr(self, "_tabs"):
            return None
        tab = self._tabs.currentWidget()
        return tab.statusBar() if isinstance(tab, DocumentTab) else None

    def _show_shell_status(self, message, timeout=0):
        bar = self._document_status_bar()
        if bar is not None:
            bar.showMessage(message, timeout)

    def _clear_shell_status(self):
        bar = self._document_status_bar()
        if bar is not None:
            bar.clearMessage()

    @editing_command
    def images_to_pdf_dialog(self):
        from .conversions import IMAGE_OPEN_FILTER, images_to_pdf
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("이미지를 PDF로"), "", tr(IMAGE_OPEN_FILTER))
        if not paths:
            return
        first = os.path.splitext(paths[0])[0] + ".pdf"
        output, _ = QFileDialog.getSaveFileName(
            self, tr("이미지를 PDF로"), first, "PDF files (*.pdf)")
        if not output:
            return
        if not output.lower().endswith(".pdf"):
            output += ".pdf"
        try:
            count = images_to_pdf(paths, output)
        except Exception as error:
            QMessageBox.critical(self, tr("이미지를 PDF로"), str(error))
            return
        self.open_in_tab(output)
        self._show_shell_status(localize(
            "Created a %d-page PDF: %s" % (count, output),
            "%d페이지 PDF 생성됨: %s" % (count, output)), 6000)

    # --- 파일 열기 (탭으로) --------------------------------------------

    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "PDF/Illustrator 파일 열기", "", tr(DOCUMENT_OPEN_FILTER))
        if path:
            self.open_in_tab(path)

    def open_recent(self, path):
        if not os.path.exists(path):
            QMessageBox.warning(self, "파일 없음",
                                "파일이 이동되었거나 삭제되었습니다:\n%s" % path)
            settings.remove_recent(path)
            self.refresh_start_page()
            return
        self.open_in_tab(path)

    def open_in_tab(self, path):
        """파일을 탭으로 연다. 이미 열려 있으면 그 탭으로 전환(중복 방지)."""
        existing = self._find_open_tab(path)
        if existing is not None:
            self._tabs.setCurrentWidget(existing)
            self._show_tabs()
            return existing
        tab = DocumentTab(self)
        tab._opening_path = path
        self._connect_tab(tab)
        idx = self._tabs.addTab(tab, "불러오는 중...")
        self._tabs.setCurrentIndex(idx)
        self._show_tabs()
        # 레이아웃이 끝난 뒤 열어야 '창 너비 맞춤' 배율이 정확하다.
        QTimer.singleShot(0, lambda: self._load_into(tab, path))
        return tab

    def _find_open_tab(self, path):
        target = os.path.normcase(os.path.abspath(path))
        for i in range(self._tabs.count()):
            tab = self._tabs.widget(i)
            tab_path = tab.doc.path if tab.doc else getattr(tab, "_opening_path", None)
            if tab_path and os.path.normcase(os.path.abspath(tab_path)) == target:
                return tab
        return None

    @editing_command
    def open_snapshot_in_tab(self, snapshot_path, original_path):
        """별도 sPDF 프로세스가 넘긴 미저장 PDF를 읽고 임시 파일을 회수한다."""
        if self._find_open_tab(original_path) is not None:
            return False
        try:
            with open(snapshot_path, "rb") as stream:
                data = stream.read()
            os.remove(snapshot_path)
        except OSError as e:
            QMessageBox.critical(
                self, "탭 이동 실패", "임시 문서를 읽을 수 없습니다.\n\n%s" % e)
            return False

        tab = DocumentTab(self)
        self._connect_tab(tab)
        index = self._tabs.addTab(tab, "옮기는 중...")
        self._tabs.setCurrentIndex(index)
        self._show_tabs()
        if not tab.open_snapshot(data, original_path):
            self._remove_tab(tab)
            return False
        self._sync_tab_title(tab)
        return True

    def _load_into(self, tab, path):
        if self._tabs.indexOf(tab) < 0 or getattr(tab, "_closing_doc", False):
            return
        tab.open_path(path)
        tab._opening_path = None
        tab.load_finished.emit(tab.doc is not None)
        if tab.doc is None:
            self._remove_tab(tab)  # 열기 실패/취소 → 빈 탭 제거
        else:
            self._sync_tab_title(tab)
            if self.workspace_mode == "editor":
                tab.open_page_editor()

    # --- 탭 제목/전환/닫기 ---------------------------------------------

    def _connect_tab(self, tab):
        """이동 전 창에 남은 제목 신호를 끊고 현재 셸에 다시 연결한다."""
        old_slot = getattr(tab, "_shell_title_slot", None)
        if old_slot is not None:
            try:
                tab.title_changed.disconnect(old_slot)
            except TypeError:
                pass
        tab._shell = self
        slot = lambda t=tab, shell=self: shell._sync_tab_title(t)
        tab._shell_title_slot = slot
        tab.title_changed.connect(slot)

    def _adopt_tab(self, source, tab, index):
        """같은 프로세스의 다른 창에서 문서 위젯과 편집 상태를 그대로 받는다."""
        if (source.access_policy != self.access_policy or
                source.workspace_mode != self.workspace_mode or
                source.updates_enabled != self.updates_enabled):
            return False
        source_index = source._tabs.indexOf(tab)
        if source_index < 0:
            return
        title = tab.tab_title()
        tooltip = tab.doc.path if tab.doc else ""
        source._tabs.removeTab(source_index)

        self._connect_tab(tab)
        index = max(0, min(index, self._tabs.count()))
        new_index = self._tabs.insertTab(index, tab, title)
        self._tabs.setTabToolTip(new_index, tooltip)
        self._tabs.setCurrentIndex(new_index)
        self._show_tabs()
        self.show()
        self.raise_()
        self.activateWindow()
        source._close_if_empty_after_move()
        return True

    def _receive_tab_drop(self, payload, index):
        """탭 막대와 빈 창 시작 화면이 함께 쓰는 창 간 이동 처리."""
        if not payload or not payload.get("path"):
            return False
        read_only = bool(payload.get("read_only", False))
        policy = (read_only, bool(payload.get("annotations_enabled", not read_only)),
                  bool(payload.get("autosave_annotations", True)))
        if (policy != self.access_policy or
                payload.get("workspace_mode") != self.workspace_mode):
            return False
        entry = _dragged_tabs.get(payload.get("token")) \
            if payload.get("pid") == os.getpid() else None
        if entry is not None:
            source, tab = entry
            if source is self:
                return False
            return self._adopt_tab(source, tab, index)
        if payload.get("dirty"):
            # 프로세스 경계를 넘으면 QWidget 대신 현재 PDF 스냅샷을 복원한다.
            return self.open_snapshot_in_tab(
                payload.get("snapshot"), payload.get("path"))
        self.open_in_tab(payload.get("path"))
        return True

    def _finish_external_tab_move(self, tab):
        """다른 프로세스가 저장된 파일을 받은 뒤 원본 탭 자원을 정리한다."""
        self._remove_tab(tab)
        self._close_if_empty_after_move()

    def _close_if_empty_after_move(self):
        if self._tabs.count() == 0:
            # 드롭 이벤트/QDrag 중에 창을 파괴하면 Qt가 소스 객체를 다시
            # 참조할 수 있으므로 이벤트 루프로 돌아간 뒤 닫는다.
            QTimer.singleShot(0, self.close)

    def _sync_tab_title(self, tab):
        i = self._tabs.indexOf(tab)
        if i < 0:
            return
        name = tab.tab_title()
        self._tabs.setTabText(i, name)
        self._tabs.setTabToolTip(i, tab.doc.path if tab.doc else "")
        if self._tabs.currentWidget() is tab:
            self.setWindowTitle(
                "%s — %s" % (name, APP_NAME) if tab.doc else self.workspace_title())

    def _on_tab_changed(self, i):
        if i < 0:
            self._show_start()
            return
        tab = self._tabs.widget(i)
        self._switch_menubar(tab._menubar)
        self._sync_tab_title(tab)

    def _switch_menubar(self, menubar):
        if self._window_chrome is not None:
            self._window_chrome.set_menubar(menubar)
            return
        # QMainWindow deletes a replaced menu bar unless ownership is released.
        # Inactive tabs still own their menus and must be able to reuse them.
        previous = self.menuWidget()
        if previous is menubar:
            return
        if previous is not None:
            previous.hide()
            previous.setParent(None)
        self.setMenuBar(menubar)
        menubar.show()

    def close_tab(self, tab):
        if tab is None or not tab.maybe_save():
            return
        self._remove_tab(tab)

    def _remove_tab(self, tab):
        if tab is self._presentation_tab:
            self.toggle_presentation(tab)
        # OCR 프로세스에는 즉시 종료 신호를 보내되, wait와 대용량 렌더 캐시
        # 해제는 탭이 사라진 화면이 한 프레임 그려진 뒤 처리한다.
        tab.prepare_close_doc()
        i = self._tabs.indexOf(tab)
        if i >= 0:
            self._tabs.removeTab(i)
        tab.hide()
        mb = getattr(tab, "_menubar", None)
        if self._tabs.count() == 0:
            self._show_start()
        QTimer.singleShot(
            16, lambda closed_tab=tab, menu=mb:
            self._dispose_removed_tab(closed_tab, menu))

    @staticmethod
    def _dispose_removed_tab(tab, menubar):
        worker = getattr(tab, "_ocr_worker", None)
        if worker is not None:
            # OCR 작업 스레드를 UI에서 기다리지 않는다. 정상 종료가 늦으면
            # 프로세스만 강제 종료하고 finished 신호에서 최종 정리한다.
            worker.finished.connect(
                lambda closed_tab=tab, menu=menubar:
                AppWindow._finalize_removed_tab(closed_tab, menu))
            if worker.isRunning():
                QTimer.singleShot(
                    2000, lambda active_worker=worker:
                    AppWindow._kill_ocr_worker_if_running(active_worker))
                return
        AppWindow._finalize_removed_tab(tab, menubar)

    @staticmethod
    def _kill_ocr_worker_if_running(worker):
        try:
            if worker.isRunning():
                worker.kill_process()
        except RuntimeError:
            # 정상 종료 뒤 부모 탭과 함께 이미 삭제된 QThread일 수 있다.
            pass

    @staticmethod
    def _finalize_removed_tab(tab, menubar):
        tab.close_doc()
        if menubar is not None:
            menubar.setParent(None)
            menubar.deleteLater()  # 셸로 reparent됐을 수 있어 따로 정리한다
        tab.deleteLater()

    # --- 종료/드롭 -----------------------------------------------------

    def closeEvent(self, ev):
        for i in range(self._tabs.count()):
            tab = self._tabs.widget(i)
            self._tabs.setCurrentIndex(i)
            if not tab.maybe_save():
                ev.ignore()
                return
        resident = getattr(QApplication.instance(), "_spdf_reader_resident", None)
        if resident is not None and resident.park(self):
            ev.ignore()
            return
        # 저장 여부가 모두 확정됐으면 무거운 이미지/워커 정리보다 창을 먼저
        # 감춰 사용자가 X 버튼의 반응을 즉시 느끼게 한다.
        self.hide()
        # 창의 X 버튼으로 종료할 때도 탭 닫기와 같은 경로를 거쳐 OCR 자식
        # 프로세스와 열린 문서를 확실히 정리한다.
        for i in range(self._tabs.count()):
            self._tabs.widget(i).close_doc()
        super().closeEvent(ev)
        if ev.isAccepted() and self._update_worker is not None and \
                self._update_worker.isRunning():
            self._update_worker.requestInterruption()
            self._update_worker.wait(1000)
        if ev.isAccepted() and self in _app_windows:
            _app_windows.remove(self)

    def dragEnterEvent(self, ev):
        if self._tabs.tabBar()._can_accept(ev.mimeData()):
            ev.setDropAction(Qt.MoveAction)
            ev.accept()
            return
        if self._document_drop_paths(ev.mimeData()):
            ev.setDropAction(Qt.CopyAction)
            ev.accept()

    def dropEvent(self, ev):
        payload = _decode_tab_drag(ev.mimeData())
        if payload is not None:
            if self._receive_tab_drop(payload, self._tabs.count()):
                ev.setDropAction(Qt.MoveAction)
                ev.accept()
            else:
                ev.ignore()
            return
        paths = self._document_drop_paths(ev.mimeData())
        for path in paths:
            self.open_in_tab(path)
        if paths:
            ev.setDropAction(Qt.CopyAction)
            ev.accept()


# ======================================================================
# 진입점 — 여러 AppWindow가 탭을 서로 주고받을 수 있다
# ======================================================================

_app_windows = []


def new_window(path=None, force_new=False, updates_enabled=None, *,
               read_only=False, annotations_enabled=None, autosave_annotations=True,
               workspace_mode=None):
    """Open an embedded viewer/editor. ``read_only=True`` disables body edits.

    Read-only mode retains viewing, search, selection, copy and printing.
    The default remains an editor. Windows with a different access policy are
    never reused. Set the policy when opening a window, not on an open document.
    In read-only mode, annotations_enabled=True enables sidecar annotations;
    autosave_annotations=False makes their saving manual (Ctrl+S).
    Standalone workspaces opt in with workspace_mode="reader" or "editor".
    Omit it in embedded hosts to preserve their existing policy and menus.
    """
    read_only, annotation_flag = workspace_policy(
        workspace_mode, read_only, annotations_enabled)
    policy = (bool(read_only), annotation_flag, bool(autosave_annotations))
    updates_enabled = bool(updates_enabled)
    application = QApplication.instance()
    if application is not None:
        # Embedded hosts use the same English UI without enabling sPDF updates.
        install_i18n(application)
    window = next((candidate for candidate in _app_windows
                   if candidate.access_policy == policy
                   and candidate.workspace_mode == workspace_mode
                   and candidate.updates_enabled == updates_enabled),
                  None)
    if force_new or window is None:
        window = AppWindow(updates_enabled=updates_enabled, read_only=read_only,
                           annotations_enabled=annotation_flag,
                           autosave_annotations=autosave_annotations,
                           workspace_mode=workspace_mode)
        if _app_windows:
            previous = _app_windows[-1]
            window.move(previous.x() + 30, previous.y() + 30)
        _app_windows.append(window)
        translate_tree(window)
        window.show()
    else:
        window.showNormal() if window.isMinimized() else window.show()
        window.raise_()
        window.activateWindow()
    if path:
        QTimer.singleShot(0, lambda: window.open_in_tab(path))
    return window
