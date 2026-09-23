"""ViewerMixin — 썸네일/메인뷰/줌/페이지 이동.

렌더 캐시는 현재 페이지 ±2만 유지한다(설계 §3.1). 대용량 스캔본에서
전 페이지를 들고 있으면 RAM이 터지기 때문.
"""

from PyQt5.QtCore import QPointF, Qt, QTimer, QUrl
from PyQt5.QtGui import QDesktopServices, QTransform
from PyQt5.QtWidgets import QApplication, QMessageBox

from . import settings
from .icons import fluent_icon
from .i18n import localize, tr
from .widgets import qimage_from_render
from .navigation import NavigationMixin

CACHE_RADIUS = 2  # 현재 페이지 기준 앞뒤로 유지할 페이지 수
MIN_RENDER_PIXEL_RATIO = 1.0
MAX_RENDER_SUPERSAMPLE = 2.0


def render_pixel_ratio(widget, zoom=1.0):
    """Use display DPR plus adaptive supersampling at low zoom levels."""
    supersample = max(
        MIN_RENDER_PIXEL_RATIO,
        min(MAX_RENDER_SUPERSAMPLE, MAX_RENDER_SUPERSAMPLE / max(1.0, zoom)))
    ratios = [supersample, float(widget.devicePixelRatioF())]
    window = widget.window().windowHandle() if widget.window() else None
    if window is not None and window.screen() is not None:
        ratios.append(float(window.screen().devicePixelRatio()))
    app = QApplication.instance()
    if app is not None and app.primaryScreen() is not None:
        ratios.append(float(app.primaryScreen().devicePixelRatio()))
    return max(ratios)


class ViewerMixin(NavigationMixin):
    def _init_viewer_state(self):
        self.doc = None
        self.page_index = 0
        self._two_page_mode = False
        self._cache = {}  # (page, zoom) -> QImage
        self._init_navigation()
        # 썸네일 스크롤 중 매번 렌더하면 버벅이므로 멈춘 뒤 한 번만 그린다.
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(80)
        self._thumb_timer.timeout.connect(self._render_visible_thumbs)
        # Continuous wheel / fine zoom events used to synchronously rasterize
        # the whole page for every step. Keep the old image briefly and render
        # only the final requested scale.
        self._zoom_render_timer = QTimer(self)
        self._zoom_render_timer.setSingleShot(True)
        self._zoom_render_timer.setInterval(90)
        self._zoom_render_timer.timeout.connect(self._render_current)
        self._pending_thumbnail_width = None
        self._thumbnail_width_timer = QTimer(self)
        self._thumbnail_width_timer.setSingleShot(True)
        self._thumbnail_width_timer.setInterval(250)
        self._thumbnail_width_timer.timeout.connect(
            self._save_thumbnail_width)

    # --- 페이지 표시 -------------------------------------------------

    def show_page(self, index):
        if self.doc is None:
            return
        index = max(0, min(index, self.doc.page_count - 1))
        if index != self.page_index:
            self.remember_navigation()
        self.page_index = index
        self._render_current()
        self._trim_cache()
        if self.thumbs.currentRow() != index:
            self.thumbs.blockSignals(True)
            self.thumbs.setCurrentRow(index)
            self.thumbs.blockSignals(False)
        self.thumbs.set_spread_pages(self.visible_document_pages())
        self.bookmarks.select_page(index)
        self._update_page_label()
        self.schedule_reading_position()

    def _render_current(self):
        self._zoom_render_timer.stop()
        if self.doc is None:
            return
        if self.is_editor_overview():
            self.refresh_editor_overview()
            return
        render_reader = getattr(self.view, "render_document", None)
        if render_reader is not None:
            render_reader(self.doc, self.visible_document_pages(), self.page_index)
            return
        pixel_ratio = render_pixel_ratio(self.view, self.view.zoom)
        pages = self.visible_document_pages()
        images = []
        for page in pages:
            key = (
                page,
                round(self.view.zoom, 3),
                round(pixel_ratio, 2),
            )
            img = self._cache.get(key)
            if img is None:
                img = qimage_from_render(
                    *self.doc.render(page, self.view.zoom * pixel_ratio),
                    device_pixel_ratio=pixel_ratio,
                )
                self._cache[key] = img
            images.append((page, img))
        self.view.set_images(images, self.page_index)

    def visible_document_pages(self):
        if self.doc is None:
            return []
        if not self._two_page_mode:
            return [self.page_index]
        first = self.page_index - self.page_index % 2
        return list(range(first, min(first + 2, self.doc.page_count)))

    def _trim_cache(self):
        """현재 페이지에서 멀어진 렌더는 버린다 — 메모리 상한 유지."""
        lo, hi = self.page_index - CACHE_RADIUS, self.page_index + CACHE_RADIUS
        for key in [k for k in self._cache if not (lo <= k[0] <= hi)]:
            del self._cache[key]

    def on_zoom_changed(self, _zoom):
        if self.doc is None:
            return
        preview_zoom = getattr(self.view, "preview_zoom", None)
        if preview_zoom is not None:
            if self.view.canvas.zoom != _zoom:
                preview_zoom(_zoom)
            self._update_page_label()
            return
        # 줌이 바뀌면 이전 배율 캐시는 쓸모없다.
        self._cache.clear()
        self._zoom_render_timer.start()
        self._update_page_label()

    def set_zoom(self, zoom):
        zoom = max(self.view.ZOOM_MIN, min(self.view.ZOOM_MAX, zoom))
        if zoom == self.view.zoom:
            self._update_page_label()
            return
        self.view.zoom = zoom
        self.on_zoom_changed(zoom)

    def zoom_in(self):
        self.set_zoom(self.view.zoom * 1.25)

    def zoom_out(self):
        self.set_zoom(self.view.zoom / 1.25)

    def zoom_in_fine(self):
        self.set_zoom_percent(self.zoom_percent() + 1)

    def zoom_out_fine(self):
        self.set_zoom_percent(self.zoom_percent() - 1)

    def _actual_size_scale(self):
        # PDF points are 1/72 inch. Qt reports physical DPI in device-
        # independent coordinates; DPR is applied separately by rendering.
        return max(1.0, float(self.view.viewport().physicalDpiX())) / 72.0

    def zoom_percent(self):
        return self.view.zoom / self._actual_size_scale() * 100.0

    def set_zoom_percent(self, percent):
        self.set_zoom(percent / 100.0 * self._actual_size_scale())

    def rotate_reader_cw(self):
        return self._rotate_reader(90)

    def rotate_reader_ccw(self):
        return self._rotate_reader(-90)

    def _rotate_reader(self, degrees):
        if self.doc is None or self._shell.workspace_mode != "reader":
            return False
        self.view.rotate_page_view(self.page_index, degrees)
        self.thumbs.invalidate(self.page_index)
        self.zoom_fit()
        self._schedule_thumbs()
        self.statusBar().showMessage(localize(
            "View rotated — the PDF file is unchanged.",
            "화면만 회전했습니다 — PDF 파일은 변경되지 않습니다."), 3500)
        return True

    def _displayed_page_size(self, index):
        size = getattr(self.view, "displayed_page_size", None)
        return size(self.doc, index) if size is not None else self.doc.page_size(index)

    def _set_fit_zoom(self, index):
        """렌더 없이 줌 값만 창 너비에 맞춘다 — 문서를 열 때 이걸로 먼저
        배율을 정한 뒤 show_page를 부르면 첫 페이지를 한 번만 렌더한다
        (예전엔 zoom 1.0으로 그리고 fit으로 또 그려서 두 배로 느렸다)."""
        pages = ([index] if not self._two_page_mode else
                 list(range(index - index % 2,
                            min(index - index % 2 + 2,
                                self.doc.page_count))))
        widths = [self._displayed_page_size(page)[0] for page in pages]
        avail = self.view.viewport().width() - 24  # 여백/스크롤바 몫
        if len(widths) > 1:
            avail -= 16.0
        pw = sum(widths)
        if pw > 0 and avail > 0:
            self.view.zoom = max(self.view.ZOOM_MIN,
                                 min(self.view.ZOOM_MAX, avail / pw))

    def zoom_fit(self):
        """창 너비에 맞춘다."""
        if self.doc is None:
            return
        self._set_fit_zoom(self.page_index)
        self.on_zoom_changed(self.view.zoom)

    def zoom_page_fit(self):
        """현재 페이지 전체가 문서 화면 안에 들어오도록 맞춘다."""
        if self.doc is None:
            return
        pages = self.visible_document_pages()
        sizes = [self._displayed_page_size(page) for page in pages]
        page_width = sum(width for width, _height in sizes)
        page_height = max(height for _width, height in sizes)
        available_width = self.view.viewport().width() - 24
        if len(sizes) > 1:
            available_width -= 16.0
        available_height = self.view.viewport().height() - 24
        if page_width <= 0 or page_height <= 0:
            return
        if available_width <= 0 or available_height <= 0:
            return
        self.view.zoom = max(
            self.view.ZOOM_MIN,
            min(
                self.view.ZOOM_MAX,
                available_width / page_width,
                available_height / page_height,
            ),
        )
        self.on_zoom_changed(self.view.zoom)

    def finish_initial_layout(self, document):
        """창 배치가 끝난 실제 폭으로 맞춤 배율과 HiDPI 이미지를 확정한다."""
        if (self.doc is not document or self.doc is None
                or getattr(self, "_closing_doc", False)
                or getattr(self, "_view_ready", False)):
            return
        if self._initial_reading_state is not None:
            state = self._initial_reading_state
            self._initial_reading_state = None
            # Explicit transfers/refreshes preserve the live view; only an
            # ordinary file open replaces the saved zoom with fit-width.
            if getattr(self, "_restore_initial_view", False):
                self._restore_initial_view = False
                self.restore_view_state(state)
                self._view_ready = True
                return
            self._two_page_mode = bool(state.get("two_page", False))
            self._two_page_act.setChecked(self._two_page_mode)
            self.page_index = max(0, min(
                self.doc.page_count - 1, int(state.get("page", 0))))
        old_zoom = self.view.zoom
        self._set_fit_zoom(self.page_index)
        if self.view.zoom != old_zoom:
            self._cache.clear()
        self.show_page(self.page_index)
        self._update_page_label()
        self.update_thumbnail_viewport_marker()
        self._view_ready = True

    def refresh_page(self, index):
        """페이지 내용이 바뀌었을 때(주석 등) 렌더 캐시와 썸네일을 무효화."""
        self.doc.invalidate_render(index)
        for key in [k for k in self._cache if k[0] == index]:
            del self._cache[key]
        if index == self.page_index:
            self._render_current()
        self.thumbs.invalidate(index)
        self._schedule_thumbs()

    def next_page(self):
        if self._two_page_mode:
            self.show_page(self.page_index - self.page_index % 2 + 2)
        else:
            self.show_page(self.page_index + 1)

    def prev_page(self):
        if self._two_page_mode:
            self.show_page(max(0, self.page_index - self.page_index % 2 - 2))
        else:
            self.show_page(self.page_index - 1)

    def set_two_page_mode(self, enabled):
        enabled = bool(enabled)
        if enabled == self._two_page_mode:
            return
        self._two_page_mode = enabled
        if hasattr(self, "_two_page_act"):
            self._two_page_act.setChecked(enabled)
        if self.doc is not None:
            self._set_fit_zoom(self.page_index)
            self._cache.clear()
            self._render_current()
            self.thumbs.set_spread_pages(self.visible_document_pages())
            self._clear_selection()
            self._apply_search_overlay()
            if self._edit_mode:
                self._show_edit_boxes()
            self.update_thumbnail_viewport_marker()
            self._update_page_label()

    def toggle_two_page_mode(self):
        self.set_two_page_mode(not self._two_page_mode)

    # --- 왼쪽 탐색 패널 --------------------------------------------

    def set_sidebar_mode(self, mode, persist=True):
        if mode not in settings.SIDEBAR_MODES:
            mode = settings.DEFAULT_SIDEBAR_MODE
        self._sidebar_mode = mode
        if mode == "none":
            self._sidebar_stack.hide()
        else:
            self._sidebar_stack.setCurrentWidget(
                self.thumbs if mode == "thumbnails" else self.bookmarks)
            self._sidebar_stack.show()
            width = settings.thumbnail_width()
            self._viewer_splitter.setSizes(
                [width, max(1, self._viewer_splitter.width() - width)])
            if mode == "thumbnails":
                self._schedule_thumbs()
        for key, action in getattr(self, "_sidebar_actions", {}).items():
            action.setChecked(key == mode)
        labels = {
            "none": tr("없음"), "thumbnails": tr("페이지 미리보기"),
            "bookmarks": tr("책갈피"),
        }
        if hasattr(self, "_sidebar_cycle_act"):
            self._sidebar_cycle_act.setToolTip(
                localize(
                    "Left panel: %s (click to cycle)",
                    "왼쪽 패널: %s (클릭하여 전환)") % labels[mode])
            self._sidebar_cycle_act.setIcon(fluent_icon({
                "none": "close", "thumbnails": "pages",
                "bookmarks": "notes",
            }[mode]))
        if hasattr(self, "_sidebar_button"):
            icon_name = {
                "none": "close", "thumbnails": "pages",
                "bookmarks": "notes",
            }[mode]
            self._sidebar_button.setIcon(fluent_icon(icon_name))
            self._sidebar_button.setToolTip(localize(
                "Choose the left panel (current: %s)",
                "왼쪽 패널 선택 (현재: %s)") % labels[mode])
        if persist:
            settings.set_sidebar_mode(mode)

    def cycle_sidebar_mode(self):
        modes = settings.SIDEBAR_MODES
        current = getattr(self, "_sidebar_mode", settings.sidebar_mode())
        self.set_sidebar_mode(modes[(modes.index(current) + 1) % len(modes)])

    # --- PDF 링크 ---------------------------------------------------

    def activate_link_at(self, point):
        """Open an internal or web link only after an explicit Ctrl+click."""
        if self.doc is None:
            return
        link = self.doc.link_at(self.page_index, point.x(), point.y())
        if link is None:
            self.statusBar().showMessage(tr("이 위치에는 링크가 없습니다"), 2500)
            return
        if link["kind"] == "goto" and link["page"] >= 0:
            target_page = min(link["page"], self.doc.page_count - 1)
            if target_page == self.page_index:
                self.remember_navigation()
            self.show_page(target_page)
            if link["to"] is not None:
                width, height = self.doc.page_size(target_page)
                x, y = link["to"]
                center = getattr(self.view, "center_on_document_point", None)
                if center is not None:
                    QTimer.singleShot(0, lambda: center(QPointF(x, y)))
                elif width > 0 and height > 0:
                    QTimer.singleShot(
                        0, lambda: self.view.center_on_page_fraction(
                            QPointF(x / width, y / height)))
            return
        if link["kind"] == "uri" and link["uri"]:
            url = QUrl(link["uri"])
            if url.scheme().lower() not in ("http", "https", "mailto"):
                QMessageBox.warning(
                    self, tr("지원하지 않는 링크"), localize(
                        "This link type is blocked for safety.\n\n%s"
                        % link["uri"],
                        "안전을 위해 이 링크 형식은 열지 않습니다.\n\n%s"
                        % link["uri"]))
                return
            QDesktopServices.openUrl(url)
            return
        QMessageBox.information(
            self, tr("지원하지 않는 링크"), localize(
                "PDF links that launch another file or program are blocked "
                "for safety.",
                "다른 파일이나 프로그램을 실행하는 PDF 링크는 안전을 위해 "
                "열지 않습니다."))

    # --- 썸네일 ------------------------------------------------------

    def _schedule_thumbs(self):
        self._thumb_timer.start()

    def _render_visible_thumbs(self):
        """보이는 항목 중 아직 안 그린 것만 렌더(레이지, 설계 §3.1)."""
        if self.doc is None or self.is_editor_overview():
            return
        width = self.thumbs.thumbnail_width()
        visible = self.thumbs.visible_rows()
        for row in visible:
            if self.thumbs.is_rendered(row, width):
                continue
            pw, _ = self._displayed_page_size(row)
            zoom = width / pw if pw else 0.2
            pixel_ratio = render_pixel_ratio(self.thumbs)
            image = qimage_from_render(
                *self.doc.render(row, zoom * pixel_ratio),
                device_pixel_ratio=pixel_ratio)
            rotation = getattr(self.view, "page_rotation", lambda _page: 0)(row)
            if rotation:
                image = image.transformed(QTransform().rotate(rotation))
            self.thumbs.set_thumb(
                row, image,
                rendered_width=width,
            )
        if visible:
            self.thumbs.evict_thumbnails_outside(
                max(0, visible[0] - 4),
                min(self.doc.page_count - 1, visible[-1] + 4))
        self.update_thumbnail_viewport_marker()

    def on_thumbnail_width_changed(self, _width):
        """기존 아이콘은 유지하고 리사이즈가 멈추면 새 폭으로 교체한다."""
        self._schedule_thumbs()

    def update_thumbnail_viewport_marker(self):
        if self.doc is None:
            self.thumbs.set_viewport_marker(-1, None)
            return
        self.thumbs.set_viewport_marker(
            self.page_index, self.view.visible_page_rect())

    def navigate_from_thumbnail(self, page, point):
        """썸네일에서 찍은 페이지 위치를 메인 화면 중앙에 표시한다."""
        if self.doc is None:
            return
        if page != self.page_index:
            self.show_page(page)
        else:
            self.remember_navigation()
        self.view.center_on_page_fraction(point)

    def on_thumbnail_splitter_moved(self, _pos, index):
        """사용자가 놓은 썸네일 패널 너비를 잦은 디스크 쓰기 없이 기억한다."""
        if index != 1:
            return
        if self._sidebar_stack.isHidden():
            return
        self._pending_thumbnail_width = self._sidebar_stack.width()
        self._thumbnail_width_timer.start()

    def _save_thumbnail_width(self):
        if self._pending_thumbnail_width is None:
            return
        settings.set_thumbnail_width(self._pending_thumbnail_width)
        self._pending_thumbnail_width = None
