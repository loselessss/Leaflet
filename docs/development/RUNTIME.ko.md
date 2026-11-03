# 개발 실행 환경


Python, PyQt5, PyMuPDF, Direct2D, RapidOCR로 개발했습니다.

`run.py`와 `run.pyw`는 저장소의 `.venv`가 있으면 먼저 해당 Python으로 전환합니다.
Windows 기본 Python과 네이티브 렌더러의 MuPDF 버전이 달라지는 것을 방지합니다.
`.venv`가 없는 소스 환경에서는 직접 선택한 Python과 같은 SDK로 네이티브 모듈을 빌드해야 합니다.
설치본과 다른 프로그램의 내부 모듈 실행에는 이 개발 런처 전환이 적용되지 않습니다.

`run.pyw`는 콘솔 없이 새 개발 프로세스를 열고 트레이 연결·상주를 사용하지 않습니다.
창을 닫으면 종료하며, 저장된 트레이 설정은 바꾸지 않습니다. `run.py`에도
`--no-resident`를 붙이면 같은 방식으로 실행할 수 있습니다.

[소스·빌드 안내](../../SOURCE_CODE.md),
[리더 API 연동](../architecture/READER_INTEGRATION.md),
[Windows 렌더러](../architecture/WINDOWS_RENDERING_BACKEND.md),
[MSIX 패키징](MSIX.md)을 참고하세요.
