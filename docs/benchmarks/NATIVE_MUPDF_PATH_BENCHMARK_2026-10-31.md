# MuPDF 경로의 네이티브 직접 추출

2026-10-31 · 미배포 1.37.3 · 이전 직접 packed 병합 위에 추가 적용

## 구현과 한계

활성 PyMuPDF wheel의 헤더/import library로 작은 C++ 브리지를 빌드했다.
MuPDF의 공개 C++ `ll_fz_walk_path` wrapper에 native moveto/lineto/curveto/close
callback을 연결해 packed float64 버퍼를 만든다. 같은 path를 읽을 때 좌표마다
Python 콜백을 호출하지 않는다. 이어지는 Rust 변환/병합은 packed 입력을 직접 읽는다.

MuPDF의 context나 내부 path 구조를 추정하지 않는다. SWIG가 제공하는 borrowed
path 주소를 동기 호출 동안만 사용하고, MuPDF의 thread-local wrapper context를
사용한다. Python GIL은 유지한다. C++ 예외/할당 실패는 브리지 안에서 처리하며
path 하나의 출력은 16MiB로 제한한다. 복사 후 native 버퍼는 즉시 반환한다.
버전이 다르거나 브리지가 없으면 원래 Python walker를 사용한다.

worker의 새 추출에만 native_paths=True/packed_paths=True를 적용했다.
PDF 수준 device callback, font/span 순회, 일부 text clip/패턴 분석은 Python에 남는다.
MuPDF 연결은 C++이며, 버퍼 변환·병합은 Rust다. 전체 PDF 장치를 Rust로 재작성한
결과가 아니다. 장면 형식과 렌더러 ABI는 유지한다.

## 비교

`python -m tests.benchmark_native_path <PDF...> --output <JSON>`

기준과 후보 모두 이전 packed 병합/소비 경로를 유지하고 MuPDF walker만 바꾼다.
페이지 1/source scale 1, 1200×900 출력. 매 표본 새 문서 페이지에서 추출하고 새
직렬화/복원/네이티브 GPU 자원을 만든다. 결과 재사용 없음. 워밍업 1회 후 각각
7회, 두 방식 순서를 번갈아 실행했다. 두 번째 실행은 문서 순서도 반대로 했다.
GC와 파일 열기는 타이머 밖이다.

총계는 추출 시작→전달 인코딩→수신 복원→GPU 장면 생성이다. 프로세스 시작,
파일 입출력, 장면 비용 계산, 디스크 캐시 저장, 최종 그리기 시간은 제외한다.
JSON의 pickle은 Python walker, packed는 native walker이며, 배열은
추출/인코딩/복원/업로드/총계 순서다.

| 실행 | 문서 | 추출 Python → native | 총계 Python → native | 총계 단축 |
|---|---|---:|---:|---:|
| 1 | ACB 2015 | 993.33 → 892.64ms | 1,279.94 → 1,166.92ms | 8.8% |
| 1 | ACB 2019 | 902.02 → 868.98ms | 1,099.29 → 1,066.10ms | 3.0% |
| 2 | ACB 2015 | 1,244.92 → 1,183.80ms | 1,615.96 → 1,520.19ms | 5.9% |
| 2 | ACB 2019 | 1,175.83 → 1,087.18ms | 1,466.06 → 1,330.12ms | 9.3% |

두 실행의 절대 시간 차이가 크므로 고정 지연 보장에 사용하지 않는다.
두 문서/두 실행 모두 전체 경로 입력 비교와 맞춤·100%·800% 화면 픽셀 해시가
일치했다. 출력 품질 변경이나 좌표 정밀도 감소는 없다. 별도 메모리 실측은 하지 않았다.

## 검증과 빌드

직선·곡선·사각형·빈 path, 실제 글자/도형 추출에서 Python walker 생성 금지,
누락/버전 불일치 fallback을 검사한다. 기존 추출·캐시·리더·GPU 합성·배포 관련
263개 테스트를 실행했다. 소규모 PyInstaller 패키지로 DLL 로드를 별도 확인한다.
전체 설치 프로그램/MSIX 릴리스 빌드는 이번 작업 범위에 포함하지 않았다.

tools/build/build_exe.bat와 CI는 native/build_mupdf_path.py를 실행하고, spec은 브리지를
native/에 포함한다. 소스 재빌드 안내도 추가했다. 비공개 원본/표본은
tmp/rust-audit/native-path-first.json, native-path-second.json에 보관한다.
