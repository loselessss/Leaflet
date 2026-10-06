"""Windowless startup must not invoke the deprecated fitz warning writer."""
import subprocess
import sys
import unittest
from pathlib import Path


class StartupImportTests(unittest.TestCase):
    def test_editor_import_with_invalid_console_handles(self):
        code = """
import sys
class InvalidConsole:
    encoding = 'utf-8'
    def write(self, text):
        raise OSError(22, 'Invalid argument')
    def flush(self):
        pass
sys.stdout = sys.stderr = InvalidConsole()
try:
    import pdfeditor.app
    assert 'fitz' not in sys.modules
finally:
    sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
"""
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
