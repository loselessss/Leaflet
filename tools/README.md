# 개발 도구 / Developer tools

저장소 루트에서 `python -m` 형식으로 실행합니다. 배치 파일은 실행 위치와 관계없이 저장소 루트에서 작업합니다.
Run Python tools as modules from the repository root. Batch files select the repository root themselves.

| 폴더 / Directory | 용도 / Purpose | 예시 / Example |
| --- | --- | --- |
| `build/` | 실행 파일·아이콘·MSIX·배포 고지 / Build, icons, MSIX, notices | `tools\build\build_exe.bat` |
| `release/` | 소스 묶음·체크섬·한영 릴리스 본문 / Source bundles and release notes | `python -m tools.release.release_notes --help` |
| `ci/` | Windows Qt 검사 분리 실행 / Isolated Windows Qt tests | `python -m tools.ci.run_tests` |
| `windows/` | 사용자별 파일 연결 / Per-user file associations | `python -m tools.windows.register_filetype` |

설정 파일은 [`packaging/`](../packaging/README.md), 빌드 절차는 [개발 안내](../docs/development/README.md)를 참고하세요.
See [packaging configuration](../packaging/README.md) and the [developer guide](../docs/development/README.md).
