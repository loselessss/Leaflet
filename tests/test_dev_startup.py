"""Exercise the real source launchers from an interpreter outside their venv."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from pdfeditor import dev_startup

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'nt', 'Windows Python/Pythonw launchers required')
class DevelopmentStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name) / '개발 경로 with spaces'
        cls.root.mkdir()
        package = cls.root / 'pdfeditor'
        package.mkdir()
        (package / '__init__.py').write_text('', encoding='utf-8')
        shutil.copy2(ROOT / 'pdfeditor/dev_startup.py', package / 'dev_startup.py')
        for entry in ('run.py', 'run.pyw'):
            shutil.copy2(ROOT / entry, cls.root / entry)
        # The fake GUI records the real interpreter chosen by the copied entry
        # point. No mocks replace prefix selection or process startup.
        (package / '__main__.py').write_text('''
import json,os,sys
from pathlib import Path
def main(*,allow_residency=True):
    output=Path(os.environ['LEAFLET_STARTUP_TEST_OUTPUT'])
    temporary=output.with_suffix('.tmp')
    temporary.write_text(json.dumps({
        'prefix':sys.prefix,'executable':sys.executable,'args':sys.argv[1:],'pid':os.getpid(),
        'allow_residency':allow_residency,'ignore_environment':sys.flags.ignore_environment,
        'no_user_site':sys.flags.no_user_site,'pythonpath':os.environ.get('PYTHONPATH'),
        'native_imported':any(n.startswith(('pymupdf','PyQt5')) for n in sys.modules)
    }),encoding='utf-8')
    temporary.replace(output)
''', encoding='utf-8')
        cls.base = getattr(sys, '_base_executable', sys.executable)
        environment = dict(os.environ)
        for name in ('__PYVENV_LAUNCHER__', 'PYTHONHOME', 'PYTHONPATH'):
            environment.pop(name, None)
        subprocess.run([cls.base, '-m', 'venv', '--without-pip', str(cls.root / '.venv')],
                       env=environment, check=True, capture_output=True, timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def invoke(self, entry, *, already_in_venv=False):
        output = self.root / 'runtime.json'
        output.unlink(missing_ok=True)
        environment = dict(os.environ, LEAFLET_STARTUP_TEST_OUTPUT=str(output),
                           PYTHONPATH=str(self.root / 'unrelated site-packages'))
        environment.pop('__PYVENV_LAUNCHER__', None)
        environment.pop('PYTHONHOME', None)
        executable = str(self.root / '.venv/Scripts/python.exe') if already_in_venv else self.base
        args = ['한글 PDF with spaces.pdf', '--no-resident']
        process = subprocess.run([executable, str(self.root / entry), *args], env=environment,
            check=False, capture_output=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr.decode(errors='replace'))
        # The bootstrap exits after starting the GUI interpreter. Wait for its
        # file even when pythonw has no inherited console streams.
        deadline = time.monotonic() + 10
        while not output.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(output.exists(), 'project interpreter did not reach the entry point')
        value = json.loads(output.read_text(encoding='utf-8'))
        # Publishing the result precedes interpreter shutdown. Wait for the
        # actual child to exit before removing its Windows-locked executable.
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.WaitForSingleObject.restype = ctypes.c_uint32
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x100000, False, value['pid'])  # SYNCHRONIZE, no mutation.
        if handle:
            try:
                self.assertEqual(kernel.WaitForSingleObject(handle, 5000), 0,
                                 'fixture interpreter did not exit')
            finally:
                kernel.CloseHandle(handle)
        else:
            self.assertEqual(ctypes.get_last_error(), 87)  # The child already exited.
        self.assertTrue(Path(value['prefix']).samefile(self.root / '.venv'))
        self.assertEqual(value['args'], args)
        self.assertFalse(value['native_imported'])
        return value

    def test_system_python_pyw_relaunches_pythonw_in_project_venv_before_native_imports(self):
        value = self.invoke('run.pyw')
        self.assertTrue(Path(value['executable']).samefile(self.root / '.venv/Scripts/pythonw.exe'))
        self.assertFalse(value['allow_residency'])
        self.assertEqual(value['ignore_environment'], 1)
        self.assertEqual(value['no_user_site'], 1)
        self.assertIsNone(value['pythonpath'])

    def test_system_python_console_launch_uses_same_project_environment(self):
        value = self.invoke('run.py')
        self.assertTrue(Path(value['executable']).samefile(self.root / '.venv/Scripts/python.exe'))
        self.assertTrue(value['allow_residency'])
        self.assertEqual(value['ignore_environment'], 1)

    def test_already_selected_project_interpreter_does_not_relaunch(self):
        value = self.invoke('run.pyw', already_in_venv=True)
        self.assertTrue(Path(value['executable']).samefile(self.root / '.venv/Scripts/python.exe'))
        self.assertEqual(value['ignore_environment'], 0)
        self.assertFalse(value['allow_residency'])


class DevelopmentStartupFallbackTests(unittest.TestCase):
    def test_packaged_executable_never_uses_source_venv(self):
        with patch.object(sys, 'frozen', True, create=True), \
                patch.object(dev_startup.subprocess, 'Popen', side_effect=AssertionError('unexpected relaunch')):
            dev_startup.ensure_project_environment('run.pyw', windowless=True)

    def test_checkout_without_venv_keeps_explicit_interpreter(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(dev_startup, '__file__', str(Path(directory) / 'pdfeditor/dev_startup.py')), \
                patch.object(dev_startup.subprocess, 'Popen', side_effect=AssertionError('unexpected relaunch')):
            dev_startup.ensure_project_environment('run.pyw', windowless=True)
