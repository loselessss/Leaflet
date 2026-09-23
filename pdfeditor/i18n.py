"""User-interface translation support.

The application ships English and Korean user-interface modes. Korean strings
in the source act as stable message keys, while English lives in a catalog.
More languages can be added without changing document or OCR language handling.
"""

import os
import re


DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = ("en", "ko")
_language = DEFAULT_LANGUAGE

# Qt standard buttons use the Qt/Windows translation catalog rather than the
# application's Korean source strings, so they otherwise remain English on a
# Korean Leaflet interface.
QT_STANDARD_BUTTONS_KO = {
    "Save": "저장",
    "Discard": "저장 안 함",
    "Don't Save": "저장 안 함",
    "Cancel": "취소",
    "Close": "닫기",
    "OK": "확인",
    "Yes": "예",
    "No": "아니요",
    "Apply": "적용",
    "Retry": "다시 시도",
}


EN = {
    # Menus and commands
    "파일(&F)": "&File",
    "편집(&E)": "&Edit",
    "페이지 구성(&P)": "Page &Organization",
    "주석(&A)": "&Annotations",
    "보기(&V)": "&View",
    "도움말(&H)": "&Help",
    "열기...": "Open...",
    "새 탭": "New Tab",
    "새 창": "New Window",
    "최근 파일": "Recent Files",
    "즐겨찾기": "Favorites",
    "저장": "Save",
    "저장 안 함": "Don't Save",
    "다른 이름으로 저장...": "Save As...",
    "인쇄...": "Print...",
    "인쇄 미리보기...": "Print Preview...",
    "인쇄 미리보기": "Print Preview",
    "인쇄 설정": "Print Settings",
    "미리보기를 확인하면서 출력 옵션을 선택하세요.":
        "Choose output options while checking the preview.",
    "인쇄 방식": "Print Sides",
    "인쇄 방식:": "Print Sides:",
    "프린터:": "Printer:",
    "기본 프린터": "Default Printer",
    "인쇄 범위:": "Print Range:",
    "쪽 지정:": "Pages:",
    "역순 인쇄": "Reverse Order",
    "용지 방향:": "Orientation:",
    "자동 (문서 방향)": "Auto (Match Document)",
    "세로": "Portrait",
    "가로": "Landscape",
    "매수:": "Copies:",
    "단면 인쇄": "Print One Sided",
    "양면 인쇄 (긴 쪽 넘김)": "Print on Both Sides (Flip on Long Edge)",
    "양면 인쇄 (짧은 쪽 넘김)": "Print on Both Sides (Flip on Short Edge)",
    "PDF 용량 줄이기...": "Reduce PDF Size...",
    "이미지를 PDF로...": "Images to PDF...",
    "이미지를 PDF로": "Images to PDF",
    "PDF를 이미지로...": "PDF to Images...",
    "PDF를 이미지로": "PDF to Images",
    "PDF 용량 줄이기": "Reduce PDF Size",
    "압축한 PDF 저장": "Save Compressed PDF",
    "PDF 용량을 줄이는 중입니다...": "Reducing PDF size...",
    "용량 줄이기 실패": "PDF Compression Failed",
    "PDF 용량 줄이기 완료": "PDF Compression Complete",
    "무손실 최적화": "Lossless optimization",
    "화질을 유지하고 중복·미사용 객체와 압축되지 않은 데이터를 정리합니다.":
        "Preserve quality while removing duplicate, unused, and uncompressed data.",
    "균형 (권장)": "Balanced (Recommended)",
    "고해상도 이미지를 150 DPI, JPEG 품질 75로 조정합니다.":
        "Adjust high-resolution images to 150 DPI and JPEG quality 75.",
    "강하게 줄이기": "Strong compression",
    "고해상도 이미지를 96 DPI, JPEG 품질 55로 조정합니다.":
        "Adjust high-resolution images to 96 DPI and JPEG quality 55.",
    "탐색기에서 현재 위치 열기": "Open File Location",
    "탭 닫기": "Close Tab",
    "종료": "Exit",
    "실행 취소": "Undo",
    "다시 실행": "Redo",
    "복사": "Copy",
    "현재 페이지 모두 선택": "Select All on Current Page",
    "텍스트 편집 모드": "Edit Text Mode",
    "찾기...": "Find...",
    "다음 찾기": "Find Next",
    "이전 찾기": "Find Previous",
    "페이지 구성...": "Organize Pages...",
    "오른쪽으로 회전": "Rotate Clockwise",
    "왼쪽으로 회전": "Rotate Counterclockwise",
    "현재 페이지 삭제": "Delete Current Page",
    "PDF 병합...": "Merge PDFs...",
    "PDF 분리...": "Split PDF...",
    "현재 페이지 추출...": "Extract Current Page...",
    "선택 영역 형광펜": "Highlight Selection",
    "메모 추가 (위치 클릭)": "Add Note (Click Location)",
    "메모 모아보기": "Notes Panel",
    "현재 페이지 OCR": "OCR Current Page",
    "전체 문서 OCR (텍스트 없는 페이지만)": "OCR Document (Pages Without Text)",
    "AI 고품질 OCR 설정...": "High-quality AI OCR Settings...",
    "확대": "Zoom In",
    "축소": "Zoom Out",
    "1% 확대": "Zoom In 1%",
    "1% 축소": "Zoom Out 1%",
    "폭 맞춤": "Fit Width",
    "쪽 맞춤": "Fit Page",
    "두 장 보기": "Two-page View",
    "왼쪽 패널": "Left Panel",
    "없음": "None",
    "페이지 미리보기": "Page Thumbnails",
    "책갈피": "Bookmarks",
    "책갈피 없음": "No bookmarks",
    "이전 보기": "Back to Previous View",
    "다음 보기": "Forward to Next View",
    "현재 페이지 책갈피 추가": "Bookmark Current Page",
    "책갈피 이름 변경": "Rename Bookmark",
    "책갈피 삭제": "Delete Bookmark",
    "제목:": "Title:",
    "문서 변경 실패": "Document Change Failed",
    "페이지 여백 자르기...": "Crop Page Margins...",
    "페이지 여백 자르기": "Crop Page Margins",
    "TXT 책갈피 가져오기...": "Import Bookmarks from TXT...",
    "TXT 책갈피 가져오기": "Import Bookmarks from TXT",
    "워터마크 추가...": "Add Watermark...",
    "워터마크 추가": "Add Watermark",
    "워터마크 문구:": "Watermark text:",
    "글자 크기:": "Font size:",
    "투명도:": "Opacity:",
    "기울기:": "Angle:",
    "적용 범위:": "Apply to:",
    "이미지 형식:": "Image format:",
    "해상도:": "Resolution:",
    "이미지 저장 폴더": "Image Output Folder",
    "파일 덮어쓰기": "Overwrite Files",
    "현재 페이지": "Current Page",
    "지정한 페이지": "Page Range",
    "전체 페이지": "All Pages",
    "선택 초기화": "Reset Selection",
    "페이지 범위": "Page Range",
    "미저장 작업 복구...": "Recover Unsaved Work...",
    "미저장 작업 복구": "Recover Unsaved Work",
    "선택한 작업 복구": "Restore Selected",
    "선택한 사본 삭제": "Discard Selected Copies",
    "(제목 없음)": "(Untitled)",
    "왼쪽 패널 전환": "Cycle Left Panel",
    "프레젠테이션 모드": "Presentation Mode",
    "전체화면": "Full Screen",
    "다음 페이지": "Next Page",
    "이전 페이지": "Previous Page",
    "텍스트 선택 도구": "Text Selection Tool",
    "손 도구": "Hand Tool",
    "즐겨찾기 추가": "Add to Favorites",
    "즐겨찾기에서 제거": "Remove from Favorites",
    "즐겨찾기에 추가": "Add to Favorites",
    "최근 목록에서 제거": "Remove from Recent Files",
    "명령 모음": "Command Bar",
    "사용법": "User Guide",
    "업데이트 확인...": "Check for Updates...",
    "PDF 기본 프로그램 / 브라우저 설정...": "Default PDF App / Browser Settings...",
    "오픈소스 라이선스": "Open-source Licenses",
    "정보": "About",
    "지원하지 않는 링크": "Unsupported Link",
    "이 위치에는 링크가 없습니다": "There is no link at this location",
    "목록 지우기": "Clear List",
    "언어": "Language",
    "화면 렌더러": "Display Renderer",
    "자동 (권장)": "Auto (Recommended)",
    "화면 렌더러 변경": "Display Renderer Change",
    "화면 렌더러 변경 사항은 Leaflet을 다시 실행하면 적용됩니다.":
        "The display renderer change will take effect after restarting Leaflet.",
    "왼쪽 패널": "Left Panel",
    "한국어": "Korean",
    "언어 변경": "Language Change",
    "언어 변경 사항은 Leaflet을 다시 실행하면 적용됩니다.":
        "The language change will take effect after restarting Leaflet.",
    "(비어 있음)": "(Empty)",
    "(빈 탭)": "(Empty Tab)",
    "현재 파일을 즐겨찾기에서 제거": "Remove Current File from Favorites",
    "★ 현재 파일을 즐겨찾기에 추가": "★ Add Current File to Favorites",
    "즐겨찾기 해제": "Remove from Favorites",
    "현재 PDF를 즐겨찾기에서 제거합니다": "Remove the current PDF from favorites",
    "현재 PDF를 즐겨찾기에 추가합니다": "Add the current PDF to favorites",
    "PDF를 연 뒤 즐겨찾기에 추가할 수 있습니다": "Open a PDF before adding it to favorites",
    "10~800% 범위를 1% 단위로 입력": "Enter a value from 10% to 800% in 1% steps",
    "검색어 입력 후 Enter (F3 다음 / Shift+F3 이전)":
        "Enter search text (F3 next / Shift+F3 previous)",
    "이전 검색 결과 (Shift+F3)": "Previous result (Shift+F3)",
    "다음 검색 결과 (F3)": "Next result (F3)",

    # Home and document chrome
    "PDF 열기...": "Open PDF...",
    "PDF/Illustrator 파일 열기...": "Open PDF/Illustrator File...",
    "PDF 파일 열기...": "Open PDF File...",
    "v%s — PDF 보기 · 주석 · OCR": "v%s — PDF viewing · annotations · OCR",
    "★ 즐겨찾기": "★ Favorites",
    "(별표한 파일이 없습니다 — 최근 파일에서 우클릭)":
        "(No favorite files — right-click a recent file)",
    "(최근 연 파일이 없습니다)": "(No recently opened files)",
    "닫기": "Close",
    "적용": "Apply",
    "취소": "Cancel",
    "나중에": "Later",

    # Common dialog titles and messages
    "열기 실패": "Open Failed",
    "PDF 열기": "Open PDF",
    "PDF 파일 (*.pdf)": "PDF Files (*.pdf)",
    "PDF/Illustrator 파일 열기": "Open PDF/Illustrator File",
    "PDF/Illustrator 파일 (*.pdf *.ai);;PDF 파일 (*.pdf);;Illustrator 파일 (*.ai)":
        "PDF/Illustrator Files (*.pdf *.ai);;PDF Files (*.pdf);;Illustrator Files (*.ai)",
    "PDF 파일 여러 개 선택": "Select PDF Files",
    "저장할 PDF": "Save PDF",
    "모든 파일 (*)": "All Files (*)",
    "저장 실패": "Save Failed",
    "인쇄": "Print",
    "인쇄 실패": "Print Failed",
    "페이지 이동": "Move Page",
    "페이지 삭제": "Delete Pages",
    "범위 확인": "Check Page Range",
    "암호 입력": "Enter Password",
    "암호 필요": "Password Required",
    "이 PDF는 암호가 걸려 있습니다.\n비밀번호를 입력하세요:":
        "This PDF is password-protected.\nEnter the password:",
    "비밀번호:": "Password:",
    "텍스트 편집": "Edit Text",
    "텍스트 추가": "Add Text",
    "내용:": "Text:",
    "메모 추가": "Add Note",
    "메모 편집": "Edit Note",
    "메모 삭제": "Delete Note",
    "메모 모아보기": "Notes",
    "OCR 사용 불가": "OCR Unavailable",
    "OCR 실패": "OCR Failed",
    "AI 고품질 OCR 설정": "High-quality AI OCR Settings",
    "VL 모델 다운로드": "Download VL Model",
    "VL 사양 확인": "VL System Check",
    "VL 준비 필요": "VL Setup Required",
    "다운로드 실패": "Download Failed",
    "다운로드 미완료": "Download Incomplete",
    "AI 고품질(VL)": "High-quality AI (VL)",
    "VL 모델 다운로드 중... (약 2GB, 네트워크에 따라 수 분)":
        "Downloading the VL model... (about 2 GB; this may take several minutes)",
    "VL 모델 설치 완료 — OCR 엔진: AI 고품질(VL)":
        "VL model installed — OCR engine: High-quality AI (VL)",
    "다운로드가 끝났지만 모델 확인에 실패했습니다.\n다시 시도해 주세요.":
        "The download finished, but the model could not be verified.\nTry again.",
    "페이지 구성": "Organize Pages",
    "추가할 PDF 선택": "Select a PDF to Add",
    "추가할 PDF/Illustrator 파일 선택":
        "Select a PDF/Illustrator File to Add",
    "삭제 불가": "Cannot Delete",
    "문서에는 최소 한 페이지가 남아 있어야 합니다.":
        "The document must contain at least one page.",
    "마지막 한 페이지는 삭제할 수 없습니다.": "The last remaining page cannot be deleted.",
    "페이지를 선택해 끌어 놓으세요. 외부 PDF를 목록에 놓으면 해당 위치에 자동으로 삽입됩니다.":
        "Select and drag pages to reorder them. Drop an external PDF into the list to insert it at that position.",
    "PDF 추가...": "Add PDF...",
    "선택 페이지 삭제": "Delete Selected Pages",
    "여러 페이지 선택 시:": "When multiple pages are selected:",
    "선택 페이지를 한 묶음으로 이동": "Move selected pages as a group",
    "드래그한 한 페이지만 이동": "Move only the dragged page",
    "삭제할 페이지를 선택하세요.": "Select the pages to delete.",
    "PDF 기본 프로그램 및 브라우저 설정": "Default PDF App and Browser Settings",
    "Windows 기본 앱 설정 열기": "Open Windows Default Apps Settings",
    "Microsoft Edge에서 PDF를 Leaflet으로 열기": "Open PDFs from Microsoft Edge in Leaflet",
    "Google Chrome에서 PDF를 Leaflet으로 열기": "Open PDFs from Google Chrome in Leaflet",
    "Mozilla Firefox에서 PDF를 Leaflet으로 열기": "Open PDFs from Mozilla Firefox in Leaflet",
    "설정 열기 실패": "Could Not Open Settings",
    "브라우저 설정 실패": "Browser Settings Failed",
    "브라우저 설정 완료": "Browser Settings Updated",
    "RapidOCR로": "Use RapidOCR",
    "AI 고품질로": "Use High-quality AI OCR",

    # Update UI
    "Leaflet 업데이트": "Leaflet Update",
    "현재 버전": "Current Version",
    "새 버전": "New Version",
    "설치 파일": "Installer",
    "변경 내용": "What's New",
    "릴리스 페이지": "Release Page",
    "다운로드 후 설치": "Download and Install",
    "크기 정보 없음": "Size unavailable",
    "등록 대기 중": "Pending upload",
    "변경 기록이 없습니다.": "No release notes are available.",
    "업데이트 다운로드 실패": "Update Download Failed",
    "업데이트 확인 실패": "Update Check Failed",
    "업데이트 실행 실패": "Update Launch Failed",
    "업데이트 설치 파일을 다운로드하는 중입니다…": "Downloading the update installer…",
    "다운로드와 SHA-256 검증을 마쳤습니다.": "Download and SHA-256 verification completed.",
    "다운로드를 취소하는 중입니다…": "Cancelling the download…",
    "이 릴리스에는 아직 Windows 설치 파일이 없습니다.":
        "This release does not have a Windows installer yet.",
    "설치 파일 무결성 정보가 없어 앱 안에서는 자동 설치하지 않습니다.":
        "Automatic installation is unavailable because installer integrity information is missing.",

    # Status text
    "즐겨찾기에서 제거됨": "Removed from favorites",
    "즐겨찾기에 추가됨": "Added to favorites",
    "손 도구 — PDF를 클릭한 채 드래그해 이동합니다":
        "Hand tool — click and drag to pan the PDF",
    "텍스트 선택 도구 — 글자를 드래그해 선택합니다":
        "Text selection tool — drag across text to select it",
    "먼저 텍스트를 드래그로 선택하세요": "Select text by dragging first",
    "메모를 붙일 위치를 클릭하세요 (Esc 취소)": "Click where you want to add the note (Esc to cancel)",
    "OCR 완료 — 인식된 텍스트가 없습니다": "OCR completed — no text was recognized",
    "인쇄를 취소했습니다": "Printing cancelled",
    "PDF 병합이 취소되었습니다.": "PDF merge cancelled.",
    "RapidOCR 유지": "Keeping RapidOCR",
    "OCR 엔진: RapidOCR": "OCR engine: RapidOCR",
    "OCR 엔진: AI 고품질(VL)": "OCR engine: High-quality AI (VL)",
    "Windows PDF 기본 앱: <b>%s</b>": "Windows default PDF app: <b>%s</b>",
    "확인할 수 없음 (설정에서 직접 확인하세요)":
        "Unavailable (check Windows Settings)",
    "Leaflet (이 프로그램)": "Leaflet (this application)",
    "Windows 앱": "Windows application",
    "Windows에서만 사용할 수 있는 설정입니다.": "This setting is available only on Windows.",
    "아래 옵션을 켜도 현재 기본 PDF 앱으로 열립니다. 먼저 Windows 기본 앱에서 Leaflet을 선택하세요.":
        "These options use the current default PDF app. Select Leaflet in Windows Default Apps first.",
    "브라우저의 내장 PDF 뷰어 대신 Windows 기본 앱을 사용합니다. 적용 후 브라우저를 완전히 종료했다 다시 실행하세요. Firefox는 웹페이지에 삽입된 PDF를 계속 브라우저에 표시할 수 있습니다.\n\n이 설정은 사용자별 브라우저 정책을 사용하므로 브라우저에 '조직에서 관리'가 표시될 수 있습니다.":
        "Use the Windows default app instead of the browser's built-in PDF viewer. Fully close and restart the browser after applying. Firefox may continue to display PDFs embedded in web pages.\n\nThese per-user browser policies may cause the browser to show a 'Managed by your organization' notice.",
    "설정 화면을 열지 못했습니다.\nWindows 설정 → 앱 → 기본 앱에서 직접 변경하세요.":
        "Could not open Settings.\nChange it manually under Windows Settings → Apps → Default apps.",
    "파일을 열 수 없습니다.": "The file could not be opened.",
    "저장할 수 없습니다.": "The file could not be saved.",
    "파일 없음": "File Not Found",
    "파일 위치 열기": "Open File Location",
    "탭 이동 실패": "Tab Transfer Failed",
    "PDF 추가 실패": "Could Not Add PDF",
    "병합 실패": "Merge Failed",
    "분리 실패": "Split Failed",
    "추출 실패": "Extraction Failed",
    "파일 덮어쓰기": "Replace Files",
    "현재 페이지 추출": "Extract Current Page",
    "병합할 PDF 선택 (여러 파일 선택 가능)": "Select PDFs to Merge (multiple selection allowed)",
    "병합할 PDF/Illustrator 파일 선택 (여러 파일 선택 가능)":
        "Select PDF/Illustrator Files to Merge (multiple selection allowed)",
    "분리한 PDF를 저장할 폴더": "Folder for Split PDFs",
    "저장되지 않은 변경": "Unsaved Changes",
    "저장하지 않은 주석이 있습니다. 저장할까요?": "You have unsaved changes. Save them?",
    "다른 이름으로 저장": "Save As",
    "(내용 없음)": "(No content)",
    "주석 삭제": "Delete Annotation",
    "여기에 메모 추가": "Add Note Here",
    "인쇄용 페이지를 준비하는 중입니다…": "Preparing pages for printing…",
    "선택한 프린터에서 인쇄를 시작할 수 없습니다.":
        "Could not start printing on the selected printer.",
    "프린터에서 다음 페이지를 만들 수 없습니다.":
        "The printer could not create the next page.",
    "편집 모드 — 글자를 클릭하면 수정, 빈 곳을 클릭하면 새 글자 추가 (원본 폰트 대신 기본 폰트로 써지므로 모양이 달라질 수 있습니다)":
        "Edit mode — click text to edit it or click an empty area to add text (replacement fonts may look different)",
    "이 페이지에는 텍스트 레이어가 없습니다 (스캔본) — OCR 필요":
        "This page has no text layer (scanned document) — OCR is required",
    "텍스트 레이어가 없는 문서입니다 (스캔본) — 복사/검색은 OCR 후 가능":
        "This document has no text layer (scanned document) — run OCR to copy or search",
    "이미 텍스트가 있음": "Text Layer Already Exists",
    "이 페이지에는 이미 텍스트 레이어가 있습니다.\nOCR을 실행하면 글자가 중복될 수 있습니다.\n\n그래도 진행할까요?":
        "This page already has a text layer.\nRunning OCR may duplicate text.\n\nContinue anyway?",
    "모든 페이지에 이미 텍스트 레이어가 있습니다.":
        "Every page already has a text layer.",
    "OCR 구성요소를 찾을 수 없습니다.\n\n설치가 손상되었을 수 있습니다. Leaflet을 다시 설치해 주세요.":
        "OCR components could not be found.\n\nThe installation may be damaged. Reinstall Leaflet.",
    "OCR 엔진이 설치되어 있지 않습니다.\n\n명령 프롬프트에서 설치 후 다시 실행하세요:\npip install rapidocr onnxruntime":
        "The OCR engine is not installed.\n\nInstall it from Command Prompt and restart:\npip install rapidocr onnxruntime",
    "AI 고품질(VL) OCR 인식 중...\n(첫 페이지는 모델 로드로 수십 초 걸릴 수 있습니다)":
        "Running high-quality AI (VL) OCR...\n(The first page may take tens of seconds while the model loads)",
    "OCR 인식 중... (첫 페이지는 인식 엔진 준비로 몇 초 걸릴 수 있습니다)":
        "Running OCR... (the first page may take a few seconds while the engine starts)",
    "OCR 중 오류가 발생했습니다.": "An error occurred during OCR.",
    "업데이트를 확인하고 있습니다…": "Checking for updates…",
    "GitHub에서 최신 버전을 확인하는 중입니다…": "Checking GitHub for the latest version…",
    "업데이트 확인": "Update Check",
    "업데이트 설치": "Install Update",
    "설치 프로그램을 실행합니다.\n저장하지 않은 문서를 확인한 뒤 Leaflet을 종료합니다. 계속할까요?":
        "The installer will start after Leaflet checks for unsaved documents and exits. Continue?",
    "불러오는 중...": "Loading...",
    "옮기는 중...": "Moving...",
    "Leaflet 문서": "Leaflet Document",
    "PDF 분리": "Split PDF",
    "분리할 페이지가 없습니다.": "There are no pages to split.",
    "페이지 범위를 입력하세요.": "Enter a page range.",
    "페이지 그룹이 비어 있습니다.": "A page group is empty.",
    "(빈 값)": "(empty value)",
    "페이지 순서는 모든 페이지를 정확히 한 번 포함해야 합니다.":
        "The page order must include every page exactly once.",
    "추출할 페이지가 없습니다.": "There are no pages to extract.",
    "옮길 페이지가 올바르지 않습니다.": "The pages to move are invalid.",
    "잘못된 작업 입력": "Invalid job input",
    "알 수 없는 상호작용 모드": "Unknown interaction mode",
    "설치됨": "Installed",
    "CPU — VL은 CPU에서 매우 느림 (GPU 권장)":
        "CPU — VL is very slow on a CPU (GPU recommended)",
    "NVIDIA GPU 없음(내장/AMD 또는 CPU)": "No NVIDIA GPU (integrated/AMD graphics or CPU)",
    "실행 런타임(torch, torchvision, transformers)":
        "runtime (torch, torchvision, transformers)",
    "모델(약 2GB, 첫 실행 시 다운로드)": "model (about 2 GB; downloaded on first use)",
    "PyTorch 미설치 — VL 실행 불가 (torch/transformers 필요)":
        "PyTorch is not installed — VL requires torch and transformers",
    "GitHub 릴리스 응답이 허용 크기를 초과했습니다.":
        "The GitHub release response exceeded the allowed size.",
    "GitHub 릴리스 응답 형식이 올바르지 않습니다.":
        "The GitHub release response format is invalid.",
    "GitHub 릴리스 주소를 신뢰할 수 없습니다.": "The GitHub release URL is not trusted.",
    "릴리스 설치 파일 정보가 안전하지 않습니다.": "The release installer information is unsafe.",
    "이 릴리스에는 Windows 설치 파일이 없습니다.": "This release has no Windows installer.",
    "설치 파일의 SHA-256 정보가 없어 자동 업데이트할 수 없습니다.":
        "Automatic update is unavailable because the installer has no SHA-256 information.",
    "설치 파일 SHA-256 검증에 실패했습니다.": "Installer SHA-256 verification failed.",
    "실행할 업데이트 설치 파일이 올바르지 않습니다.": "The update installer is invalid.",
    "업데이트 다운로드를 취소했습니다.": "Update download cancelled.",
    "VL 런타임이 설치되어 있지 않습니다.\n먼저 다음을 설치하세요:\n  pip install torch torchvision transformers huggingface_hub\n(GPU 사용 시 CUDA 지원 torch 빌드 필요)":
        "The VL runtime is not installed.\nInstall it first:\n  pip install torch torchvision transformers huggingface_hub\n(install a CUDA-enabled torch build for GPU acceleration)",
}


_PATTERNS = (
    (re.compile(r"^v(.+) — PDF 보기 · 주석 · OCR$"),
     lambda m: "v%s — PDF viewing · annotations · OCR" % m.group(1)),
    (re.compile(r"^(.+)\(으\)로 돌아가기$"),
     lambda m: "Back to %s" % m.group(1).lstrip("← ")),
    (re.compile(r"^(\d+)쪽$"), lambda m: "Page %s" % m.group(1)),
    (re.compile(r"^(\d+) / (\d+)쪽$"),
     lambda m: "Page %s of %s" % (m.group(1), m.group(2))),
    (re.compile(r"^(\d+)개 단어 선택 — Ctrl\+C로 복사$"),
     lambda m: "%s words selected — press Ctrl+C to copy" % m.group(1)),
    (re.compile(r"^복사됨 \((\d+)자\)$"),
     lambda m: "Copied (%s characters)" % m.group(1)),
    (re.compile(r"^저장됨: (.+)$"), lambda m: "Saved: %s" % m.group(1)),
    (re.compile(r"^추출됨: (.+)$"), lambda m: "Extracted: %s" % m.group(1)),
    (re.compile(r"^검색 결과 없음: (.+)$"),
     lambda m: "No results found: %s" % m.group(1)),
    (re.compile(r"^메모 모아보기 \((\d+)\)$"),
     lambda m: "Notes (%s)" % m.group(1)),
    (re.compile(r"^(\d+)페이지$"), lambda m: "Page %s" % m.group(1)),
    (re.compile(r"^(\d+)쪽 — (.+)$"),
     lambda m: "Page %s — %s" % (m.group(1), m.group(2))),
    (re.compile(r"^(\d+)건$"), lambda m: "%s results" % m.group(1)),
    (re.compile(r"^(\d+)쪽 크기를 읽을 수 없습니다\.$"),
     lambda m: "Could not read the size of page %s." % m.group(1)),
    (re.compile(r"^(\d+)쪽 인쇄 준비 중…$"),
     lambda m: "Preparing page %s…" % m.group(1)),
    (re.compile(r"^(\d+)쪽을 프린터로 보냈습니다$"),
     lambda m: "Sent %s pages to the printer" % m.group(1)),
    (re.compile(r"^선택한 (\d+)개 페이지를 삭제할까요\?\n\(Ctrl\+Z로 되돌릴 수 있습니다\.\)$"),
     lambda m: "Delete the %s selected pages?\n(You can undo with Ctrl+Z.)" % m.group(1)),
    (re.compile(r"^(\d+)쪽을 삭제할까요\? \(Ctrl\+Z로 되돌릴 수 있습니다\)$"),
     lambda m: "Delete page %s? (You can undo with Ctrl+Z.)" % m.group(1)),
    (re.compile(r"^(\d+)개 페이지 삭제$"), lambda m: "Deleted %s pages" % m.group(1)),
    (re.compile(r"^(\d+)개 페이지를 (\d+)페이지 위치로 이동$"),
     lambda m: "Moved %s pages to page %s" % (m.group(1), m.group(2))),
    (re.compile(r"^(\d+)쪽 → (\d+)쪽으로 이동$"),
     lambda m: "Moved page %s → %s" % (m.group(1), m.group(2))),
    (re.compile(r"^(\d+)개 파일에서 (\d+)페이지 추가$"),
     lambda m: "Added %s pages from %s files" % (m.group(2), m.group(1))),
    (re.compile(r"^(\d+)개 파일, (\d+)페이지 병합됨$"),
     lambda m: "Merged %s pages from %s files" % (m.group(2), m.group(1))),
    (re.compile(r"^(\d+)개 PDF로 분리됨: (.+)$"),
     lambda m: "Split into %s PDFs: %s" % (m.group(1), m.group(2))),
    (re.compile(r"^OCR 완료 — (\d+)개 텍스트 블록 인식 \(저장해야 파일에 반영됩니다\)$"),
     lambda m: "OCR completed — recognized %s text blocks (save to apply changes)" % m.group(1)),
    (re.compile(r"^현재 Leaflet (.+)가 최신 버전입니다\.$"),
     lambda m: "Leaflet %s is up to date." % m.group(1)),
    (re.compile(r"^Leaflet (.+) 업데이트가 있습니다\.\n자세히 볼까요\?$"),
     lambda m: "Leaflet %s is available.\nView details?" % m.group(1)),
    (re.compile(r"^Leaflet (.+) 업데이트가 있습니다\.$"),
     lambda m: "Leaflet %s is available." % m.group(1)),
    (re.compile(r"^Windows PDF 기본 앱: <b>(.+)</b>$"),
     lambda m: "Windows default PDF app: <b>%s</b>" % m.group(1)),
    (re.compile(r"^(.+) 설정을 변경했습니다\.\n브라우저를 완전히 종료한 뒤 다시 실행하세요\.$"),
     lambda m: "%s settings were updated.\nFully close and restart the browser." % m.group(1)),
    (re.compile(r"^파일이 이동되었거나 삭제되었습니다:\n(.+)$"),
     lambda m: "The file was moved or deleted:\n%s" % m.group(1)),
    (re.compile(r"^저장할 수 없습니다\.\n\n(.+)$", re.DOTALL),
     lambda m: "The file could not be saved.\n\n%s" % m.group(1)),
    (re.compile(r"^파일을 열 수 없습니다\.\n\n(.+)$", re.DOTALL),
     lambda m: "The file could not be opened.\n\n%s" % m.group(1)),
    (re.compile(r"^편집 중인 문서를 옮길 수 없습니다\.\n\n(.+)$", re.DOTALL),
     lambda m: "The edited document could not be moved.\n\n%s" % m.group(1)),
    (re.compile(r"^임시 문서를 읽을 수 없습니다\.\n\n(.+)$", re.DOTALL),
     lambda m: "The temporary document could not be read.\n\n%s" % m.group(1)),
    (re.compile(r"^탭 이동용 임시 저장에 실패했습니다: (.+)$", re.DOTALL),
     lambda m: "Could not create temporary data for tab transfer: %s" % m.group(1)),
    (re.compile(r"^PDF 열기 설정을 변경하지 못했습니다\.\n\n(.+)$", re.DOTALL),
     lambda m: "Could not change the PDF opening settings.\n\n%s" % m.group(1)),
    (re.compile(r"^현재 파일을 찾을 수 없습니다\.\n(.+)$", re.DOTALL),
     lambda m: "The current file could not be found.\n%s" % m.group(1)),
    (re.compile(r"^Windows 탐색기를 열 수 없습니다\.\n\n(.+)$", re.DOTALL),
     lambda m: "Could not open File Explorer.\n\n%s" % m.group(1)),
    (re.compile(r"^(.+) 파일의 비밀번호를 입력하세요\.$", re.DOTALL),
     lambda m: "Enter the password for %s." % m.group(1)),
    (re.compile(r"^메모 편집: (.+)$", re.DOTALL), lambda m: "Edit Note: %s" % m.group(1)),
    (re.compile(r"^같은 이름의 파일 (\d+)개가 있습니다\. 모두 덮어쓸까요\?$"),
     lambda m: "%s files have the same names. Replace all of them?" % m.group(1)),
    (re.compile(r"^PDF를 추가할 수 없습니다\.\n\n(.+)$", re.DOTALL),
     lambda m: "Could not add the PDF.\n\n%s" % m.group(1)),
    (re.compile(r"^PDF를 병합할 수 없습니다\.\n\n(.+)$", re.DOTALL),
     lambda m: "Could not merge the PDFs.\n\n%s" % m.group(1)),
    (re.compile(r"^(\d+)개 파일을 저장한 뒤 중단되었습니다\.\n\n(.+)$", re.DOTALL),
     lambda m: "Stopped after saving %s files.\n\n%s" % (m.group(1), m.group(2))),
    (re.compile(r"^OCR 중 오류가 발생했습니다\.\n\n(.+)$", re.DOTALL),
     lambda m: "An error occurred during OCR.\n\n%s" % m.group(1)),
    (re.compile(r"^OCR 프로세스를 시작할 수 없습니다: (.+)$", re.DOTALL),
     lambda m: "Could not start the OCR process: %s" % m.group(1)),
    (re.compile(r"^OCR 작업 프로세스가 시작하자마자 종료되었습니다\(종료 코드 (.+)\)\.$"),
     lambda m: "The OCR worker exited immediately (exit code %s)." % m.group(1)),
    (re.compile(r"^VL 모델 다운로드에 실패했습니다\.\n\n(.+)$", re.DOTALL),
     lambda m: "The VL model download failed.\n\n%s" % m.group(1)),
    (re.compile(r"^VL을 쓸 수 없습니다 — 빠진 것: (.+)$", re.DOTALL),
     lambda m: "VL is unavailable — missing: %s" % m.group(1)),
    (re.compile(r"^잘못된 작업 입력: (.+)$", re.DOTALL),
     lambda m: "Invalid job input: %s" % m.group(1)),
    (re.compile(r"^OCR 초기화 실패: (.+)$", re.DOTALL),
     lambda m: "OCR initialization failed: %s" % m.group(1)),
    (re.compile(r"^(\d+)번째 출력 범위가 비어 있습니다\.$"),
     lambda m: "Output range %s is empty." % m.group(1)),
    (re.compile(r"^올바르지 않은 페이지 범위: (.+)$"),
     lambda m: "Invalid page range: %s" % m.group(1)),
    (re.compile(r"^페이지 범위의 시작이 끝보다 큽니다: (.+)$"),
     lambda m: "The page range starts after it ends: %s" % m.group(1)),
    (re.compile(r"^페이지 범위는 1-(\d+) 사이여야 합니다: (.+)$"),
     lambda m: "Page numbers must be between 1 and %s: %s" % (m.group(1), m.group(2))),
    (re.compile(r"^알 수 없는 Fluent 아이콘: (.+)$"),
     lambda m: "Unknown Fluent icon: %s" % m.group(1)),
    (re.compile(r"^알 수 없는 상호작용 모드: (.+)$"),
     lambda m: "Unknown interaction mode: %s" % m.group(1)),
    (re.compile(r"^지원하지 않는 버전 형식입니다: (.+)$"),
     lambda m: "Unsupported version format: %s" % m.group(1)),
    (re.compile(r"^GitHub 릴리스 정보를 확인하지 못했습니다: (.+)$", re.DOTALL),
     lambda m: "Could not check GitHub release information: %s" % m.group(1)),
    (re.compile(r"^GitHub 릴리스 응답을 읽지 못했습니다: (.+)$", re.DOTALL),
     lambda m: "Could not read the GitHub release response: %s" % m.group(1)),
    (re.compile(r"^업데이트 다운로드에 실패했습니다: (.+)$", re.DOTALL),
     lambda m: "Update download failed: %s" % m.group(1)),
    (re.compile(r"^업데이트 설치 파일을 실행하지 못했습니다: (.+)$", re.DOTALL),
     lambda m: "Could not launch the update installer: %s" % m.group(1)),
    (re.compile(r"^설치 파일 크기가 다릅니다: (.+) / (.+) bytes$"),
     lambda m: "Installer size mismatch: %s / %s bytes" % (m.group(1), m.group(2))),
    (re.compile(r"^NVIDIA GPU\((.+), (.+)GB\) \+ RAM (.+)GB — VL에 적합합니다\.$"),
     lambda m: "NVIDIA GPU (%s, %s GB) + RAM %s GB — suitable for VL." % m.groups()),
    (re.compile(r"^GPU\((.+), (.+)GB\)가 있으나 여유가 크지 않습니다 — 동작은 하지만 느리거나 메모리 부족이 날 수 있습니다\.$"),
     lambda m: "GPU (%s, %s GB) has limited headroom — VL may be slow or run out of memory." % (m.group(1), m.group(2))),
    (re.compile(r"^(.+), RAM (.+)GB — GPU 가속을 못 써 VL이 매우 느립니다\(페이지당 수십 초~분\)\. 켜놓고 기다리는 배경 작업이면 쓸 수 있지만, 평소엔 RapidOCR을 권합니다\.$"),
     lambda m: "%s, RAM %s GB — without GPU acceleration VL is very slow (tens of seconds to minutes per page). RapidOCR is recommended for normal use." % (tr(m.group(1)), m.group(2))),
    (re.compile(r"^지원하지 않는 브라우저입니다: (.+)$"),
     lambda m: "Unsupported browser: %s" % m.group(1)),
)


def language():
    return _language


def set_language(code):
    """Select a shipped UI language and return its normalized code."""
    global _language
    normalized = (code or DEFAULT_LANGUAGE).lower().split("-", 1)[0]
    if normalized not in SUPPORTED_LANGUAGES:
        normalized = DEFAULT_LANGUAGE
    _language = normalized
    return _language


def tr(text):
    """Translate a complete UI string while leaving document data untouched."""
    if not isinstance(text, str) or _language != "en" or not text:
        return text
    translated = EN.get(text)
    if translated is not None:
        return translated
    for pattern, replacement in _PATTERNS:
        match = pattern.match(text)
        if match:
            return replacement(match)
    return text


def localize(english, korean):
    """Return language-specific prose that is too long for the message map."""
    return korean if _language == "ko" else english


def localize_qt_standard_button(text):
    """Localize a button label created internally by Qt or Windows."""
    if _language == "ko":
        return QT_STANDARD_BUTTONS_KO.get(text, text)
    return text


def install(app, language_code=None):
    """Install automatic translation for widgets created by Qt and the app."""
    if language_code is None:
        from . import settings
        language_code = os.environ.get("SPDF_UI_LANGUAGE") or settings.ui_language()
    set_language(language_code)
    if getattr(app, "_spdf_i18n_filter", None) is not None:
        return app._spdf_i18n_filter

    import weakref
    from PyQt5 import sip
    from PyQt5.QtCore import QEvent, QObject, QTimer
    from PyQt5.QtWidgets import QComboBox, QListWidget, QTabWidget, QLineEdit

    def translate_source_text(text):
        translated = tr(text)
        if translated != text:
            return translated
        return localize_qt_standard_button(text)

    def translate_object(obj):
        if sip.isdeleted(obj):
            return
        for getter, setter in (
                ("text", "setText"), ("title", "setTitle"),
                ("windowTitle", "setWindowTitle"),
                ("toolTip", "setToolTip"), ("statusTip", "setStatusTip"),
                ("placeholderText", "setPlaceholderText")):
            # Editable values (including spin-box editors) are user/model
            # state, not translatable labels. Never replay their initial text.
            if getter == "text" and isinstance(obj, QLineEdit):
                continue
            get = getattr(obj, getter, None)
            put = getattr(obj, setter, None)
            if callable(get) and callable(put):
                try:
                    old = get()
                    property_name = "_spdf_i18n_source_" + getter
                    source = obj.property(property_name) or old
                    new = translate_source_text(source)
                    if new != old:
                        put(new)
                    if obj.property(property_name) is None:
                        obj.setProperty(property_name, source)
                except (RuntimeError, TypeError):
                    pass
        if isinstance(obj, QComboBox):
            for index in range(obj.count()):
                old = obj.itemText(index)
                new = tr(old)
                if new != old:
                    obj.setItemText(index, new)
        if isinstance(obj, QListWidget):
            for index in range(obj.count()):
                item = obj.item(index)
                old = item.text()
                new = tr(old)
                if new != old:
                    item.setText(new)
        if isinstance(obj, QTabWidget):
            for index in range(obj.count()):
                old = obj.tabText(index)
                new = tr(old)
                if new != old:
                    obj.setTabText(index, new)

    def translate_tree(root, visited=None):
        try:
            children = root.findChildren(QObject)
        except RuntimeError:
            return
        for child in [root] + children:
            if visited is not None:
                key = (child, language())
                if key in visited:
                    continue
                visited.add(key)
            translate_object(child)

    class TranslationFilter(QObject):
        def __init__(self, parent):
            super().__init__(parent)
            self.pending = {}
            self.flush_scheduled = False

        def schedule(self, root):
            key = id(root)
            self.pending[key] = (weakref.ref(root), language())
            if self.flush_scheduled:
                return
            self.flush_scheduled = True
            QTimer.singleShot(0, self.flush_pending)

        def flush_pending(self):
            self.flush_scheduled = False
            visited = set()
            for key in tuple(self.pending):
                self.flush(key, visited)

        def flush(self, key, visited=None):
            pending = self.pending.pop(key, None)
            if pending is None:
                return
            reference, scheduled_language = pending
            root = reference()
            if root is not None and not sip.isdeleted(root):
                current_language = language()
                try:
                    set_language(scheduled_language)
                    translate_tree(root, visited)
                finally:
                    set_language(current_language)

        def eventFilter(self, watched, event):
            # Qt can emit Polish/ChildAdded from inside a widget constructor.
            # Calling getters on that half-built C++ object can access invalid
            # memory (not a catchable Python exception). Defer every traversal;
            # for ChildAdded inspect the completed parent, not event.child().
            if event.type() in (QEvent.Show, QEvent.Polish, QEvent.ChildAdded):
                self.schedule(watched)
            return False

    event_filter = TranslationFilter(app)
    app.installEventFilter(event_filter)
    app._spdf_i18n_filter = event_filter
    app._spdf_translate_tree = translate_tree
    return event_filter


def translate_tree(root):
    """Translate a completed widget tree immediately."""
    from PyQt5.QtWidgets import QApplication
    application = QApplication.instance()
    callback = getattr(application, "_spdf_translate_tree", None)
    if callback:
        callback(root)
