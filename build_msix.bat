@echo off
REM Build dist\Leaflet with build_exe.bat first. Identity arguments are required.
python "%~dp0build_msix.py" %*
exit /b %errorlevel%
