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
set "FXC=%WindowsSdkDir%bin\%WindowsSDKVersion%x64\fxc.exe"
if not exist "%FXC%" (
  echo Windows SDK shader compiler fxc.exe not found.
  exit /b 1
)
"%FXC%" /nologo /T ps_4_0 /E main /D D2D_FULL_SHADER /D D2D_ENTRY=main /Gis /O3 ^
  /I "%WindowsSdkDir%Include\%WindowsSDKVersion%um" ^
  /Fh "%~dp0bin\spdf_mask_lerp_shader.h" /Vn spdf_mask_lerp_shader ^
  "%~dp0d2d_renderer\mask_lerp.hlsl"
if errorlevel 1 exit /b %errorlevel%
cl /nologo /std:c++17 /EHsc /W4 /WX /O2 /LD /DUNICODE /D_UNICODE ^
  /Fo"%~dp0bin\spdf_d2d.obj" /Fd"%~dp0bin\spdf_d2d.pdb" ^
  /I"%~dp0bin" /I"%~dp0d2d_renderer" "%~dp0d2d_renderer\spdf_d2d.cpp" ^
  /link /OUT:"%~dp0bin\spdf_d2d_renderer.dll" ^
  /IMPLIB:"%~dp0bin\spdf_d2d.lib" /PDB:"%~dp0bin\spdf_d2d_renderer.pdb" ^
  d3d11.lib dxgi.lib d2d1.lib dwrite.lib dxguid.lib ole32.lib
exit /b %errorlevel%
