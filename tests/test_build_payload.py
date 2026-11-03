import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from tools.build.build_payload import keep_payload, trim_payload, native_worker_runtime_binaries


class BuildPayloadTests(unittest.TestCase):
    def test_independent_worker_gets_shared_msvc_runtime_in_its_own_directory(self):
        with patch('PyInstaller.depend.bindepend.get_imports', side_effect=[
                {('VCRUNTIME140.dll', 'runtime/VCRUNTIME140.dll'), ('KERNEL32.dll', None)},
                {('VCRUNTIME140.dll', 'runtime/VCRUNTIME140.dll'),
                 ('MSVCP140.dll', 'qt/MSVCP140.dll')}]) as imports:
            self.assertEqual(native_worker_runtime_binaries('worker.exe', 'sdk.dll', search_paths=['qt']),
                [('qt/MSVCP140.dll', 'native'), ('runtime/VCRUNTIME140.dll', 'native')])
            imports.assert_any_call('sdk.dll', search_paths=['qt'])

    def test_missing_worker_runtime_stops_packaging(self):
        with patch('PyInstaller.depend.bindepend.get_imports', return_value={('MSVCP140.dll', None)}):
            with self.assertRaisesRegex(RuntimeError, 'MSVCP140.dll'):
                native_worker_runtime_binaries('sdk.dll')

    def test_preserves_rendering_image_printing_and_worker_runtimes(self):
        for name in (
            "native/spdf_d2d_renderer.dll", "python312.dll", "numpy.libs/openblas.dll",
            "PyQt5/Qt5/bin/opengl32sw.dll", "PyQt5/Qt5/bin/libGLESv2.dll",
            "PyQt5/Qt5/bin/Qt5PrintSupport.dll", "PyQt5/Qt5/bin/Qt5Network.dll",
            "PyQt5/Qt5/plugins/platforms/qwindows.dll",
            "PyQt5/Qt5/plugins/platforms/qoffscreen.dll",
            "PyQt5/Qt5/plugins/imageformats/qjpeg.dll",
            "PyQt5/Qt5/plugins/imageformats/qtiff.dll",
            "PyQt5/Qt5/plugins/iconengines/qsvgicon.dll",
            "PyQt5/Qt5/translations/qtbase_ko.qm",
            "PyQt5/Qt5/translations/qtbase_en_US.qm",
            "rapidocr/models/korean_PP-OCRv5_rec_mobile.onnx",
            "onnxruntime/capi/onnxruntime.dll",
        ):
            self.assertTrue(keep_payload(name, gui=True), name)

    def test_omits_only_unused_video_web_and_other_language_payloads(self):
        for name in (
            "cv2/opencv_videoio_ffmpeg500_64.dll",
            "PyQt5/Qt5/plugins/platforms/qwebgl.dll",
            "PyQt5/Qt5/bin/Qt5Quick.dll",
            "PyQt5/Qt5/translations/qtbase_de.qm",
        ):
            self.assertFalse(keep_payload(name, gui=True), name)
        self.assertFalse(keep_payload(r"cv2\opencv_videoio_ffmpeg500_64.dll", gui=False))

    @unittest.skipUnless(sys.platform == "win32" and importlib.util.find_spec("pefile"),
                         "Windows PE reader required")
    def test_refuses_to_remove_dll_required_by_a_retained_plugin(self):
        from PyQt5.QtCore import QLibraryInfo
        plugins = Path(QLibraryInfo.location(QLibraryInfo.PluginsPath))
        libraries = Path(QLibraryInfo.location(QLibraryInfo.BinariesPath))
        plugin = plugins / "platforms/qwebgl.dll"
        dependency = libraries / "Qt5Quick.dll"
        if not plugin.is_file() or not dependency.is_file():
            self.skipTest("Qt WebGL fixture is unavailable")
        with self.assertRaisesRegex(RuntimeError, "needs qt5quick.dll"):
            trim_payload([
                ("PyQt5/Qt5/bin/Qt5Quick.dll", str(dependency), "BINARY"),
                ("retained-plugin.dll", str(plugin), "BINARY"),
            ], [], gui=True)


if __name__ == "__main__":
    unittest.main()
