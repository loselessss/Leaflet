"""Prepare an unsigned x64 MSIX from the matching PyInstaller build."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from pdfeditor.meta import APP_NAME, APP_VERSION

ROOT = Path(__file__).resolve().parent
NS = 'http://schemas.microsoft.com/appx/manifest/foundation/windows10'
UAP = 'http://schemas.microsoft.com/appx/manifest/uap/windows10'
RESCAP = NS + '/restrictedcapabilities'
ET.register_namespace('', NS)
ET.register_namespace('uap', UAP)
ET.register_namespace('rescap', RESCAP)


def package_version(version):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Expected x.y.z version')
    if any(int(part) > 65535 for part in version.split('.')):
        raise ValueError('MSIX version components must be <= 65535')
    return version + '.0'


def manifest(version, name, publisher, display_name):
    if not re.fullmatch(r'[A-Za-z0-9.-]{3,50}', name):
        raise ValueError('Invalid MSIX identity name')
    if not publisher.startswith('CN=') or not display_name.strip():
        raise ValueError('Supply the certificate subject / Store publisher and display name')
    root = ET.Element('{' + NS + '}Package', IgnorableNamespaces='uap rescap')
    def node(parent, tag, **attrs):
        return ET.SubElement(parent, '{' + NS + '}' + tag, attrs)
    node(root, 'Identity', Name=name, Publisher=publisher,
         Version=package_version(version), ProcessorArchitecture='x64')
    props = node(root, 'Properties')
    for key, text in [('DisplayName',APP_NAME), ('PublisherDisplayName',display_name),
                      ('Logo',r'Assets\StoreLogo.png')]:
        node(props,key).text = text
    resources = node(root,'Resources')
    for language in ('en-us','ko-kr'):
        node(resources,'Resource', Language=language)
    deps = node(root,'Dependencies')
    node(deps,'TargetDeviceFamily',Name='Windows.Desktop',MinVersion='10.0.17763.0',
         MaxVersionTested='10.0.26100.0')
    applications = node(root,'Applications')
    app = node(applications,'Application',Id='sPDF',Executable=r'app\Leaflet.exe',
               EntryPoint='Windows.FullTrustApplication')
    ET.SubElement(app,'{'+UAP+'}VisualElements',DisplayName=APP_NAME,Description=APP_NAME+' PDF reader and editor',
        Square150x150Logo=r'Assets\Square150x150Logo.png',
        Square44x44Logo=r'Assets\Square44x44Logo.png',BackgroundColor='transparent')
    extensions = node(app,'Extensions')
    extension = ET.SubElement(extensions,'{'+UAP+'}Extension',Category='windows.fileTypeAssociation')
    association = ET.SubElement(extension,'{'+UAP+'}FileTypeAssociation',Name='spdf.pdf')
    ET.SubElement(association,'{'+UAP+'}DisplayName').text='PDF'
    supported = ET.SubElement(association,'{'+UAP+'}SupportedFileTypes')
    for extension in ('.pdf','.ai'):
        ET.SubElement(supported,'{'+UAP+'}FileType').text=extension
    capabilities = node(root,'Capabilities')
    ET.SubElement(capabilities,'{'+RESCAP+'}Capability',Name='runFullTrust')
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)


def stage_package(source, destination, *, version, name, publisher, display_name, icon):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    ocr_source = source.parent / 'Leaflet-ocr'
    if source == destination or source in destination.parents:
        raise ValueError('MSIX staging must be outside the application directory')
    manifest_bytes = manifest(version,name,publisher,display_name)
    for file in ('Leaflet.exe','_internal/native/spdf_d2d_renderer.dll',
                 '_internal/LICENSE','_internal/LICENSES.md','_internal/SOURCE_CODE.md',
                 '_internal/third-party/build-environment.json'):
        if not (source/file).is_file():
            raise FileNotFoundError('Rebuild with build_exe.bat: missing '+file)
    for file in ('leaflet-ocr.exe','_internal/third-party/build-environment.json'):
        if not (ocr_source/file).is_file():
            raise FileNotFoundError('Rebuild with build_exe.bat: missing Leaflet-ocr/'+file)
    inventory=json.loads((source/'_internal/third-party/build-environment.json').read_text(encoding='utf-8'))
    if inventory['app_version'] != version:
        raise ValueError('Existing executable is a different version; rebuild first')
    worker_inventory=json.loads((ocr_source/'_internal/third-party/build-environment.json').read_text(encoding='utf-8'))
    if (worker_inventory.get('app_version') != version or
            worker_inventory.get('commit') != inventory.get('commit')):
        raise ValueError('OCR worker belongs to a different build; rebuild first')
    if inventory.get('architecture','').lower() not in ('amd64','x86_64'):
        raise ValueError('Only x64 builds are supported')
    if any(path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction())
           for root in (source, ocr_source) for path in root.rglob('*')):
        raise ValueError('Links are not allowed in the package input')
    destination.mkdir(parents=True,exist_ok=False)
    shutil.copytree(source,destination/'app')
    shutil.copytree(ocr_source,destination/'app/ocr')
    (destination/'AppxManifest.xml').write_bytes(manifest_bytes)
    from PIL import Image
    assets=destination/'Assets'
    assets.mkdir()
    with Image.open(icon) as image:
        image=image.convert('RGBA')
        for label,size in [('StoreLogo',50),('Square44x44Logo',44),('Square150x150Logo',150)]:
            image.resize((size,size),Image.Resampling.LANCZOS).save(assets/(label+'.png'))
    return destination


def find_makeappx():
    executable=shutil.which('MakeAppx.exe')
    if executable:
        return executable
    base=Path(os.environ.get('ProgramFiles(x86)',r'C:\Program Files (x86)'))/'Windows Kits/10/bin'
    candidates=list(base.glob('*/x64/makeappx.exe'))
    if not candidates:
        raise FileNotFoundError('Install the Windows SDK, or put MakeAppx.exe on PATH')
    return str(max(candidates,key=lambda p: tuple(int(v) for v in p.parent.parent.name.split('.'))))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--identity-name',required=True)
    parser.add_argument('--publisher',required=True)
    parser.add_argument('--publisher-display-name',required=True)
    parser.add_argument('--source',type=Path,default=ROOT/'dist/Leaflet')
    parser.add_argument('--output',type=Path,default=ROOT/'Output')
    args=parser.parse_args(argv)
    makeappx=find_makeappx()
    args.output.mkdir(parents=True,exist_ok=True)
    package=args.output/('Leaflet_%s_x64_unsigned.msix'%APP_VERSION)
    if package.exists():
        raise FileExistsError(package)
    # Retain staging on error for inspection; never remove existing build outputs.
    staging=Path(tempfile.mkdtemp(prefix='msix-',dir=args.output))/'package'
    stage_package(args.source,staging,version=APP_VERSION,name=args.identity_name,
        publisher=args.publisher,display_name=args.publisher_display_name,icon=ROOT/'assets/spdf.ico')
    subprocess.run([makeappx,'pack','/d',str(staging),'/p',str(package),'/no'],check=True)
    print('Unsigned package (sign before distribution):',package)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
