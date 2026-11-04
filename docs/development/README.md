# 개발 안내 / Development

명령은 저장소 루트에서 실행하며, 의존성이 설치된 Python 환경을 사용합니다.
Run these commands from the repository root with the prepared Python environment.

| 작업 / Task | 명령 / Command |
| --- | --- |
| 개발 실행 / Launch | `python run.py` 또는 `python run.pyw` |
| 전체 검사 / Full tests | `python -m tools.ci.run_tests` |
| 특정 검사 / One module | `python -m tools.ci.run_tests --single tests.test_release_packaging` |
| 실행 파일 / Executables | `tools\build\build_exe.bat` |
| 설치 파일 / Installer | `tools\build\build_installer.bat` |
| MSIX 준비 / MSIX | [MSIX 안내](MSIX.md) |

실행 파일을 먼저 빌드한 뒤 설치 파일을 만듭니다. 결과물은 기존과 같이 `dist/`와 `Output/`에 생성됩니다.
Build executables before the installer. Outputs remain in `dist/` and `Output/`.

- [소스·의존성·빌드 환경 / Source and build requirements](../../SOURCE_CODE.md)
- [개발 런처와 트레이 동작](RUNTIME.ko.md) / [Development runtime](RUNTIME.md)
- [도구 목록 / Tool reference](../../tools/README.md)
- [기여 시 저장소 규칙 / Repository rules](../../AGENTS.md)

- [라이브러리 업데이트 / Dependency updates](DEPENDENCIES.md)
