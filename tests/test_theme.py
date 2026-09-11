import ast
import re
import unittest
from pathlib import Path

from pdfeditor.icons import AVAILABLE_ICONS, FLUENT_GLYPHS
from pdfeditor.theme import FLUENT_STYLESHEET


class FluentThemeTests(unittest.TestCase):
    def test_theme_covers_primary_shell_controls(self):
        for selector in (
                "QMenuBar", "QToolBar", "QTabBar::tab", "QListWidget",
                "QTreeWidget", "QLineEdit", "QStatusBar",
                "QScrollBar:vertical"):
            self.assertIn(selector, FLUENT_STYLESHEET)

    def test_theme_has_fluent_accent_and_cards(self):
        self.assertIn("#0f6cbd", FLUENT_STYLESHEET)
        self.assertIn("QFrame#startCard", FLUENT_STYLESHEET)
        self.assertIn("QFrame#printSettingsCard", FLUENT_STYLESHEET)
        self.assertIn("QFrame#printPreviewCard", FLUENT_STYLESHEET)
        self.assertIn("QPrintPreviewWidget#printPreviewWidget", FLUENT_STYLESHEET)
        self.assertIn('QPushButton[accent="true"]', FLUENT_STYLESHEET)

    def test_theme_does_not_force_classic_fusion_style(self):
        source = (
            Path(__file__).resolve().parents[1] / "pdfeditor" / "theme.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn('setStyle("Fusion")', source)

    def test_stylesheet_blocks_are_balanced(self):
        self.assertEqual(
            FLUENT_STYLESHEET.count("{"), FLUENT_STYLESHEET.count("}"))
        self.assertIn("QAbstractScrollArea::corner", FLUENT_STYLESHEET)

    def test_start_file_lists_do_not_show_horizontal_scroll_corner(self):
        source = (
            Path(__file__).resolve().parents[1] / "pdfeditor" / "startpage.py"
        ).read_text(encoding="utf-8")
        self.assertIn("Qt.ScrollBarAlwaysOff", source)
        self.assertIn("Qt.ElideMiddle", source)

    def test_outer_window_does_not_create_an_empty_status_bar(self):
        source = (
            Path(__file__).resolve().parents[1] / "pdfeditor" / "app.py"
        ).read_text(encoding="utf-8")
        shell = source.split("class AppWindow(", 1)[1]
        shell_init = shell.split("    def show_recovery", 1)[0]
        self.assertNotIn("self.setStatusBar", shell_init)
        self.assertIn("def _document_status_bar", shell)

    def test_visible_fluent_controls_have_icons(self):
        expected = {
            "add_file", "ai", "back", "chevron_down", "chevron_up",
            "close", "copy", "delete", "download", "edit", "external",
            "extract", "fit_page", "fit_width", "fullscreen", "hand", "help",
            "highlight", "image", "info",
            "license", "merge", "new_tab", "new_window", "note", "notes",
            "object_select", "ocr", "open", "pages", "power", "presentation", "print", "recent", "rectangle", "redo",
            "rotate_ccw", "rotate_cw", "save", "save_as", "search",
            "select_all", "settings", "split", "star", "star_filled",
            "text_select", "two_page", "undo", "update", "zoom_in", "zoom_out",
        }
        self.assertEqual(AVAILABLE_ICONS, expected)

    def test_common_actions_use_official_system_glyphs(self):
        self.assertEqual(FLUENT_GLYPHS["save"], 0xE74E)
        self.assertEqual(FLUENT_GLYPHS["search"], 0xE721)
        self.assertEqual(FLUENT_GLYPHS["settings"], 0xE713)
        self.assertTrue(set(FLUENT_GLYPHS) <= AVAILABLE_ICONS)

    def test_command_bar_is_icon_first(self):
        source = (
            Path(__file__).resolve().parents[1] / "pdfeditor" / "app.py"
        ).read_text(encoding="utf-8")
        self.assertIn("Qt.ToolButtonIconOnly", source)
        self.assertIn("sidebarRibbonButton", source)
        self.assertIn(
            "self._sidebar_button.setToolButtonStyle(Qt.ToolButtonIconOnly)",
            source)
        self.assertNotIn(
            "self._sidebar_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)",
            source)

    def test_command_bar_exposes_sidebar_menu(self):
        source = (
            Path(__file__).resolve().parents[1] / "pdfeditor" / "app.py"
        ).read_text(encoding="utf-8")
        self.assertIn("tool_bar.addWidget(self._sidebar_button)", source)

    def test_command_bar_exposes_both_page_rotation_actions(self):
        source = (
            Path(__file__).resolve().parents[1] / "pdfeditor" / "app.py"
        ).read_text(encoding="utf-8")
        self.assertIn("tool_bar.addAction(self._rotate_ccw_act)", source)
        self.assertIn("tool_bar.addAction(self._rotate_cw_act)", source)

    def test_command_bar_exposes_two_page_view(self):
        source = (
            Path(__file__).resolve().parents[1] / "pdfeditor" / "app.py"
        ).read_text(encoding="utf-8")
        self.assertIn("tool_bar.addAction(self._two_page_act)", source)

    def test_command_bar_exposes_presentation_and_full_screen(self):
        source = (
            Path(__file__).resolve().parents[1] / "pdfeditor" / "app.py"
        ).read_text(encoding="utf-8")
        self.assertIn("tool_bar.addAction(self._presentation_act)", source)
        self.assertIn("tool_bar.addAction(self._full_screen_act)", source)

    def test_windows_11_backdrop_has_safe_fallback(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "pdfeditor" / "windows_integration.py"
        ).read_text(encoding="utf-8")
        self.assertIn("DWMWA_SYSTEMBACKDROP_TYPE = 38", source)
        self.assertIn('sys.platform != "win32"', source)

    def test_all_referenced_icon_names_exist(self):
        root = Path(__file__).resolve().parents[1] / "pdfeditor"
        referenced = set()
        for path in root.glob("*.py"):
            if path.name == "icons.py":
                continue
            source = path.read_text(encoding="utf-8")
            referenced.update(re.findall(r'fluent_icon\("([a-z_]+)"', source))
        self.assertTrue(referenced)
        self.assertTrue(referenced <= AVAILABLE_ICONS)

    def test_every_main_menu_action_has_an_icon(self):
        source = (
            Path(__file__).resolve().parents[1] / "pdfeditor" / "app.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "_act"
        ]
        self.assertTrue(calls)
        self.assertFalse([
            node.lineno for node in calls
            if len(node.args) < 5
            and not any(key.arg == "icon_name" for key in node.keywords)
        ])


if __name__ == "__main__":
    unittest.main()
