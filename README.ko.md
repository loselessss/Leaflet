# Leaflet

[English](README.md) | 한국어

GPU 가속으로 부드럽게 확대·이동하고, 주석·페이지 구성·텍스트 편집·한국어와 영어의
오프라인 OCR을 사용할 수 있는 Windows PDF 리더·편집기입니다.

**버전: 1.39.0 (2026-11-06)** · Windows · 한국어·영어

## 다운로드

**안정 버전은 [Microsoft Store](https://apps.microsoft.com/detail/9PCB1BH4WBDT)에서 설치하세요.**

일반 설치 파일은 [GitHub 릴리스](https://github.com/loselessss/Leaflet/releases/latest)에서도 받을 수 있습니다.
최근 개선 사항은 [릴리스 노트](docs/releases/RELEASE_NOTES.ko.md)에서 확인하세요.

## 주요 기능

- **읽기 순서로 복사:** Ctrl+Shift+C로 선택한 글이나 현재 페이지의 읽기 순서를 PC에서 분석합니다. 작업 후 모델 메모리는 정리됩니다.
- **읽기:** 최대 3200% 확대, 부드러운 화면 이동, 검색·책갈피·두 장 보기와 탭의 창 분리.
- **화면 테마:** 리본의 다크 모드 버튼에서 직접 전환하거나 Windows 설정을 따르며 PDF의 원본 색상은 유지합니다.
- **화면 테마:** 보기 → 다크 모드에서 ‘문서 포함 / 문서 제외’를 바로 선택합니다. 문서 색상도 앱 테마를 따르며 리본의 달은 포함 여부를 기억합니다. 첫 화면에서 읽기·편집 모드를 바꿀 수 있습니다. PDF 파일은 변경하지 않습니다.
- **주석:** 형광펜·메모를 추가하고 별도 관리 창에서 검색·편집.
- **편집:** 텍스트 수정과 이미지·도형 추가 및 배치 조정.
- **페이지 구성:** 순서 변경·회전·자르기·병합·분리·추출.
- **스캔 문서 인식:** 한국어·영어 OCR로 검색 가능한 텍스트 추가.
- **출력:** 인쇄, PDF 압축과 PDF·이미지 변환.

시작 메뉴의 **Leaflet** 또는 **Leaflet 편집기**로 실행합니다.
**편집 → 편집 창에서 열기**(Ctrl+E)와 **리더로 돌아가기**로 전환하며, **F1**을 누르면 도움말을 볼 수 있습니다.

텍스트는 선택한 줄이나 상자 안에서 편집하며 대체 글꼴의 모양은 원본과 다를 수 있습니다.
GPU 모드에서는 복잡한 그림의 표현이 조금 달라질 수 있으므로 정밀 확인에는 CPU 모드를 사용하세요.
편집 방법·단축키·AI/EPS 지원 범위는 [사용 안내](docs/usage/GUIDE.ko.md)를 참고하세요.

## 문서와 개발

| 찾는 내용 | 바로가기 |
| --- | --- |
| 전체 문서 | [문서 목차](docs/README.md) |
| 빌드와 소스 제공 | [소스·빌드 안내](SOURCE_CODE.md) |
| 개발 실행과 테스트 | [개발 안내](docs/development/README.md) |
| 리더 API | [리더 연동](docs/architecture/READER_INTEGRATION.md) |
| 진행 중인 변경과 이력 | [변경 이력](docs/releases/CHANGELOG.ko.md) |

앱 코드는 `pdfeditor/`, 네이티브 렌더러는 `native/`, 개발 도구는 `tools/`,
패키징 설정은 `packaging/`에 있습니다. 개발 환경 준비 후 `python run.py` 또는
`python run.pyw`로 실행합니다.

## 라이선스와 개인정보

Leaflet이 직접 작성한 코드는 [MIT License](LICENSE)로 제공합니다. 외부 구성요소는
각자의 조건을 유지하며, AGPL판 PyMuPDF와 GPL판 PyQt5를 사용하는 설치본에는 해당 조건도 적용됩니다.
[오픈소스 고지](LICENSES.md), [소스 제공 안내](SOURCE_CODE.md), [개인정보 처리방침](PRIVACY.md)을 확인하세요.
