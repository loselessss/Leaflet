# 패키징 설정 / Packaging configuration

- `spdf.spec`: PyInstaller GUI·독립 OCR 작업 프로세스 구성 / GUI and isolated OCR builds.
- `installer.iss`: Inno Setup 설치·파일 연결·바로가기 / Installation, file associations, shortcuts.

`installer.iss`의 `MyAppVersion`은 `pdfeditor/meta.py`의 `APP_VERSION`과 동일하게 유지합니다.
Keep `MyAppVersion` synchronized with `APP_VERSION` in `pdfeditor/meta.py`.

루트에서 `tools\build\build_exe.bat` 실행 후 `tools\build\build_installer.bat`를 실행합니다.
From the root, build executables first, then the installer. See the [developer guide](../docs/development/README.md).
