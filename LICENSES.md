# sPDF licensing and third-party notices / 라이선스·오픈소스 고지

## sPDF

Copyright (c) 2026 loselessss and contributors.

sPDF's original source code is licensed under the MIT License. See
[LICENSE](LICENSE) for the complete terms. This declaration applies to the
sPDF application source, its OCR worker, native renderer, build scripts, tests
and documentation to the extent those files are owned by the sPDF authors.

sPDF가 직접 작성한 소스 코드는 MIT License로 제공합니다. 전체 조건은
[LICENSE](LICENSE)에 있습니다. 이 선언은 sPDF 작성자가 권리를 보유한 범위에서
앱 소스·OCR 워커·네이티브 렌더러·빌드 스크립트·테스트·문서에 적용합니다.

### Distribution scope / 배포 적용 범위

The MIT license does not relicense third-party components. The current packaged
application includes PyMuPDF/MuPDF under AGPL v3 and PyQt5 under GPL v3 unless
the distributor has obtained appropriate commercial licenses. Therefore a
packaged build using those open-source editions is not distributed under MIT
terms alone. Every distributor must comply with all applicable dependency terms.

MIT는 외부 구성요소의 라이선스를 변경하지 않습니다. 현재 설치본은 배포자가
적절한 상용 라이선스를 별도로 취득하지 않은 경우 AGPL v3의 PyMuPDF/MuPDF와
GPL v3의 PyQt5를 포함합니다. 따라서 해당 오픈소스판으로 만든 설치본은 MIT
조건만으로 배포되는 것이 아니며, 배포자는 적용되는 모든 의존성 조건을 지켜야 합니다.

## Third-party components / 외부 구성요소

Each component keeps its own copyright and license. The following is an
overview, not a replacement for its full notices. Packaged builds also include
`third-party/` with the actual build-environment versions, metadata and bundled
license/notice files. Optional engines downloaded separately are not covered
by this inventory and must retain their own notices.

각 구성요소의 저작권·라이선스는 그대로 유지됩니다. 아래 표는 요약이며 원문을
대신하지 않습니다. 설치본의 `third-party/`에는 실제 빌드 환경의 버전·메타데이터·
라이선스·고지 사본을 포함합니다. 별도로 다운로드하는 선택형 엔진은 해당 엔진의
라이선스도 확인해야 합니다.

| Component / 구성요소 | License / 라이선스 | Upstream / 원본 |
| --- | --- | --- |
| PyMuPDF / MuPDF | AGPL v3 | [Artifex / PyMuPDF](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright) |
| PyQt5 | GPL v3 | [Riverbank Computing](https://www.riverbankcomputing.com/software/pyqt/) |
| Qt libraries supplied by PyQt5-Qt5 | LGPL v3 / GPL v3, plus component-specific notices | [Qt licensing](https://www.qt.io/licensing/open-source-lgpl-obligations) |
| PyQt5-sip | BSD-style; see packaged version's notice | [SIP](https://github.com/Python-SIP/sip) |
| RapidOCR | Apache 2.0 | [RapidAI](https://github.com/RapidAI/RapidOCR) |
| PaddleOCR recognition models | Apache 2.0 | [PaddlePaddle](https://github.com/PaddlePaddle/PaddleOCR) |
| ONNX Runtime | MIT, with third-party notices | [Microsoft](https://github.com/microsoft/onnxruntime) |
| OpenCV | Apache 2.0, with bundled component notices | [OpenCV](https://github.com/opencv/opencv-python) |
| NumPy | BSD 3-Clause, with bundled component notices | [NumPy](https://numpy.org/) |
| Pillow | HPND-style, with bundled component notices | [Pillow](https://github.com/python-pillow/Pillow) |
| Python runtime | PSF license and included notices | [Python](https://docs.python.org/3/license.html) |
| PyInstaller bootloader | GPL with the PyInstaller distribution exception | [PyInstaller](https://pyinstaller.org/en/stable/license.html) |

Copies of the AGPL, GPL, LGPL and Apache texts are supplied in `licenses/`.
The LGPL text includes the GPL text it incorporates. Original
copyright, attribution and NOTICE files must also be retained; copying only
the generic license text does not replace those obligations.

AGPL·GPL·LGPL·Apache 원문은 `licenses/`에 포함합니다. 각 프로젝트의
저작권·출처·NOTICE도 보존해야 하며, 일반 라이선스 원문만 넣는 것으로 이를
대체하지 않습니다.

## Source and redistribution / 소스 제공·재배포

See [SOURCE_CODE.md](SOURCE_CODE.md) for version-matched sources, dependencies
and build instructions. Supplying an executable requires the applicable
corresponding-source access and license notices, not merely a public repository.
If you modify AGPL-covered dependencies for remote network use, review AGPL
section 13. Embedding sPDF or using read-only mode does not create an exemption
from applicable third-party licenses.
Ordinary PDF documents processed by sPDF do not become AGPL merely through use.

버전에 맞는 소스·의존성·빌드 안내는 [SOURCE_CODE.md](SOURCE_CODE.md)를 참고하세요.
실행 파일 배포에는 대응 소스 접근과 고지가 필요하며, 저장소 공개만으로 모든
조건을 충족했다고 보지 않습니다. AGPL 적용 의존성을 수정해 네트워크 서비스로
제공할 경우 AGPL 13조도 검토해야 합니다. 내장 모드나 읽기 전용 모드는 적용되는
외부 라이선스의 예외가 아니며, 일반 PDF 문서가 sPDF로 처리되었다는 이유만으로
AGPL이 되지는 않습니다.
