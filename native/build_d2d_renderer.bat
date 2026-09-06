@echo off
setlocal
set "VCVARS="
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if exist "%VSWHERE%" (
  for /f "usebackq tokens=*" %%I in (`"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath`) do set "VCVARS=%%I\VC\Auxiliary\Build\vcvars64.bat"
)
if not defined VCVARS set "VCVARS=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if not exist "%VCVARS%" (
  echo Visual Studio C++ x64 build tools not found.
  exit /b 1
)
call "%VCVARS%" >nul
if errorlevel 1 exit /b %errorlevel%

if not exist "%~dp0bin" mkdir "%~dp0bin"
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /LD /DUNICODE /D_UNICODE ^
  /Fo"%~dp0bin\spdf_d2d.obj" /Fd"%~dp0bin\spdf_d2d.pdb" ^
  /I"%~dp0d2d_renderer" "%~dp0d2d_renderer\spdf_d2d.cpp" ^
  /link /OUT:"%~dp0bin\spdf_d2d_renderer.dll" ^
  /IMPLIB:"%~dp0bin\spdf_d2d.lib" /PDB:"%~dp0bin\spdf_d2d_renderer.pdb" ^
  d3d11.lib dxgi.lib d2d1.lib dwrite.lib dxguid.lib
exit /b %errorlevel%
