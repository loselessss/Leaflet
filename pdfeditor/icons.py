"""Fluent 스타일의 해상도 독립 선형 아이콘."""

import math


AVAILABLE_ICONS = frozenset({
    "add_file", "ai", "back", "chevron_down", "chevron_up", "close",
    "copy", "delete", "download", "edit", "external", "extract",
    "fit_page", "fit_width", "fullscreen",
    "hand", "help", "highlight", "info", "license", "merge", "new_tab",
    "new_window", "note", "notes", "ocr", "open", "pages", "power",
    "presentation", "print", "recent", "redo", "rotate_ccw", "rotate_cw", "save", "save_as",
    "image", "object_select", "rectangle", "search", "select_all", "settings", "split", "star", "star_filled",
    "text_select", "two_page", "undo", "update", "zoom_in", "zoom_out",
})


# Windows 11의 실제 Segoe Fluent Icons 코드 포인트. 문서 편집 전용처럼
# 시스템 글꼴에 직접 대응하는 기호가 없는 항목만 아래 QPainter 폴백을 쓴다.
FLUENT_GLYPHS = {
    "add_file": 0xE710,       # Add
    "ai": 0xE945,             # LightningBolt
    "back": 0xE72B,           # Back
    "chevron_down": 0xE70D,
    "chevron_up": 0xE70E,
    "close": 0xE711,          # Cancel
    "copy": 0xE8C8,
    "delete": 0xE74D,
    "download": 0xE896,
    "edit": 0xE70F,
    "external": 0xE8A7,      # OpenInNewWindow
    "extract": 0xE8AD,       # Go
    "hand": 0xE927,           # Swipe
    "help": 0xE897,
    "highlight": 0xE7E6,
    "info": 0xE946,
    "license": 0xE8A6,        # ProtectedDocument
    "merge": 0xE8B6,          # ImportAll
    "new_tab": 0xE7C3,        # Page
    "new_window": 0xE78B,
    "note": 0xE70B,           # QuickNote
    "notes": 0xE8FD,          # BulletedList
    "ocr": 0xE8FE,            # Scan
    "open": 0xE8E5,           # OpenFile
    "pages": 0xE89A,          # TwoPage
    "power": 0xE7E8,
    "print": 0xE749,
    "recent": 0xE823,
    "redo": 0xE7A6,
    "save": 0xE74E,
    "save_as": 0xE792,
    "search": 0xE721,
    "select_all": 0xE8B3,
    "settings": 0xE713,
    "split": 0xE8A9,          # ViewAll
    "star": 0xE734,
    "star_filled": 0xE735,
    "text_select": 0xE933,    # IBeam
    "undo": 0xE7A7,
    "update": 0xE895,         # Sync
    "zoom_in": 0xE8A3,
    "zoom_out": 0xE71F,
}


_SYSTEM_ICON_FONT = None


def _system_icon_font():
    """설치된 Windows 심볼 글꼴을 한 번만 탐색한다."""
    global _SYSTEM_ICON_FONT
    if _SYSTEM_ICON_FONT is None:
        from PyQt5.QtGui import QFontDatabase

        families = set(QFontDatabase().families())
        if "Segoe Fluent Icons" in families:
            _SYSTEM_ICON_FONT = "Segoe Fluent Icons"
        elif "Segoe MDL2 Assets" in families:
            _SYSTEM_ICON_FONT = "Segoe MDL2 Assets"
        else:
            _SYSTEM_ICON_FONT = ""
    return _SYSTEM_ICON_FONT


def _font_icon(codepoint, color, size):
    """Windows 심볼 글꼴의 글리프를 고해상도 QIcon으로 렌더링한다."""
    from PyQt5.QtCore import QRect, Qt
    from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

    ratio = 2
    pixmap = QPixmap(size * ratio, size * ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    painter.setPen(QColor(color))
    font = QFont(_system_icon_font())
    font.setPixelSize(size * ratio)
    painter.setFont(font)
    painter.drawText(
        QRect(0, 0, size * ratio, size * ratio),
        Qt.AlignCenter,
        chr(codepoint),
    )
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return QIcon(pixmap)


def _star_points(QPointF):
    points = []
    for index in range(10):
        angle = math.radians(-90 + index * 36)
        radius = 7.2 if index % 2 == 0 else 3.2
        points.append(QPointF(
            10 + math.cos(angle) * radius,
            10 + math.sin(angle) * radius))
    return points


def fluent_icon(name, color="#424242", size=20):
    """지정한 이름의 Fluent 선형 QIcon을 고해상도로 그린다."""
    if name not in AVAILABLE_ICONS:
        raise ValueError("알 수 없는 Fluent 아이콘: %s" % name)

    font_family = _system_icon_font()
    codepoint = FLUENT_GLYPHS.get(name)
    if font_family and codepoint is not None:
        return _font_icon(codepoint, color, size)

    from PyQt5.QtCore import QPointF, QRectF, Qt
    from PyQt5.QtGui import (
        QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap,
        QPolygonF,
    )

    ratio = 2
    pixmap = QPixmap(size * ratio, size * ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.scale(size * ratio / 20.0, size * ratio / 20.0)
    pen = QPen(QColor(color), 1.55, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    def line(x1, y1, x2, y2):
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    if name == "open":
        path = QPainterPath(QPointF(2.5, 6.0))
        path.lineTo(7.5, 6.0)
        path.lineTo(9.1, 7.6)
        path.lineTo(17.5, 7.6)
        path.lineTo(16.2, 15.5)
        path.lineTo(2.5, 15.5)
        path.closeSubpath()
        painter.drawPath(path)
        line(3.2, 6.0, 3.2, 4.5)
        line(3.2, 4.5, 8.0, 4.5)
        line(8.0, 4.5, 9.5, 6.0)
    elif name == "back":
        line(12.5, 4.0, 6.5, 10.0)
        line(6.5, 10.0, 12.5, 16.0)
    elif name in ("chevron_up", "chevron_down"):
        if name == "chevron_up":
            line(5.0, 12.5, 10.0, 7.5)
            line(10.0, 7.5, 15.0, 12.5)
        else:
            line(5.0, 7.5, 10.0, 12.5)
            line(10.0, 12.5, 15.0, 7.5)
    elif name == "close":
        line(5.0, 5.0, 15.0, 15.0)
        line(15.0, 5.0, 5.0, 15.0)
    elif name == "hand":
        path = QPainterPath(QPointF(5.8, 10.2))
        path.lineTo(5.8, 7.0)
        path.cubicTo(5.8, 5.7, 7.4, 5.7, 7.4, 7.0)
        path.lineTo(7.4, 4.8)
        path.cubicTo(7.4, 3.5, 9.0, 3.5, 9.0, 4.8)
        path.lineTo(9.0, 7.0)
        path.lineTo(9.0, 4.0)
        path.cubicTo(9.0, 2.8, 10.7, 2.8, 10.7, 4.0)
        path.lineTo(10.7, 7.0)
        path.lineTo(10.7, 4.8)
        path.cubicTo(10.7, 3.7, 12.3, 3.7, 12.3, 4.9)
        path.lineTo(12.3, 7.6)
        path.cubicTo(12.7, 6.5, 14.3, 6.8, 14.3, 8.0)
        path.lineTo(14.3, 11.5)
        path.cubicTo(14.3, 15.0, 12.2, 17.0, 9.4, 17.0)
        path.cubicTo(7.1, 17.0, 5.9, 15.7, 4.8, 13.8)
        path.lineTo(3.4, 11.5)
        path.cubicTo(2.8, 10.5, 4.0, 9.5, 4.9, 10.4)
        path.lineTo(6.3, 11.9)
        painter.drawPath(path)
    elif name == "text_select":
        line(7.0, 5.0, 13.0, 5.0)
        line(10.0, 5.0, 10.0, 15.0)
        line(7.5, 15.0, 12.5, 15.0)
        line(3.0, 6.0, 3.0, 3.0)
        line(3.0, 3.0, 6.0, 3.0)
        line(14.0, 3.0, 17.0, 3.0)
        line(17.0, 3.0, 17.0, 6.0)
        line(3.0, 14.0, 3.0, 17.0)
        line(3.0, 17.0, 6.0, 17.0)
        line(14.0, 17.0, 17.0, 17.0)
        line(17.0, 17.0, 17.0, 14.0)
    elif name in ("star", "star_filled"):
        polygon = QPolygonF(_star_points(QPointF))
        if name == "star_filled":
            painter.setBrush(QBrush(QColor(color)))
        painter.drawPolygon(polygon)
    elif name == "search":
        painter.drawEllipse(QRectF(3.0, 3.0, 10.5, 10.5))
        line(12.0, 12.0, 17.0, 17.0)
    elif name in ("add_file", "new_tab"):
        painter.drawRoundedRect(QRectF(4.0, 2.5, 10.5, 15.0), 1.2, 1.2)
        if name == "add_file":
            line(14.0, 12.5, 14.0, 18.0)
            line(11.2, 15.3, 16.8, 15.3)
        else:
            line(7.0, 10.0, 11.5, 10.0)
            line(9.25, 7.75, 9.25, 12.25)
    elif name == "delete":
        painter.drawRoundedRect(QRectF(5.2, 6.2, 9.6, 11.0), 1.2, 1.2)
        line(3.8, 5.0, 16.2, 5.0)
        line(7.3, 5.0, 8.0, 3.0)
        line(8.0, 3.0, 12.0, 3.0)
        line(12.0, 3.0, 12.7, 5.0)
        line(8.2, 8.5, 8.2, 14.5)
        line(11.8, 8.5, 11.8, 14.5)
    elif name == "download":
        line(10.0, 2.5, 10.0, 12.3)
        line(6.3, 8.8, 10.0, 12.5)
        line(10.0, 12.5, 13.7, 8.8)
        path = QPainterPath(QPointF(3.5, 13.0))
        path.lineTo(3.5, 16.5)
        path.lineTo(16.5, 16.5)
        path.lineTo(16.5, 13.0)
        painter.drawPath(path)
    elif name == "external":
        painter.drawRoundedRect(QRectF(3.0, 6.0, 11.0, 11.0), 1.2, 1.2)
        line(9.0, 3.0, 17.0, 3.0)
        line(17.0, 3.0, 17.0, 11.0)
        line(17.0, 3.0, 9.0, 11.0)
    elif name in ("save", "save_as"):
        path = QPainterPath(QPointF(3.0, 3.0))
        path.lineTo(14.0, 3.0)
        path.lineTo(17.0, 6.0)
        path.lineTo(17.0, 17.0)
        path.lineTo(3.0, 17.0)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawRect(QRectF(6.0, 3.0, 7.0, 5.0))
        painter.drawRoundedRect(QRectF(6.0, 11.0, 8.0, 6.0), 1.0, 1.0)
        if name == "save_as":
            line(12.0, 15.8, 17.2, 10.6)
            line(15.8, 10.0, 17.8, 12.0)
    elif name == "new_window":
        painter.drawRoundedRect(QRectF(5.0, 3.0, 12.0, 12.0), 1.5, 1.5)
        painter.drawRoundedRect(QRectF(3.0, 5.0, 12.0, 12.0), 1.5, 1.5)
        line(8.0, 11.0, 12.0, 11.0)
        line(10.0, 9.0, 10.0, 13.0)
    elif name == "recent":
        painter.drawEllipse(QRectF(3.0, 3.0, 14.0, 14.0))
        line(10.0, 5.5, 10.0, 10.0)
        line(10.0, 10.0, 13.5, 12.0)
        line(3.2, 6.0, 1.8, 4.0)
        line(3.2, 6.0, 5.2, 4.7)
    elif name == "power":
        painter.drawArc(QRectF(3.0, 3.0, 14.0, 14.0), 55 * 16, 250 * 16)
        line(10.0, 2.5, 10.0, 10.0)
    elif name == "print":
        painter.drawRoundedRect(QRectF(3.0, 7.0, 14.0, 8.0), 1.2, 1.2)
        painter.drawRect(QRectF(5.0, 2.5, 10.0, 6.5))
        painter.drawRect(QRectF(5.0, 12.0, 10.0, 5.5))
        painter.drawEllipse(QRectF(13.8, 9.0, 1.2, 1.2))
    elif name in ("undo", "redo"):
        if name == "undo":
            painter.drawArc(QRectF(4.0, 5.0, 13.0, 11.0), 20 * 16, 235 * 16)
            line(4.5, 5.0, 2.5, 9.0)
            line(2.5, 9.0, 6.5, 9.0)
        else:
            painter.drawArc(QRectF(3.0, 5.0, 13.0, 11.0), -75 * 16, 235 * 16)
            line(15.5, 5.0, 17.5, 9.0)
            line(17.5, 9.0, 13.5, 9.0)
    elif name == "copy":
        painter.drawRoundedRect(QRectF(6.0, 5.0, 11.0, 12.0), 1.2, 1.2)
        painter.drawRoundedRect(QRectF(3.0, 2.0, 11.0, 12.0), 1.2, 1.2)
    elif name == "select_all":
        line(3.0, 7.0, 3.0, 3.0); line(3.0, 3.0, 7.0, 3.0)
        line(13.0, 3.0, 17.0, 3.0); line(17.0, 3.0, 17.0, 7.0)
        line(3.0, 13.0, 3.0, 17.0); line(3.0, 17.0, 7.0, 17.0)
        line(13.0, 17.0, 17.0, 17.0); line(17.0, 17.0, 17.0, 13.0)
        painter.drawRoundedRect(QRectF(6.0, 6.0, 8.0, 8.0), 1.0, 1.0)
    elif name == "object_select":
        path = QPainterPath(QPointF(4.0, 2.5))
        path.lineTo(4.0, 15.0)
        path.lineTo(7.4, 11.8)
        path.lineTo(10.0, 17.2)
        path.lineTo(12.4, 16.0)
        path.lineTo(9.8, 10.8)
        path.lineTo(14.5, 10.2)
        path.closeSubpath()
        painter.drawPath(path)
    elif name == "rectangle":
        painter.drawRoundedRect(QRectF(3.0, 4.0, 14.0, 12.0), 1.2, 1.2)
        line(10.0, 6.5, 10.0, 13.5)
        line(6.5, 10.0, 13.5, 10.0)
    elif name == "image":
        painter.drawRoundedRect(QRectF(2.5, 3.0, 15.0, 14.0), 1.2, 1.2)
        painter.drawEllipse(QRectF(5.0, 5.3, 2.4, 2.4))
        path = QPainterPath(QPointF(4.5, 14.5))
        path.lineTo(8.3, 10.4)
        path.lineTo(10.7, 12.5)
        path.lineTo(13.3, 9.5)
        path.lineTo(16.0, 14.5)
        painter.drawPath(path)
    elif name == "edit":
        line(4.0, 16.0, 7.5, 15.2)
        line(7.5, 15.2, 16.5, 6.2)
        line(13.8, 3.5, 16.5, 6.2)
        line(13.8, 3.5, 4.8, 12.5)
        line(4.8, 12.5, 4.0, 16.0)
    elif name == "pages":
        painter.drawRoundedRect(QRectF(5.0, 2.5, 10.5, 13.0), 1.2, 1.2)
        painter.drawRoundedRect(QRectF(2.8, 5.0, 10.5, 12.5), 1.2, 1.2)
        line(6.0, 9.0, 10.5, 9.0)
        line(6.0, 12.0, 10.5, 12.0)
    elif name == "two_page":
        painter.drawRoundedRect(QRectF(2.0, 3.0, 7.0, 14.0), 1.0, 1.0)
        painter.drawRoundedRect(QRectF(11.0, 3.0, 7.0, 14.0), 1.0, 1.0)
        line(4.2, 6.0, 6.8, 6.0)
        line(13.2, 6.0, 15.8, 6.0)
    elif name == "fullscreen":
        line(3.0, 7.0, 3.0, 3.0); line(3.0, 3.0, 7.0, 3.0)
        line(13.0, 3.0, 17.0, 3.0); line(17.0, 3.0, 17.0, 7.0)
        line(3.0, 13.0, 3.0, 17.0); line(3.0, 17.0, 7.0, 17.0)
        line(13.0, 17.0, 17.0, 17.0); line(17.0, 17.0, 17.0, 13.0)
    elif name == "presentation":
        painter.drawRoundedRect(QRectF(2.5, 3.0, 15.0, 10.5), 1.0, 1.0)
        line(10.0, 13.5, 10.0, 17.5)
        line(6.5, 17.5, 13.5, 17.5)
        path = QPainterPath(QPointF(8.0, 6.0))
        path.lineTo(13.0, 8.25)
        path.lineTo(8.0, 10.5)
        path.closeSubpath()
        painter.drawPath(path)
    elif name in ("rotate_cw", "rotate_ccw"):
        if name == "rotate_cw":
            painter.drawArc(QRectF(3.0, 3.0, 14.0, 14.0), 25 * 16, 280 * 16)
            line(14.0, 3.5, 17.0, 3.0); line(17.0, 3.0, 16.5, 6.0)
        else:
            painter.drawArc(QRectF(3.0, 3.0, 14.0, 14.0), -125 * 16, 280 * 16)
            line(6.0, 3.5, 3.0, 3.0); line(3.0, 3.0, 3.5, 6.0)
    elif name == "merge":
        painter.drawRoundedRect(QRectF(2.5, 3.0, 6.0, 8.0), 1.0, 1.0)
        painter.drawRoundedRect(QRectF(2.5, 12.0, 6.0, 5.0), 1.0, 1.0)
        painter.drawRoundedRect(QRectF(12.0, 6.0, 5.5, 9.0), 1.0, 1.0)
        line(8.5, 7.0, 12.0, 9.0); line(8.5, 14.5, 12.0, 12.5)
    elif name == "split":
        painter.drawRoundedRect(QRectF(7.0, 3.0, 6.0, 14.0), 1.0, 1.0)
        line(7.0, 10.0, 2.5, 10.0); line(2.5, 10.0, 4.5, 8.0)
        line(2.5, 10.0, 4.5, 12.0)
        line(13.0, 10.0, 17.5, 10.0); line(17.5, 10.0, 15.5, 8.0)
        line(17.5, 10.0, 15.5, 12.0)
    elif name == "extract":
        painter.drawRoundedRect(QRectF(3.0, 3.0, 9.0, 14.0), 1.0, 1.0)
        line(8.0, 10.0, 17.0, 10.0)
        line(17.0, 10.0, 14.0, 7.0); line(17.0, 10.0, 14.0, 13.0)
    elif name == "highlight":
        line(4.0, 14.5, 12.8, 5.7); line(7.2, 16.0, 16.0, 7.2)
        line(12.8, 5.7, 16.0, 7.2); line(4.0, 14.5, 7.2, 16.0)
        line(3.0, 17.5, 15.0, 17.5)
    elif name in ("note", "notes", "license"):
        painter.drawRoundedRect(QRectF(3.5, 3.0, 13.0, 14.0), 1.2, 1.2)
        line(6.5, 7.0, 13.5, 7.0)
        line(6.5, 10.0, 13.5, 10.0)
        if name != "note":
            line(6.5, 13.0, 11.0, 13.0)
    elif name == "ocr":
        line(3.0, 7.0, 3.0, 3.0); line(3.0, 3.0, 7.0, 3.0)
        line(13.0, 3.0, 17.0, 3.0); line(17.0, 3.0, 17.0, 7.0)
        line(3.0, 13.0, 3.0, 17.0); line(3.0, 17.0, 7.0, 17.0)
        line(13.0, 17.0, 17.0, 17.0); line(17.0, 17.0, 17.0, 13.0)
        line(5.0, 10.0, 15.0, 10.0)
    elif name == "ai":
        line(10.0, 2.0, 10.0, 6.5); line(7.8, 4.2, 12.2, 4.2)
        line(4.5, 8.0, 4.5, 12.0); line(2.5, 10.0, 6.5, 10.0)
        line(12.5, 11.0, 12.5, 18.0); line(9.0, 14.5, 16.0, 14.5)
    elif name in ("zoom_in", "zoom_out"):
        painter.drawEllipse(QRectF(3.0, 3.0, 10.5, 10.5))
        line(12.0, 12.0, 17.0, 17.0)
        line(6.0, 8.25, 10.5, 8.25)
        if name == "zoom_in":
            line(8.25, 6.0, 8.25, 10.5)
    elif name in ("fit_page", "fit_width"):
        painter.drawRoundedRect(QRectF(4.5, 2.5, 11.0, 15.0), 1.0, 1.0)
        if name == "fit_width":
            line(2.5, 10.0, 17.5, 10.0)
            line(2.5, 10.0, 5.2, 7.3)
            line(2.5, 10.0, 5.2, 12.7)
            line(17.5, 10.0, 14.8, 7.3)
            line(17.5, 10.0, 14.8, 12.7)
        else:
            line(2.5, 6.0, 2.5, 2.5); line(2.5, 2.5, 6.0, 2.5)
            line(14.0, 2.5, 17.5, 2.5); line(17.5, 2.5, 17.5, 6.0)
            line(2.5, 14.0, 2.5, 17.5); line(2.5, 17.5, 6.0, 17.5)
            line(14.0, 17.5, 17.5, 17.5); line(17.5, 17.5, 17.5, 14.0)
    elif name == "help":
        painter.drawEllipse(QRectF(2.5, 2.5, 15.0, 15.0))
        painter.drawArc(QRectF(7.0, 5.0, 6.0, 5.5), 0, 180 * 16)
        line(10.0, 10.3, 10.0, 12.5)
        painter.drawEllipse(QRectF(9.4, 14.2, 1.2, 1.2))
    elif name == "info":
        painter.drawEllipse(QRectF(2.5, 2.5, 15.0, 15.0))
        painter.drawEllipse(QRectF(9.3, 5.0, 1.4, 1.4))
        line(10.0, 9.0, 10.0, 14.0)
    elif name == "settings":
        painter.drawEllipse(QRectF(7.0, 7.0, 6.0, 6.0))
        painter.drawEllipse(QRectF(3.5, 3.5, 13.0, 13.0))
        for angle in range(0, 360, 45):
            rad = math.radians(angle)
            line(10 + math.cos(rad) * 6.5, 10 + math.sin(rad) * 6.5,
                 10 + math.cos(rad) * 8.0, 10 + math.sin(rad) * 8.0)
    elif name == "update":
        painter.drawArc(QRectF(3.0, 3.0, 14.0, 14.0), 35 * 16, 285 * 16)
        line(14.0, 3.7, 17.0, 3.0)
        line(17.0, 3.0, 16.3, 6.0)

    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return QIcon(pixmap)
