# 남은 Python 준비 작업: 글자 목록과 이미지 채널 변환

2026-10-31 · 미배포 1.37.3 유지 · 네이티브 path 추출 위의 추가 변경

## 계측과 구현

남은 추출을 cProfile로 조사했다. 계측된 글자 윤곽 준비는 ACB 2015에서 약
243ms, 2019에서 약 151ms였고, 2019의 RGB 채널 변환은 약 64ms였다.
이는 계측 오버헤드가 있는 진단값이며 아래 비계측 벤치마크와 더하지 않는다.

- MuPDF의 공개 text/span 구조를 같은 SDK로 컴파일한 C++ 브리지에서 순회한다.
  glyph ID·font 주소·Unicode·MuPDF로 계산한 변환 행렬을 40바이트 레코드로 전달한다.
  Python은 레코드마다 기존 VectorPath를 생성하지만 SWIG의 span/items/행렬 호출은 생략한다.
- glyph 윤곽은 기존 작업별 캐시를 유지한다. 새 glyph는 네이티브에서 outline 생성과
  packed path 추출을 수행한 뒤 원래 MuPDF path를 즉시 해제한다.
- 음수 glyph ID 복구, bitmap/Type3·윤곽 누락은 원래 Python 처리로 돌아간다.
  -1 중복 Unicode 매핑은 기존과 같이 건너뛴다. font 주소는 text callback 안에서만
  사용하며, 이후 캐시에는 기존처럼 주소 정수 키와 소유한 좌표만 남긴다.
- 일반/테두리 글자 클립의 변환·병합도 Rust에서 packed 버퍼로 직접 생성한다.
  빈 클립은 기존의 빈 경로 의미를 유지한다.
- RGB/RGBA→premultiplied BGRA는 Rust에서 단일 출력 버퍼로 처리한다.
  채널별 임시 목록과 Python의 RGBA 픽셀 generator를 생략한다. 반올림은 기존
  `(value * alpha + 127) // 255`와 동일하다. RGB는 alpha=255로 채운다.

## 비교

`python -m tests.benchmark_native_hotspots <PDF...> --output <JSON>`

기존 native path/packed 추출은 양쪽 모두 켜고 native text와 Rust pixel packing만
번갈아 바꾼다. packed 글자 클립은 두 방식의 공통 동작이므로 별도 속도 기여를
이 표에 포함해 주장하지 않는다. `pickle`은 이전 글자 순회/채널 변환, `packed`는
후보다. 워밍업 1회 뒤 각 7회 중앙값, 두 번째 실행은 문서 순서를 반대로 했다.
페이지 1/source scale 1, 새 추출·직렬화·복원·GPU 장면 생성이며 결과 재사용은 없다.
파일 열기·GC·디스크 캐시·프로세스 시작·최종 그리기는 타이머 밖이다.

| 실행 | 문서 | 추출→전달→GPU 준비 기존 → 후보 | 단축 |
|---|---|---:|---:|
| 1 | ACB 2015 | 1,421.55 → 1,355.26ms | 4.7% |
| 1 | ACB 2019 | 1,339.24 → 1,278.93ms | 4.5% |
| 2 | ACB 2015 | 2,679.47 → 2,481.87ms | 7.4% |
| 2 | ACB 2019 | 2,220.12 → 2,044.90ms | 7.9% |

실행 사이 시간 변동이 컸다. 두 번 모두 방향은 개선됐지만 특정 ms 지연을
보장하는 수치가 아니다. 첫 text-only 탐색에서는 특히 2015의 시간 변동이 커
`native-text-first.json`은 속도 개선의 채택 근거로 사용하지 않았다.

각 문서의 전체 복원 장면/GPU 경로 배열과 맞춤·100%·800% 화면의 픽셀 해시를
검사했다. 각 실행의 6개 화면 모두 일치했다. 글자·효과 품질을 낮추지 않았다.

## 검증과 남은 범위

회전·공백·반복 글자·글자 클립, Python span 생성 금지 상태의 실제 PDF 추출,
native text 부재 fallback을 검사한다. 이미지 변환은 채널 값×alpha의 65,536개
조합과 RGB/빈 입력/짧은 입력/기존 bytearray 입력을 비교한다.
실제 worker·리더·GPU 합성·배포를 포함한 관련 테스트 266개가 통과했다.

PDF 수준 그룹/clip/image callback, 영역 단순화 장치, 최종 Python 장면 항목 생성은
아직 남는다. 이미지 디코딩/다운샘플은 이미 MuPDF 네이티브가 처리한다. Python 코드
줄 수만 줄이기 위해 이를 다시 작성하지 않았다. 전체 RSS/VRAM은 따로 계측하지 않았다.
원본과 표본은 비공개 tmp/rust-audit/native-hotspots-{first,second}.json에 보관한다.
