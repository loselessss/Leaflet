import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

from build_msix import manifest, package_version, stage_package, find_makeappx, NS
from pdfeditor.meta import APP_VERSION


class MsixTests(unittest.TestCase):
    def test_manifest_identity_is_escaped_and_preserves_version(self):
        root=ET.fromstring(manifest(APP_VERSION,'Example.sPDF','CN=Example & Co','Example & Co'))
        identity=root.find('{'+NS+'}Identity')
        self.assertEqual(identity.get('Publisher'),'CN=Example & Co')
        self.assertEqual(identity.get('Version'),APP_VERSION+'.0')
        self.assertEqual(identity.get('ProcessorArchitecture'),'x64')
        for bad in ('1.2','1.2.3.4','1.2.65536'):
            with self.assertRaises(ValueError):
                package_version(bad)

    def make_source(self, root):
        source=root/'dist'
        for path in ('sPDF.exe','_internal/native/spdf_d2d_renderer.dll',
                     '_internal/LICENSE','_internal/LICENSES.md','_internal/SOURCE_CODE.md'):
            file=source/path
            file.parent.mkdir(parents=True,exist_ok=True)
            file.write_bytes(b'fixture')
        inventory=source/'_internal/third-party/build-environment.json'
        inventory.parent.mkdir(parents=True)
        inventory.write_text(json.dumps({'app_version':APP_VERSION,'architecture':'AMD64'}))
        worker=root/'sPDF-ocr/_internal/third-party/build-environment.json'
        worker.parent.mkdir(parents=True)
        worker.write_bytes(inventory.read_bytes())
        (root/'sPDF-ocr/spdf-ocr.exe').write_bytes(b'fixture')
        return source

    def stage(self, source, target):
        return stage_package(source,target,version=APP_VERSION,name='Example.sPDF',
            publisher='CN=Example',display_name='Example',icon=Path('assets/spdf.ico'))

    def test_staging_preserves_workers_and_rejects_stale_build_and_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=self.make_source(root)
            target=self.stage(source,root/'package')
            self.assertTrue((target/'app/ocr/spdf-ocr.exe').is_file())
            self.assertTrue((target/'app/_internal/native/spdf_d2d_renderer.dll').is_file())
            self.assertTrue((target/'Assets/Square150x150Logo.png').is_file())
            with self.assertRaises(FileExistsError):
                self.stage(source,target)
            inventory=source/'_internal/third-party/build-environment.json'
            inventory.write_text(json.dumps({'app_version':'0.0.0'}))
            with self.assertRaisesRegex(ValueError,'different version'):
                self.stage(source,root/'stale')
            self.assertFalse((root/'stale').exists())

    @unittest.skipUnless(sys.platform=='win32','Windows SDK integration')
    def test_windows_sdk_accepts_manifest_and_package(self):
        try:
            tool=find_makeappx()
        except FileNotFoundError:
            self.skipTest('Windows SDK unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=self.make_source(root)
            shutil.copyfile(sys.executable,source/'sPDF.exe')
            shutil.copyfile(sys.executable,source.parent/'sPDF-ocr/spdf-ocr.exe')
            target=self.stage(source,root/'package')
            output=root/'fixture.msix'
            result=subprocess.run([tool,'pack','/d',str(target),'/p',str(output),'/no'],
                capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            with zipfile.ZipFile(output) as archive:
                self.assertIn('AppxManifest.xml',archive.namelist())
                self.assertIn('app/ocr/spdf-ocr.exe',archive.namelist())

    def test_packaged_identity_does_not_set_legacy_app_id(self):
        from pdfeditor.windows_integration import set_current_process_app_id
        with patch('pdfeditor.paths.is_packaged',return_value=True):
            self.assertFalse(set_current_process_app_id())

    def test_only_installers_are_attached_to_normal_release(self):
        workflow=Path('.github/workflows/release.yml').read_text(encoding='utf-8')
        normal=workflow.split('- name: Publish GitHub release',1)[1]
        self.assertIn('gh release upload $tag $installer $latestInstaller --clobber',normal)
        self.assertNotIn('$sourceArchive',normal)
        self.assertIn('sources-v$version',normal)
        self.assertLess(workflow.index('gh release upload $sourceTag'),workflow.index('- name: Publish GitHub release'))
        self.assertIn('--prerelease --latest=false',workflow)


if __name__=='__main__':
    unittest.main()
