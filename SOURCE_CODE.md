# Source code and rebuilding / 소스 코드·다시 빌드하기

## Get the matching version / 같은 버전 받기

Open **Help → Open-source Licenses → Source code** in sPDF. The link points to
the release for the version you are running, not to the moving `main` branch:

- [All sPDF releases](https://github.com/loselessss/sPDF/releases)
- Under the same release's Assets, download `sPDF_Source_VERSION.zip` and
  `sPDF_Dependency_Sources_VERSION.md` together. GitHub-generated tag ZIPs alone
  do not contain the build inventory and dependency-source directions.
- The ZIP contains the tagged sPDF source, build scripts and the actual build
  environment's package versions and notices. Unrelated project files and
  personal/untracked files are excluded.
- Dependency sources are provided through exact-version upstream source
  archive links (and available SHA-256 values) in the dependency document.
  The application ZIP alone is **not** all third-party corresponding source.
- Earlier releases may not have these additional assets. Their Git tags are
  still available; do not assume their complete binary-source correspondence
  or licensing has been audited retroactively.

sPDF의 **도움말 → 오픈소스 라이선스 → 소스 코드**에서 실행 중인 버전의 릴리스로
이동할 수 있습니다. 같은 릴리스의 Assets에서 소스 ZIP과 의존성 소스 안내를
함께 받으세요.
ZIP에는 해당 태그의 sPDF 소스·빌드 스크립트·실제 빌드 환경의 패키지 버전·고지가
들어갑니다. sPDF와 무관한 프로젝트 파일과 개인·미추적 파일은 제외합니다.
외부 라이브러리 원본은 의존성 안내의 **같은 버전 소스 링크**에서 받을 수 있으며,
sPDF ZIP만으로 외부 라이브러리 소스 전체가 제공되는 것은 아닙니다.
이전 릴리스의 소스 대응·라이선스까지 소급 검증한 것은 아닙니다.

## Rebuild on Windows / Windows에서 빌드

1. Extract the source ZIP. Use the Python version and architecture recorded in
   `third-party/build-environment.json` (official builds use 64-bit Python 3.12).
2. Create a clean virtual environment. Install the exact versions recorded in
   `third-party/build-requirements.txt` with `python -m pip install -r`.
3. Run `python ci_test_runner.py`. Install Inno Setup 6 at the location documented
   by `build_installer.bat`.
4. Run `build_exe.bat`, then `build_installer.bat`. Run with the virtual
   environment's Python on PATH. Outputs appear in `dist/` and `Output/`.
5. To change a dependency, obtain its source from the dependency document,
   follow its included build instructions, install your rebuilt wheel, and
   rebuild sPDF. For PyMuPDF, retain its matching MuPDF source/configuration;
   for PyQt5, retain the matching Qt source and PyQt build tooling.

소스 ZIP을 풀고 `third-party/build-environment.json`의 Python 환경과
`third-party/build-requirements.txt`의 패키지 버전을 사용합니다.
테스트 후 `build_exe.bat` → `build_installer.bat` 순서로 실행하세요.
라이브러리 자체를 수정하려면 해당 소스의 빌드 설명을 따라 새 패키지를 만든 뒤
sPDF를 다시 빌드합니다. 소스 ZIP 밖의 의존성 소스도 필요할 수 있습니다.
이 안내는 빌드 절차를 제공하며, 서명·타임스탬프까지 동일한 실행 파일 생성을
보장한다는 뜻은 아닙니다.

## Maintainer release checklist / 배포자 확인 사항

- Build in a clean environment. `build_legal.py` records distribution metadata,
  notices and exact package versions without importing OCR or Qt into the GUI.
- `create_source_bundle.py` uses a clean Git tag matching `APP_VERSION`, never
  a recursive copy of the working folder. It resolves exact-version source
  archives for PyMuPDF and PyQt5 and the matching Qt source distribution.
  Generated icons and the rebuilt native DLL may differ; their tagged
  generators and native source/build script are included. Other local source changes stop publication.
- Publish the source ZIP, its checksum and dependency source document as Assets
  in the same public release as the installers. Source preparation or publication
  failures stop installer publication. Sources remain publicly downloadable
  without Actions artifact access or an expiry date.
- The installer SHA-256 is included in the release body; GitHub asset digests
  continue to protect updater downloads. Existing historic releases are not rewritten.
- MSIX preparation and signing directions are in [MSIX.md](MSIX.md).
- Check upstream source links remain accessible for as long as required. If
  an upstream source disappears, host an exact copy yourself; a dead URL is
  not a source offer. Retain dependency archives and any local patches.
- Confirm bundled native DLLs, codecs, fonts and OCR models are covered by
  their own notices and matching sources where required. Package metadata
  collection is an aid, **not a complete legal audit** of wheel contents.
- Do not silently replace upstream wheels with patched binaries. Add matching
  modified sources, build instructions and change notices to the release.
- For physical/offline distribution, provide corresponding sources with it
  or use another valid license mechanism. This document is not a written
  three-year source offer and does not invent a support commitment.

공식 배포에서는 대응 소스 준비 실패 시 게시하지 않습니다. 외부 소스 링크의
유지 책임은 배포자에게 있으므로, 링크가 사라지면 같은 소스를 직접 제공해야
합니다. 네이티브 DLL·코덱·폰트·OCR 모델의 고지와 필요한 대응 소스는 별도로
검토하세요. 자동 목록은 완전한 법률 검토를 대신하지 않습니다.
물리 매체 배포 시에는 그 방식에 맞는 소스 제공 조건을 별도로 충족해야 합니다.

## References / 근거

- [AGPL v3, sections 1, 4–6 and 13](https://www.gnu.org/licenses/agpl-3.0.html)
- [GNU FAQ: sources on another server](https://www.gnu.org/licenses/gpl-faq.html#SourceAndBinaryOnDifferentSites)
- [PyMuPDF source builds](https://pymupdf.readthedocs.io/en/latest/installation.html)
- [PyQt source distributions](https://www.riverbankcomputing.com/software/pyqt/download)
- [Qt open-source obligations](https://www.qt.io/licensing/open-source-lgpl-obligations)
