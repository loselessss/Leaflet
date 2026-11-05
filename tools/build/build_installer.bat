@echo off
pushd "%~dp0..\.." || exit /b 1
chcp 65001 >nul
REM Build Output\Leaflet_Setup_X.X.X.exe with Inno Setup.
REM Prerequisite: run tools/build/build_exe.bat first to create dist\Leaflet.

if not exist dist\Leaflet\Leaflet.exe (
  echo dist\Leaflet\Leaflet.exe is missing. Run tools/build/build_exe.bat first.
  popd
  exit /b 1
)
if not exist dist\Leaflet-ocr\leaflet-ocr.exe (
  echo dist\Leaflet-ocr\leaflet-ocr.exe is missing. Run tools/build/build_exe.bat first.
  popd
  exit /b 1
)

set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo Inno Setup 6 was not found: "%ISCC%"
  echo Install it from https://jrsoftware.org/isdl.php
  popd
  exit /b 1
)

"%ISCC%" packaging\installer.iss || goto :err
echo.
echo Complete: Output\Leaflet_Setup_*.exe
popd
goto :eof

:err
echo *** Installer build failed ***
popd
exit /b 1
