"""Build a path bridge using only this Python environment's MuPDF SDK."""
from pathlib import Path
import subprocess
import pymupdf


def main():
    root = Path(__file__).resolve().parent
    sdk = Path(pymupdf.__file__).parent / 'mupdf-devel'
    vswhere = Path('C:/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe')
    installation = subprocess.check_output([str(vswhere), '-latest', '-products', '*',
        '-requires', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64',
        '-property', 'installationPath'], text=True).strip()
    vcvars = Path(installation) / 'VC/Auxiliary/Build/vcvars64.bat'
    output = root / 'bin'
    output.mkdir(exist_ok=True)
    # Fixed build recipe; paths come from this environment, never shell input.
    recipe = output / 'build_mupdf_path.cmd'
    recipe.write_text('@echo off\ncall "' + str(vcvars) + '" >nul\n'
        'if errorlevel 1 exit /b 1\n'
        'cl /nologo /std:c++17 /EHsc /O2 /W4 /WX /LD /I"' + str(sdk / 'include') +
        '" "' + str(root / 'mupdf_path.cpp') + '" /Fo"' + str(output / 'mupdf_path.obj') +
        '" /link "' + str(sdk / 'lib/mupdfcpp64.lib') + '" /OUT:"' +
        str(output / 'leaflet_mupdf_path.dll') + '" /IMPLIB:"' +
        str(output / 'mupdf_path.lib') + '"\n', encoding='utf-8')
    subprocess.run(['cmd', '/c', str(recipe)], check=True)


if __name__ == '__main__':
    main()
