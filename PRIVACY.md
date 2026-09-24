# Leaflet Privacy Policy / 개인정보 처리방침

Effective date / 시행일: 2026-09-24

## English

### Scope and developer

This policy applies to the Leaflet Windows PDF reader and editor maintained by
the [loselessss/Leaflet project](https://github.com/loselessss/Leaflet), including
its Microsoft Store package and standalone installer.

### Documents and local processing

Leaflet accesses documents you choose to open and processes their text, images,
annotations, and edits on your computer. PDF rendering, search, editing,
conversion, and OCR run locally. Leaflet does not upload your documents or OCR
results to the developer or to a cloud AI service.

Leaflet does not require an account and does not include advertising, usage
analytics, or automatic crash-report uploads to the developer. The developer
does not receive your document contents, reading history, or local settings
through normal use of the application.

### Information stored on your computer

To provide its features, Leaflet may store preferences, recent file paths,
favorites, reading positions, saved and exported files, backups, annotation
sidecars, and recovery copies containing document content and pending edits.
Temporary document copies, OCR inputs and results, and rendering caches may
also contain document-derived content. Downloaded OCR models and standalone
installer updates are stored locally.

For compatibility, settings use `%USERPROFILE%\.spdf.json`; caches, recovery
copies, and models use `%LOCALAPPDATA%\sPDF`. Temporary work files use the Windows
temporary folder. Windows may redirect app-data paths for packaged installations.
Saved documents and annotation sidecars remain in their selected locations.
Local files rely on your Windows account and device security; Leaflet does not
separately encrypt all settings, caches, or temporary files.

### Network connections and other services

- **Microsoft Store:** Microsoft handles Store installation and package updates
  under the [Microsoft Privacy Statement](https://www.microsoft.com/privacy/privacystatement).
  Leaflet's MSIX package disables its standalone EXE updater.
- **Standalone updates:** The standalone version can contact GitHub to check
  releases and download installers. GitHub receives connection information such
  as your IP address and request headers, including the installed app version.
  Document contents and file paths are not included in these requests. See the
  [GitHub Privacy Statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement).
- **Optional OCR models:** If you choose to download the high-quality OCR model,
  Hugging Face and its download infrastructure receive connection and download
  request information. This download does not send your documents; recognition
  subsequently runs locally. See the [Hugging Face Privacy Policy](https://huggingface.co/privacy).
- **User-directed actions:** Web links open in your browser. Printing sends
  document data to your selected printer or print service. Saving to a synced
  or network folder allows that service to handle files under your configuration.

### Retention and your choices

You control which documents you open, edit, save, print, and share. Recent-file
entries can be removed in the app; recovery copies can be discarded through the
recovery interface. Settings and saved files remain until changed or deleted.
Caches are subject to the configured size limit and eviction. Temporary files
are normally cleaned up but may remain after an interruption.

To remove remaining app data, close Leaflet and delete the relevant settings,
cache, recovery, model, or temporary files at the locations above. Deleting
recovery copies can remove unsaved work. Uninstalling does not guarantee removal
of user-created files or all app data.

### Contact and changes

For privacy questions, contact the maintainer through
[Leaflet GitHub Issues](https://github.com/loselessss/Leaflet/issues).
Issues are public: do not attach private documents or personal information.
Information you voluntarily submit there is used to respond to your request
and is also handled by GitHub. Changes to this policy will be published here
with an updated effective date.

## 한국어

### 적용 범위와 개발자

이 방침은 [loselessss/Leaflet 프로젝트](https://github.com/loselessss/Leaflet)가
유지·관리하는 Windows PDF 리더·편집기 Leaflet의 Microsoft Store 패키지와
일반 설치판에 적용됩니다.

### 문서 접근과 로컬 처리

Leaflet은 사용자가 선택한 문서에 접근하여 텍스트, 이미지, 주석과 편집 내용을
사용자의 컴퓨터에서 처리합니다. PDF 표시, 검색, 편집, 변환 및 OCR은 로컬에서
실행됩니다. 문서나 OCR 결과를 개발자 또는 클라우드 AI 서비스로 업로드하지 않습니다.

Leaflet은 계정을 요구하지 않으며 광고, 사용 분석, 개발자에게 자동 전송되는
충돌 보고 기능을 포함하지 않습니다. 일반적인 앱 사용을 통해 개발자가 문서 내용,
열람 기록 또는 로컬 설정을 전달받지 않습니다.

### 컴퓨터에 저장되는 정보

기능 제공을 위해 환경설정, 최근 파일 경로, 즐겨찾기, 읽던 위치, 저장·내보내기한
파일, 백업, 주석 보조 파일, 문서 내용과 미저장 편집 내용을 포함하는 복구본이
저장될 수 있습니다. 임시 문서 복사본, OCR 입력·결과와 렌더링 캐시에도 문서에서
파생된 내용이 포함될 수 있습니다. 다운로드한 OCR 모델과 일반 설치판의 업데이트
설치 파일도 로컬에 저장됩니다.

이전 버전과의 호환을 위해 설정은 `%USERPROFILE%\.spdf.json`을, 캐시·복구본·모델
등은 `%LOCALAPPDATA%\sPDF`를 사용합니다. 임시 작업 파일은 Windows 임시 폴더를
사용합니다. 패키지 설치 환경에서는 Windows가 앱 데이터 경로를 재지정할 수 있습니다.
저장 문서와 주석 보조 파일은 해당 저장 위치에 남습니다. 로컬 파일의 보호는 Windows
계정과 장치 보안에 의존하며, 모든 설정·캐시·임시 파일에 별도 암호화를 적용하지 않습니다.

### 외부 연결과 다른 서비스

- **Microsoft Store:** 스토어 설치와 패키지 업데이트는 Microsoft가
  [Microsoft 개인정보처리방침](https://www.microsoft.com/privacy/privacystatement)에
  따라 처리합니다. Leaflet MSIX 패키지에서는 일반 EXE 업데이트 기능을 끕니다.
- **일반 설치판 업데이트:** GitHub에 릴리스 정보를 요청하고 설치 파일을 다운로드할
  수 있습니다. 이때 GitHub는 IP 주소, 설치된 앱 버전을 포함한 요청 헤더 등 연결
  정보를 받습니다. 문서 내용과 파일 경로는 이 요청에 포함하지 않습니다.
  [GitHub 개인정보처리방침](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement)이 적용됩니다.
- **선택형 OCR 모델:** 사용자가 고품질 OCR 모델 다운로드를 선택하면 Hugging Face와
  그 다운로드 인프라가 연결·다운로드 요청 정보를 받습니다. 이 과정에서 문서를
  전송하지 않으며, 이후 인식은 로컬에서 실행됩니다.
  [Hugging Face 개인정보처리방침](https://huggingface.co/privacy)이 적용됩니다.
- **사용자가 지시한 작업:** 웹 링크는 브라우저에서 열리고 인쇄 시 선택한 프린터나
  인쇄 서비스에 문서 데이터를 전달합니다. 동기화 또는 네트워크 폴더에 저장한 파일은
  사용자의 설정에 따라 해당 서비스에서 처리할 수 있습니다.

### 보관 기간과 삭제

사용자는 열기·편집·저장·인쇄·공유할 문서를 직접 선택합니다. 앱에서 최근 파일 항목을
제거하거나 복구 화면에서 복구본을 폐기할 수 있습니다. 설정과 저장 파일은 변경하거나
삭제할 때까지 유지됩니다. 캐시는 설정된 용량 제한과 정리 정책에 따라 제거됩니다.
임시 파일은 정상적으로 정리되지만 비정상 종료 시 남을 수 있습니다.

남은 앱 데이터를 삭제하려면 Leaflet을 종료한 뒤 위 경로에서 해당 설정·캐시·복구본·
모델·임시 파일을 삭제할 수 있습니다. 복구본 삭제 시 미저장 작업을 잃을 수 있습니다.
앱 제거만으로 사용자가 만든 파일이나 모든 앱 데이터의 삭제를 보장하지는 않습니다.

### 문의 및 방침 변경

개인정보 관련 문의는 [Leaflet GitHub Issues](https://github.com/loselessss/Leaflet/issues)를
통해 유지관리자에게 전달할 수 있습니다. 공개 게시판이므로 비공개 문서나 개인정보를
첨부하지 마세요. 직접 제출한 정보는 문의 응답을 위해 사용되며 GitHub에서도 처리됩니다.
방침이 변경되면 이 문서의 시행일과 내용을 갱신합니다.
