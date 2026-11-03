@echo off
pushd "%~dp0..\.." || exit /b 1
REM Build dist\Leaflet with tools/build/build_exe.bat first. Identity arguments are required.
python -m tools.build.build_msix %*
set "LEAFLET_BUILD_RESULT=%errorlevel%"
popd
exit /b %LEAFLET_BUILD_RESULT%
