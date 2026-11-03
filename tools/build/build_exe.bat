@echo off
pushd "%~dp0..\.." || exit /b 1
chcp 65001 >nul
REM Build dist\Leaflet\Leaflet.exe with PyInstaller.
REM Prerequisite: install PyInstaller and all application dependencies.

echo === Creating icons ===
python -m tools.build.make_icons || goto :err

echo === Building Direct2D renderer ===
call native\build_d2d_renderer.bat || goto :err

echo === Building Rust GPU scene compiler ===
python native\build_path_packer.py || goto :err

echo === Building native MuPDF input adapter ===
python native\build_mupdf_path.py || goto :err

REM Verify the repository root before removing its generated build directories.
if not exist pdfeditor\meta.py goto :err
if not exist packaging\spdf.spec goto :err

echo === Cleaning previous build ===
if exist build rmdir /s /q build
if exist dist\Leaflet rmdir /s /q dist\Leaflet

echo === PyInstaller ===
REM Use python -m so the Scripts directory does not need to be on PATH.
python -m PyInstaller --noconfirm --clean packaging/spdf.spec || goto :err

echo.
echo Complete: dist\Leaflet\Leaflet.exe
echo Next: run tools/build/build_installer.bat to create the installer.
popd
goto :eof

:err
echo.
echo *** Build failed ***
popd
exit /b 1
