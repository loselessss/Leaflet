import os
import unittest

from PyQt5 import sip
from PyQt5.QtCore import QEvent
from PyQt5.QtWidgets import QApplication, QPushButton, QWidget, QSpinBox

from pdfeditor.i18n import install, set_language


class TranslationLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        cls.translator = install(cls.app, "en")

    def setUp(self):
        set_language("en")

    def test_polish_translation_waits_for_completed_construction(self):
        button = QPushButton("저장")
        self.translator.eventFilter(button, QEvent(QEvent.Polish))
        self.assertEqual(button.text(), "저장")
        self.app.processEvents()
        self.assertEqual(button.text(), "Save")
        sip.delete(button)

    def test_child_added_never_dereferences_incomplete_child(self):
        class ConstructionEvent:
            def type(self):
                return QEvent.ChildAdded

            def child(self):
                raise AssertionError("Never retain an incomplete child wrapper")

        parent = QWidget()
        self.translator.eventFilter(parent, ConstructionEvent())
        child = QPushButton("저장", parent)
        self.app.processEvents()
        self.assertEqual(child.text(), "Save")
        sip.delete(parent)

    def test_deleted_widget_is_not_read_by_deferred_translation(self):
        button = QPushButton("저장")
        self.translator.schedule(button)
        sip.delete(button)
        self.app.processEvents()
        self.assertTrue(sip.isdeleted(button))

    def test_retranslation_uses_original_source_text(self):
        button = QPushButton("저장")
        self.translator.schedule(button)
        self.app.processEvents()
        self.assertEqual(button.text(), "Save")
        set_language("ko")
        self.translator.schedule(button)
        self.app.processEvents()
        self.assertEqual(button.text(), "저장")
        set_language("en")
        self.translator.schedule(button)
        self.app.processEvents()
        self.assertEqual(button.text(), "Save")
        sip.delete(button)

    def test_translation_preserves_live_zoom_editor(self):
        spin = QSpinBox()
        spin.setRange(10, 800)
        spin.setSuffix("%")
        spin.setValue(100)
        self.app._spdf_translate_tree(spin)
        spin.setValue(175)
        self.translator.schedule(spin)
        self.app.processEvents()
        self.assertEqual(spin.value(), 175)
        self.assertEqual(spin.lineEdit().text(), "175%")
        sip.delete(spin)

    def test_overlapping_trees_translate_each_widget_once_per_batch(self):
        class CountingButton(QPushButton):
            reads = 0

            def text(self):
                self.reads += 1
                return super().text()

        parent = QWidget()
        button = CountingButton("저장", parent)
        self.app.processEvents()
        button.reads = 0
        self.translator.schedule(parent)
        self.translator.schedule(button)
        self.translator.flush_pending()
        self.assertEqual(button.reads, 1)
        sip.delete(parent)


if __name__ == "__main__":
    unittest.main()
