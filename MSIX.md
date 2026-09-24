# MSIX preparation / MSIX 준비

Build an **unsigned x64 package** locally, or run the **Prepare unsigned MSIX**
workflow with your identity name, publisher subject and publisher display name.
The workflow uploads a build artifact only; it does not publish a release or
install/trust a certificate. Do not distribute that artifact as a signed installer.

로컬 또는 **Prepare unsigned MSIX** 수동 워크플로에서 서명 전 x64 패키지를
만들 수 있습니다. 게시자 정보는 직접 입력합니다. 자동 릴리스·인증서 설치는
하지 않으며, 일반 릴리스에는 기존 EXE 설치 파일을 제공합니다.

1. Install Python build dependencies and the Windows SDK (MakeAppx and SignTool).
2. Run `build_exe.bat` first. Both GUI and OCR worker must match the app version.
3. Run the following with **your** identity and certificate subject:

```powershell
python build_msix.py --identity-name "YourCompany.Leaflet" --publisher "CN=YourCompany" --publisher-display-name "YourCompany"
```

Output: `Output/Leaflet_VERSION_x64_unsigned.msix`. Existing packages are never
overwritten. Staging is retained in a unique `Output/msix-*` directory for review.
Windows 10 1809 or later, x64 only. The package includes the native renderer,
OCR worker and dependency notices. PDF/AI Open With entries come from its manifest;
default associations are still chosen by the user. MSIX uses the Windows package
identity and disables the EXE updater. Store submission and install/upgrade/
uninstall verification are separate steps, not claimed by package creation.

출력 파일은 `Output/Leaflet_VERSION_x64_unsigned.msix`입니다. 기존 파일은 덮어쓰지
않습니다. MSIX에서는 EXE 자동 업데이트를 끄고 패키지 경로로 업데이트합니다.
새 인증서 신뢰 설정, 스토어 제출, 실제 설치·업그레이드·제거 검증은 별도입니다.

## Privacy policy / 개인정보 처리방침

The bilingual policy is [PRIVACY.md](PRIVACY.md). After publishing this file to
the public main branch, verify that the following URL opens without signing in
and use it in Partner Center's privacy-policy URL field:

https://github.com/loselessss/Leaflet/blob/main/PRIVACY.md

한국어·영어 방침은 [PRIVACY.md](PRIVACY.md)에 있습니다. 공개 main 브랜치에
게시한 뒤 위 주소가 로그인 없이 열리는지 확인하고 Partner Center의 개인정보
처리방침 URL에 입력하세요. Store 제출 전 앱 안에서도 방침에 접근할 수 있도록
연결하고, 실제 게시자 정보와 배포 기능이 방침 내용과 일치하는지 확인하세요.

## Signing and distribution / 서명·배포

- For Microsoft Store, use the exact Identity Name and Publisher from Partner
  Center; Store signing is performed on submission. The Store version's fourth
  component remains zero (`x.y.z.0`).
- For direct distribution, sign with your code-signing certificate. Its subject
  must exactly match the manifest Publisher. Keep certificate keys/passwords
  outside the repository. Use your signing service or a certificate in the
  Windows certificate store, for example:

```powershell
signtool sign /sha1 YOUR_CERTIFICATE_THUMBPRINT /fd SHA256 /tr YOUR_HTTPS_TIMESTAMP_URL /td SHA256 Output\Leaflet_VERSION_x64_unsigned.msix
signtool verify /pa /v Output\Leaflet_VERSION_x64_unsigned.msix
```

After successful signing/verification, rename the signed copy to omit `unsigned`.
Test install, file opening, reader/editor handoff, OCR, GPU workers, upgrade and
uninstall before enabling release uploads. Keep version-matched source assets
in the same release as any MSIX download, as for EXE releases (see [SOURCE_CODE.md](SOURCE_CODE.md)).
Unsigned workflow artifacts expire and are not a public corresponding-source host.

MSIX도 EXE와 같은 소스 제공 의무가 적용됩니다. 같은 릴리스에 해당 버전의
공개 소스 파일을 첨부하세요. 서명된 패키지의 설치·업그레이드 검증이 끝나기 전에는
일반 릴리스 첨부 대상으로 자동 추가하지 않습니다.

- [Microsoft: package manifest](https://learn.microsoft.com/en-us/windows/msix/desktop/desktop-to-uwp-manual-conversion)
- [Microsoft: MakeAppx](https://learn.microsoft.com/en-us/windows/msix/package/create-app-package-with-makeappx-tool)
- [Microsoft: signing](https://learn.microsoft.com/en-us/windows/msix/package/signing-package-overview)
