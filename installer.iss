; sPDF 설치 스크립트 (Inno Setup 6)
; 빌드: build_installer.bat  (먼저 build_exe.bat로 dist\Leaflet 생성)
;
; 버전은 bandwagon 방식대로 수동 동기화 — pdfeditor\meta.py의 APP_VERSION과
; 아래 MyAppVersion을 함께 맞출 것(자동 동기화 안 됨).

#define MyAppName "Leaflet"
#define MyAppVersion "1.33.8"
#define MyAppPublisher "Leaflet"
#define MyAppExeName "Leaflet.exe"
#define MyProgId "sPDF.Document"
#define MyAppUserModelId "sPDF.Desktop"

[Setup]
AppId={{7C2F9A4E-3B71-4E0C-9D2A-5F6B1A8C0E11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputBaseFilename=Leaflet_Setup_{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; 관리자면 시스템 전체(HKLM), 아니면 현재 사용자(HKCU)에 설치·등록
PrivilegesRequiredOverridesAllowed=dialog
SetupIconFile=assets\spdf.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesInstallIn64BitMode=x64compatible
ShowLanguageDialog=yes
LicenseFile=LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[CustomMessages]
english.ReaderShortcut=Leaflet Reader
korean.ReaderShortcut=Leaflet 리더
english.EditorShortcut=Leaflet Editor
korean.EditorShortcut=Leaflet 편집기
english.ReaderDesktopShortcut=Create a Leaflet Reader desktop shortcut
korean.ReaderDesktopShortcut=Leaflet 리더 바탕 화면 바로 가기 만들기
english.EditorDesktopShortcut=Create a Leaflet Editor desktop shortcut
korean.EditorDesktopShortcut=Leaflet 편집기 바탕 화면 바로 가기 만들기
english.AdditionalShortcuts=Additional shortcuts:
korean.AdditionalShortcuts=추가 바로 가기:

[Tasks]
Name: "desktopreader"; Description: "{cm:ReaderDesktopShortcut}"; GroupDescription: "{cm:AdditionalShortcuts}"; Flags: unchecked
Name: "desktopeditor"; Description: "{cm:EditorDesktopShortcut}"; GroupDescription: "{cm:AdditionalShortcuts}"; Flags: unchecked
; PDF/Illustrator 연결은 '연결 프로그램 후보'로만 등록(기본값을 강제로 뺏지 않음).
; 사용자가 나중에 Windows '기본 앱'에서 sPDF를 직접 고를 수 있다.
Name: "associate"; Description: "Add Leaflet to the Open with list for PDF and Illustrator files"; GroupDescription: "File associations:"; Languages: english
Name: "associate"; Description: "PDF 및 Illustrator 파일의 연결 프로그램 목록에 Leaflet 추가"; GroupDescription: "파일 연결:"; Languages: korean
; Windows 8 이상에서는 설치 프로그램이 기본 앱을 직접 바꿀 수 없다.
; 선택 시 설치 완료 후 Windows 기본 앱 설정을 열어 사용자가 확정한다.
Name: "associate\defaultpdf"; Description: "Choose Leaflet as the default PDF app after installation (opens Windows Settings)"; GroupDescription: "File associations:"; Flags: unchecked; Languages: english
Name: "associate\defaultpdf"; Description: "설치 후 Leaflet을 기본 PDF 앱으로 선택(Windows 설정 열기)"; GroupDescription: "파일 연결:"; Flags: unchecked; Languages: korean

[Files]
Source: "dist\Leaflet\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Keep existing pinned shortcuts and external launchers working with the new build.
Source: "dist\Leaflet\Leaflet.exe"; DestDir: "{app}"; DestName: "sPDF.exe"; Flags: ignoreversion
; OCR 워커는 Qt DLL과 격리하기 위해 별도 폴더에 (paths.ocr_command 참고)
Source: "dist\Leaflet-ocr\*"; DestDir: "{app}\ocr"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "assets\spdf_doc.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
; Keep legal documents accessible without starting sPDF.
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "SOURCE_CODE.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "build\legal\*"; DestDir: "{app}\third-party"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{cm:ReaderShortcut}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--workspace reader"; AppUserModelID: "{#MyAppUserModelId}"
Name: "{group}\{cm:EditorShortcut}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--workspace editor"; AppUserModelID: "{#MyAppUserModelId}"
Name: "{autodesktop}\{cm:ReaderShortcut}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--workspace reader"; AppUserModelID: "{#MyAppUserModelId}"; Tasks: desktopreader
Name: "{autodesktop}\{cm:EditorShortcut}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--workspace editor"; AppUserModelID: "{#MyAppUserModelId}"; Tasks: desktopeditor

[InstallDelete]
Type: files; Name: "{app}\ocr\spdf-ocr.exe"
; 업데이트 및 설치 언어 변경 시 이전 바로가기를 정리한 뒤 선택 항목만 다시 만든다.
Type: files; Name: "{group}\Leaflet Reader.lnk"
Type: files; Name: "{group}\Leaflet Editor.lnk"
Type: files; Name: "{group}\Leaflet 리더.lnk"
Type: files; Name: "{group}\Leaflet 편집기.lnk"
Type: files; Name: "{autodesktop}\Leaflet Reader.lnk"
Type: files; Name: "{autodesktop}\Leaflet Editor.lnk"
Type: files; Name: "{autodesktop}\Leaflet 리더.lnk"
Type: files; Name: "{autodesktop}\Leaflet 편집기.lnk"
Type: files; Name: "{group}\{#MyAppName}.lnk"
Type: files; Name: "{autodesktop}\{#MyAppName}.lnk"
Type: files; Name: "{group}\sPDF Reader.lnk"
Type: files; Name: "{group}\sPDF Editor.lnk"
Type: files; Name: "{group}\sPDF 리더.lnk"
Type: files; Name: "{group}\sPDF 편집기.lnk"
Type: files; Name: "{autodesktop}\sPDF Reader.lnk"
Type: files; Name: "{autodesktop}\sPDF Editor.lnk"
Type: files; Name: "{autodesktop}\sPDF 리더.lnk"
Type: files; Name: "{autodesktop}\sPDF 편집기.lnk"

[Registry]
; Keep the existing file association identity, but show only the new app name.
Root: HKA; Subkey: "Software\RegisteredApplications"; ValueType: none; ValueName: "sPDF"; Flags: deletevalue; Tasks: associate
; 설치 시 고른 언어를 앱의 최초 UI 언어 기본값으로 전달한다.
Root: HKA; Subkey: "Software\sPDF"; ValueType: string; ValueName: "UILanguage"; ValueData: "{code:GetUiLanguage}"; Flags: uninsdeletevalue
; --- ProgId: sPDF로 PDF를 열었을 때의 아이콘/실행 명령 ---
Root: HKA; Subkey: "Software\Classes\{#MyProgId}"; ValueType: string; ValueData: "PDF"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\{#MyProgId}\DefaultIcon"; ValueType: string; ValueData: "{app}\assets\spdf_doc.ico"
Root: HKA; Subkey: "Software\Classes\{#MyProgId}\shell\open\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""

; --- .pdf/.ai의 '연결 프로그램' 후보 목록에 추가(기본값은 안 건드림) ---
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: none; ValueName: "{#MyProgId}"; Flags: uninsdeletevalue; Tasks: associate
Root: HKA; Subkey: "Software\Classes\.ai\OpenWithProgids"; ValueType: none; ValueName: "{#MyProgId}"; Flags: uninsdeletevalue; Tasks: associate

; --- Windows '기본 앱' 목록에 sPDF가 나타나도록 Capabilities 등록 ---
Root: HKA; Subkey: "Software\sPDF\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#MyAppName}"; Flags: uninsdeletekey; Tasks: associate
Root: HKA; Subkey: "Software\sPDF\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Lightweight PDF viewer, annotation, OCR, and editing tool"; Tasks: associate
Root: HKA; Subkey: "Software\sPDF\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pdf"; ValueData: "{#MyProgId}"; Tasks: associate
Root: HKA; Subkey: "Software\sPDF\Capabilities\FileAssociations"; ValueType: string; ValueName: ".ai"; ValueData: "{#MyProgId}"; Tasks: associate
Root: HKA; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: "Software\sPDF\Capabilities"; Flags: uninsdeletevalue; Tasks: associate

[Run]
Filename: "ms-settings:defaultapps"; Description: "Choose Leaflet as the default PDF app"; Flags: shellexec nowait skipifsilent runasoriginaluser; Tasks: associate\defaultpdf; Languages: english
Filename: "ms-settings:defaultapps"; Description: "Leaflet을 기본 PDF 앱으로 선택"; Flags: shellexec nowait skipifsilent runasoriginaluser; Tasks: associate\defaultpdf; Languages: korean
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Leaflet"; Flags: nowait postinstall skipifsilent; Languages: english
Filename: "{app}\{#MyAppExeName}"; Description: "Leaflet 실행"; Flags: nowait postinstall skipifsilent; Languages: korean

[Code]
function GetUiLanguage(Param: String): String;
begin
  if ActiveLanguage = 'korean' then
    Result := 'ko'
  else
    Result := 'en';
end;
