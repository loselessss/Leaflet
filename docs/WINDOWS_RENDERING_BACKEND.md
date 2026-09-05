# Windows 렌더링 백엔드 설계

작성일: 2026-09-01 · 구현 현황 갱신: 2026-09-04

상태: Direct2D 타일 합성 및 제한형 PDF 벡터·글자 GPU 래스터화 적용

### 현재 단계: 1.30.0 / ABI v19

- 1.26~1.27의 소프트/이미지 마스크, 사용자 선 스타일, 윤곽선 글자와 stroked clip geometry에 이어 격리 그룹의 **11개 separable 혼합 모드**를 실제 표시 경로에 연결했다. Multiply, Screen, Overlay, Darken, Lighten, Color Dodge, Color Burn, Hard Light, Soft Light, Difference, Exclusion이 대상이다.
- 1.28.1은 Hue/Saturation/Color/Luminosity도 Direct2D Blend effect에 연결하여 Normal 외 표준 PDF 혼합 모드 15개를 지원한다. PDF의 SetLum/SetSat·색 범위 보정과 같은 RGB 성분 혼합을 사용하며, 일반 HSL 색상 변환으로 대체하지 않는다. 구형 DLL이 확장된 모드 번호를 받지 않도록 ABI v11로 구분한다.
- 혼합 장면은 일반 그룹까지 명시적인 GPU 중간 bitmap에 그린다. 그룹을 닫을 때 소스 불투명도를 적용하고 배경 snapshot과 Direct2D Blend effect로 합성한 결과를 이전 target에 복사한다. 배경을 두 번 source-over하지 않으며, 페이지 좌표·DPI 변환은 그대로 유지한다. [Microsoft Blend effect의 입력·알파 합성 정의](https://learn.microsoft.com/en-us/windows/win32/direct2d/blend)를 따른다.
- 임시 bitmap은 PDF 전체 확대 크기가 아닌 viewport 크기다. 혼합 그룹은 2개, 명시적 클리핑은 3개, 마스크는 생성·변환·적용에 필요한 최대 4개를 중첩 깊이별로 예약하여 표면별 256 MiB 상한을 적용한다. 이는 명시적 bitmap 예약 한도이며 색상표·드라이버·effect 내부 메모리까지 포함한 총 VRAM 한도는 아니다. 그룹 종료·실패·표면 해제 시 회수한다. 현재는 프레임별 임시 버퍼이며 풀 재사용·부분 갱신은 후속 최적화다.
- 1.28.2는 혼합 장면의 geometry/text/stroked clip을 ABI v12의 명시적 clip capture로 처리한다. 기존 배경을 복사한 target에서 자식 혼합을 처리하고, 종료 시 `result * coverage + backdrop * (1 - coverage)`를 GPU 효과로 계산해 SOURCE_COPY한다. 이로써 클리핑 밖의 배경과 반투명 알파를 보존하며 경계 coverage를 해당 clip당 한 번 적용한다. coverage는 일반 Direct2D clip layer와 같은 래스터화 경로를 사용한다. [Microsoft Composite effect 입력 순서와 연산 정의](https://learn.microsoft.com/en-us/windows/win32/direct2d/composite)를 따른다.
- 혼합 또는 마스크 장면의 모든 PDF 투명도 그룹은 여전히 격리되어야 한다. 1.28.3에서는 마스크 생성과 적용을 명시적 bitmap capture로 나눠, 두 범위 안의 격리 혼합·geometry clip 및 중첩 마스크를 GPU로 처리한다. mask-end는 색상/알파를 coverage로 바꾼 뒤 배경을 복사한 content target으로 전환하고, clip-pop에서 coverage를 적용한다. 범위가 교차하는 잘못된 스택은 사전 검증으로 거부한다.
- 밝기 마스크는 MuPDF의 `FZ_RI_IN_SOFTMASK` 색 변환으로 만든 65³ RGB→Gray LUT를 [Direct2D LookupTable3D](https://learn.microsoft.com/en-us/windows/win32/direct2d/3d-lookup-table-effect)에 올린 뒤 알파로 변환한다. 일반 RGB→Gray 변환과 마스크 전용 변환은 다르다. LUT는 약 1.05 MiB로 필요할 때 한 번 생성·업로드하고 기본 ICC 변환이 바뀌면 갱신한다. 픽셀별 변환과 래스터화는 GPU가 수행한다. Windows 10 이상의 해당 GPU 효과를 사용할 수 없으면 기존 안전 경로가 적용된다. 회색조(+alpha) 이미지도 RGBA로 정규화하고 PDF의 Interpolate 설정을 전달한다.
- 1.28.4는 반복 이미지 XObject 디코딩 캐시, 확대 단계별 이미지 장면 품질 갱신, linear/radial shading의 Direct2D vector band 변환, 일부 비격리/knockout 그룹의 안전한 flatten/격리 변환을 추가했다. ABI v15는 변환된 knockout 그룹을 네이티브 composite capture에 전달한다.
- 1.28.5는 linear shading과 시작 반지름이 0인 radial shading을 Direct2D gradient primitive로 승격한다. 기존 band 표현보다 draw call을 크게 줄이고, 지원하지 못하는 radial 형태는 기존 band 또는 CPU 대체 경로를 유지한다. ABI v16은 linear/radial gradient fill API와 gradient stop 배열을 추가한다.
- 1.28.6은 MuPDF display-list 글자 항목의 glyph id가 비어 있어도 같은 내장/원본 폰트의 cmap으로 유니코드 문자를 glyph id에 다시 매핑할 수 있으면 그 원본 glyph outline을 사용한다. 원본 폰트에서 glyph id 또는 outline을 얻지 못하는 보이는 글자는 계속 CPU 경로로 둔다.
- Direct2D device context는 프레임 시작·렌더 타깃 재생성 시 `D2D1_ANTIALIAS_MODE_PER_PRIMITIVE`와 `D2D1_TEXT_ANTIALIAS_MODE_GRAYSCALE`을 명시한다. 기존 PDF 글자는 glyph outline geometry로 처리하므로 화면 기준 텍스트 품질도 geometry AA 경로에서 검증한다.
- GPU 장면 추출은 자동 모드에서 먼저 경로를 걷거나 이미지를 디코딩하지 않는 가벼운 전체 명령 검사를 수행한다. 복잡도 점수가 5,000 이상이면 동기 추출을 시작하지 않고 CPU 화면을 즉시 유지하며, 그보다 단순한 쪽은 페이지당 1초 예산을 적용한다. GPU 강제 모드에서는 10초 예산을 적용한다. 시간 예산을 넘긴 페이지는 기존 CPU 타일 경로를 유지하며, 이미 준비된 낮은 확대 단계 GPU 장면은 고해상도 갱신이 시간 초과되어도 버리지 않는다.
- 1.29.0은 독립 미지원 투명도 그룹을 MuPDF CPU island 이미지로 래스터화해 GPU 장면에 다시 합성하는 첫 경로를 추가했다. 작은 국소 knockout/비격리 그룹은 `cpu-island-approximate`로 표시하고 GPU 강제 모드에서 GPU 표시를 유지할 수 있게 하되, 선택 좌표·페이지 박스·확대 배율 같은 수치는 PDF 모델과 리더 상태를 기준으로 유지한다.
- 1.29.1은 soft-mask transfer function을 256샘플 알파 LUT로 만들어 ABI v17의 Direct2D TableTransfer effect에 전달한다. 단순 색상 벡터 타일 패턴은 패턴 셀을 기록한 뒤 page fill clip 안에서 반복 복제해 Direct2D scene item으로 펼친다. 근사 CPU island는 작은 겹침 도형을 같은 제한 영역 island에 흡수해 GPU 강제 렌더링을 유지하면서 중복 벡터 경계선을 줄인다. 같은 색의 연속 글자 glyph outline은 `text-outline-merge`로 결합 path에 압축하고, 같은 색의 연속 fill path는 `baked-gradient-band-merge`로 압축한다. linear/radial gradient primitive를 감싼 동일 영역 clip triplet은 `gradient-clip-merge`로 gradient 항목에 흡수한다. `SPDF_GPU_AGGRESSIVE_BAND_MERGE=1`은 기본값이 꺼진 실험 설정이며, 유사 색상 band를 평균 색상으로 병합하고 별도 장면 캐시 키와 `aggressive-band-merge` feature로 기본 정확 색상 경로와 구분한다. 중첩 타일 패턴, 패턴 내부 마스크와 기타 미지원 명령은 아직 남아 있다. shading 생성과 이미지 디코딩도 현재 CPU 작업이다.
- 1.29.2의 interactive zoom은 Ctrl/Alt+휠 목표 배율까지 120 ms ease-out으로 현재 GPU 장면의 페이지 행렬을 갱신한다. 각 중간 프레임의 실제 배율을 UI와 좌표 변환에 그대로 사용하고 마지막 프레임은 요청 배율과 정확히 일치한다. 확대 입력이 안정된 뒤에만 더 높은 이미지 품질이 필요한 장면을 보이는 쪽부터 한 쪽씩 갱신하며, paint 경로에서는 장면을 재추출하지 않는다. MuPDF 문서 객체는 GUI 스레드에 유지하고 쪽 사이에서 이벤트 루프에 제어를 돌려주므로, 별도 스레드에서 같은 문서를 공유하지 않는다.
- 1.29.3은 페이지 표시 목록과 네이티브 자원 참조를 ABI v18 retained scene으로 복사해, 프레임마다 Python이 개별 항목을 호출하지 않고 페이지 행렬과 함께 장면을 한 번 호출한다. bitmap 기반 mask·blend capture가 없는 장면은 Direct2D command list로 한 번 기록해 이후 프레임에서 그대로 재사용한다. mask/composite 장면은 target bitmap 복사와 effect 적용이 필요하므로 retained 명령을 네이티브에서 재생한다.
- 1.29.4는 투명 배경 이미지 마스크의 범위를 이미지 변환에서 계산하고, soft-mask와 geometry clip의 중간 bitmap을 현재 target과 교차하는 실제 device-space bounds로 제한한다. 잘라낸 원점은 중첩 캡처별로 행렬에 반영하고 합성 시 원래 위치로 복원한다.
- 1.29.5는 혼합·마스크 target 전환을 가로지르는 geometry clip만 bitmap-backed clip group으로 만들고, 그 밖의 clip은 일반 Direct2D layer로 유지한다. retained scene 생성 시 linear/radial gradient brush와 stop collection을 한 번 만들고 반복 프레임에서 재사용한다. 자동·GPU 강제 모드의 단순 사각형 경로는 ABI v19의 axis-aligned clip으로 기록하며, CPU 대체 경로와 페이지 좌표·변환은 변경하지 않는다. 자동 모드에서 복잡하다고 판정된 쪽은 현재 쪽만 복사한 메모리 snapshot을 별도 작업 프로세스에서 최대 10초 동안 장면으로 변환한다. GUI의 원본 MuPDF 문서 객체를 공유하지 않으며, 완료 결과는 문서 변경 세대와 이미지 배율을 검증한 뒤 메모리 캐시에 설치하고 CPU 화면을 GPU 장면으로 교체한다. 처음 숨겨진 상태로 배치된 탭은 화면에 나타나는 시점에 미뤄진 작업을 예약한다. 다시 숨김·문서 교체·닫기에서는 작업과 임시 snapshot을 정리한다.
- 실제 Direct2D 출력 픽셀을 읽는 명시적 진단 API를 추가했다. 11개 모드의 반투명 배경·소스·그룹 opacity 결과를 수식과 비교하고, 실제 PDF의 GPU 장면을 CPU 렌더의 내부 픽셀과 비교한다. 픽셀 readback은 테스트용 호출에만 사용하며 일반 repaint 경로에는 넣지 않는다. 임의 포스터·색 관리·모든 중첩 조합의 품질이나 속도 우위를 이 테스트만으로 보장하지 않는다.
- 추가한 성분 혼합 4개는 12가지 배경/소스 색 쌍(6개 색조 영역, 회색, 흑백)과 4가지 알파/불투명도 조건의 192개 조합을 독립 SetLum/SetSat 수식과 비교한다. 실제 PDF 15개 모드를 일반 장면과 중첩/even-odd 클리핑 장면에서 CPU 내부 픽셀과 비교한다. 반투명 배경·소수점 clip 경계·중첩·회전·96/120 DPI를 별도로 비교하고, 잘못된 capture 종료와 미완료 프레임 정리도 검증한다. 알파/밝기 마스크 내부·외부 혼합, RGB 원색·회색 마스크, 이미지 마스크를 CPU 출력과 비교하며, 중첩 적용·마스크 영역 밖 보존·오류 후 프레임 재시작도 확인한다.

### 1.25.0 구현 이력

구현 현황: sPDF 1.25.0에서 ABI v6 DLL을 독립 실행 리더·편집기의 실제 Qt HWND에 연결한다. Intel Iris Xe의 하드웨어 D3D feature level 11.1에서 D3D11/DXGI 장치, Direct2D device context, DirectWrite factory와 flip-model swap chain을 검증했다. PyMuPDF의 512px BGRA 타일, 페이지 회전 행렬, 검색·선택·편집 테두리를 Direct2D로 합성한다. 지원되는 페이지는 MuPDF가 CPU에서 해석한 선·사각형·베지어와 원래 글꼴 glyph 윤곽을 immutable Direct2D geometry 및 realization으로 만들어 상세 CPU 타일 없이 GPU 래스터화한다. CPU에서 디코딩한 배치 이미지와 색상 스텐실 마스크는 원래 PDF 행렬로 Direct2D가 확대·합성하며, 중첩된 벡터·텍스트 클리핑은 표시 순서대로 Direct2D layer에 적용한다. 모든 shading 유형은 제한된 고품질 이미지로 변환해 합성하고 일반 격리 투명도 그룹은 opacity layer로 처리한다. 숨김·닫기 때 네이티브 캐시를 해제하며 실패하면 같은 문서와 좌표를 유지한 채 Qt 표시로 전환한다.

## 결정

sPDF 독립 실행 리더와 편집기의 Windows 우선 화면 백엔드는 다음 조합을 목표로 한다.

- Direct3D 11 장치와 DXGI flip-model swap chain으로 창 표면과 프레임 표시를 관리한다.
- Direct2D device context로 페이지 이미지, 편집 개체, 선택 표시와 안내선을 합성한다.
- DirectWrite로 sPDF가 새로 만드는 조판 텍스트의 측정·glyph 배치·화면 표시를 처리한다.
- 리더와 편집기는 같은 백엔드 코드를 사용하되 장치·swap chain·캐시·문서 상태를 각 OS 프로세스가 독립 소유한다.
- 장치 생성 실패, 원격 데스크톱, 드라이버 reset에는 CPU 표시 경로로 전환한다. 편집 좌표와 저장 결과는 백엔드와 무관해야 한다.

Direct2D는 PDF 파일을 해석하는 엔진이 아니다. PyMuPDF가 CPU에서 PDF 명령을 해석하고 원래 glyph 윤곽과 이미지를 제공하며, Direct2D는 지원되는 장면을 래스터화·합성한다. 기존 PDF 글자를 DirectWrite로 다시 조판하지 않는다. 지원 범위와 혼합 조합의 제한은 위 현재 단계에 따른다. CPU island로 대체할 수 없는 미지원 명령이 있거나 이미지 장면 데이터가 64 MiB를 넘으면 페이지 전체를 기존 CPU 타일 경로로 표시한다.

Microsoft 문서의 [Direct2D device context 구성](https://learn.microsoft.com/en-us/windows/win32/direct2d/devices-and-device-contexts), [Direct2D·Direct3D 상호 운용](https://learn.microsoft.com/en-us/windows/win32/direct2d/direct2d-and-direct3d-interoperation-overview), [DXGI 개요](https://learn.microsoft.com/en-us/windows/win32/direct3ddxgi/d3d10-graphics-programming-guide-dxgi)를 기준으로 구현한다.

## 구현 경계

Python/PyQt5의 현재 배포본에는 Direct2D QPA 플러그인이 없다. 네이티브 Windows 렌더러를 별도 모듈로 만들고 PyQt 창의 HWND에 붙이는 방식을 사용한다. Python은 문서·편집 명령·접근성 UI를 소유하고, 네이티브 모듈은 다음의 제한된 명령만 받는다.

- 창 연결·크기/DPI 변경, 장치 생성·해제, 프레임 시작·표시.
- 페이지 타일 추가·갱신·폐기와 행렬·clip·불투명도 지정.
- 조판 개체의 도형·이미지·텍스트 표시와 선택/안내선 overlay.
- 장치 손실·메모리 부족·대체 경로 전환 알림과 진단 수치.

PDF 저장, 실행 취소, OCR, 페이지 구성과 파일 잠금은 네이티브 렌더러에 넣지 않는다. 렌더러 충돌은 해당 작업 프로세스에만 국한하며, 다른 파일을 연 별도 프로세스에 전파하지 않는다. 같은 파일의 리더는 정상 인계 뒤 이미 종료될 수 있으므로 디스크의 정상본과 독립 복구 사본으로 다시 열 수 있어야 한다.

## 단계

1. 현재 타일·페이지 좌표·캐시 정책과 화면 표면 생성 코드를 분리한다. CPU와 기존 OpenGL 경로로 회귀 검사를 유지한다.
2. 작은 네이티브 시제품에서 HWND, D3D11 BGRA 장치, DXGI flip-model swap chain, Direct2D device context와 DirectWrite factory를 생성한다. 장치 생성·빈 프레임·bitmap 합성·resize·해제를 완료했다.
3. 현재 512px 타일을 복사해 리더·편집기의 확대·이동과 overlay를 표시한다. 탭당 RAM 캐시 상한, GPU bitmap 연동 폐기, 숨김·닫기 후 자원 회수를 적용했다. 다중 모니터 DPI 전환과 실제 장치 손실 복구 시험은 계속한다.
4. 단순 벡터·fill text·배치 이미지는 MuPDF 표시 장면에서 추출해 Direct2D로 표시한다. 반복 glyph geometry realization과 64 MiB 이미지 장면 상한을 적용했다.
5. 벡터·텍스트 클리핑의 중첩 push/pop을 Direct2D layer로 적용하고 색상 스텐실 마스크를 GPU 이미지로 합성한다. shading은 제한된 고품질 이미지로 만들고 일반 격리 투명도 그룹은 opacity layer로 처리한다. 소프트/클리핑 마스크와 특수 혼합 모드는 지원 범위에 넣기 전 CPU 대체 경로와 800% 확대 품질을 비교한다.
6. PDFium/Skia GPU canvas는 별도 비교 시제품 후보로 유지한다.
7. 편집 개체의 이동·크기 조절·회전은 변경 영역만 다시 표시한다. CPU PDF 해석 지연과 GPU 래스터·합성 지연을 따로 기록한다.
8. GPU 래스터화 지원과 메모리 정책이 안정화되면 현재 800% 확대 상한을 높인다. 새 상한은 고배율 글자·곡선·그라데이션 품질, 좌표 정밀도, 뷰포트 단위 메모리 사용량을 측정한 뒤 결정한다. 숫자 제한만 먼저 해제하지 않으며 CPU 안전 경로의 고배율 처리도 함께 검증한다.

## GPU 후속 성능·품질 과제

상태: 진행 중. GPU 래스터화 지원 범위 확장과 별도로 성능·품질을 계속 검증한다.

### 후속 작업

- [ ] **실제 렌더 경로 확인:** 페이지별 GPU 래스터화, CPU 래스터화 후 GPU 합성, 혼합 경로와 전체 CPU 대체를 구분한다. GPU 표시만으로 벡터·글자 GPU 지원이나 속도 우위를 판단하지 않는다. 대체 사유와 해당 명령·그룹을 함께 수집한다.
- [ ] **초기 캐시 생성 지연:** 1.29.5는 빠른 명령 검사 후 복잡한 쪽을 CPU로 먼저 표시하고 별도 프로세스에서 GPU 장면을 준비해 교체한다. 남은 작업은 PDF 해석, 장면 추출, glyph/geometry 생성, 이미지 디코딩·색 변환, shading 이미지 생성, GPU 업로드, 첫 프레임, 선명한 화면 완성 시간을 계속 분리 측정하고, 새 프로세스의 첫 열기와 같은 프로세스의 재열기·재방문·확대/축소를 비교하는 것이다.
- [ ] **캐시 재사용·입력 반응:** 동일 이미지·glyph·geometry의 중복 생성/업로드, 불필요한 캐시 무효화와 Python 픽셀 루프를 조사한다. 재사용·일괄 변환·보이는 영역 우선 처리를 검토하되, 문서 수정 시 무효화와 닫기·숨김 시 자원 회수는 유지한다. 트레이 상주 여부와 독립적으로 측정한다.
- [ ] **리더 확대 배율 표시:** CPU/GPU 경로와 무관하게 리더에서 확대·축소 시 하단 배율 입력값이 잠깐 실제 값으로 바뀐 뒤 100%로 되돌아가는 문제가 남아 있다. 실제 화면 확대는 적용되므로 표시 상태 갱신 또는 늦은 레이아웃 동기화 경로를 분리해 수정한다.
- [ ] **안티앨리어싱 품질:** Direct2D 컨텍스트의 per-primitive/grayscale AA 명시는 적용했고, 실제 출력 픽셀에서 사선 도형의 중간 알파와 흰 배경의 회색 edge를 회귀 검사한다. 남은 작업은 100%·폭 맞춤·800% 및 Windows 100/125/150/200% 배율에서 글자 윤곽, 사선·곡선, 클리핑·마스크 경계와 이미지 확대 품질을 CPU 기준 화면과 비교하는 것이다. 벡터 AA와 이미지 보간을 구분하고 PDF의 명시적 Interpolate 설정을 무조건 덮어쓰지 않는다.
- [ ] **장면 메모리 상한:** 디코딩 이미지·shading·반복 자원별 필요량과 누적량을 기록한다. 64 MiB 페이지 이미지 장면 제한, CPU 타일 캐시, 256 MiB 명시적 합성 버퍼 예약 및 실제 DXGI budget을 서로 구분한다. 중복 자원 공유·지연 생성·영역별 처리와 기존 자동/낮음/보통/높음 정책을 검토하며, 원인 확인 없이 상한만 올리거나 해상도를 몰래 낮추지 않는다.
- [ ] **복잡 효과 PDF 판별과 CPU island:** 작은 shading band, 투명도 그룹, knockout 그룹이 과도하게 반복되는 페이지는 GPU 장면 추출 초기에 비용을 예측하고 세션 안에서 실패 결과를 캐시한다. 1.29.0의 CPU island는 정확 island를 먼저 시도하고, 작은 영역의 겹침/중첩 그룹은 근사 island로 GPU 표시를 유지한다. 다음 단계는 근사 island의 화질 차이를 CPU 기준 화면과 비교하고 timeout 전에 문제 그룹을 더 빨리 찾아 scene 추출 비용을 줄이는 것이다.

완료 확인 시 CPU/GPU 경로, 첫 열기·재사용 지연, 최고 RAM/VRAM 사용량, 확대 화면 비교를 함께 확인한다. GPU 표시 여부만으로 성능·품질 개선 완료를 판정하지 않는다.

## 완료 기준

- 같은 문서·장비에서 입력 후 첫 화면, 연속 이동/변형, 선명한 화면 완성 시간을 기존 경로와 비교한다.
- 100%, 폭 맞춤, 800% 확대에서 글자·선·clip·투명도와 선택 좌표가 맞는다.
- 다중 모니터 DPI 변경, 창 resize, 절전 복귀, 원격 데스크톱과 장치 reset 뒤 복구한다.
- 숨긴 탭·닫은 창의 대기 작업과 장치 자원이 남지 않고 종료를 지연하지 않는다.
- GPU를 끄거나 사용할 수 없어도 읽기·편집·실행 취소·저장 결과가 동일하다.

## PDF 내부 sPDF 편집 데이터

PDF 1.3 이후의 page-piece dictionary와 PDF 1.4 이후 문서 catalog의 `PieceInfo`에는 응용 프로그램 전용 데이터를 넣을 수 있다. sPDF는 `/PieceInfo << /sPDF ... >>` 아래 application data dictionary의 `/Private` stream에 형식 버전이 있는 JSON 또는 CBOR 데이터를 저장하는 방식을 시제품으로 검증한다. `/LastModified`를 함께 기록하고, 모르는 다른 응용 프로그램 항목은 보존한다.

여기에는 안정적인 개체 ID, 그룹·스타일·프레임 연결, 안내선, 원본 문자열과 출력 설정처럼 비교적 작은 편집 정보를 넣을 수 있다. 일반 PDF 뷰어는 이를 무시하므로 PDF 열람에는 필요하지 않아야 한다. [Adobe PDF Reference의 Page-Piece Dictionaries](https://opensource.adobe.com/dc-acrobat-sdk-docs/pdfstandards/pdfreference1.5_v6.pdf)와 [PDF Association의 custom metadata 지침](https://pdfa.org/download-area/publications/Including-custom-metadata-structures-in-PDF.pdf)을 따른다.

`PieceInfo`는 최적화·정리·다른 프로그램의 재저장에서 제거되거나 현재 PDF 내용과 불일치할 수 있다. 따라서 첫 조판 버전의 완전한 재편집 원본은 `*.spdf-layout` 컨테이너로 유지하고, PDF 내부 데이터는 이동이 편한 보조 사본으로 취급한다. 큰 원본 이미지·글꼴·복구 이력은 PDF private stream에 무조건 넣지 않는다. 데이터 크기·압축 해제 상한, 스키마 검증, checksum, 암호 PDF와 전자서명 변경 경고를 적용한다.
