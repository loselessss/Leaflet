# GPU 장면 arena·작업 스레드 자원 준비 비교 (2026-10-21)

기준은 1.37.1 개발 중 첫 `ReplayIndex` 공유 단계이며, 릴리스 1.37.0 자체와의 비교가 아니다. [장면 컴파일러 프로젝트](GPU_SCENE_COMPILER_PLAN.md)의 다음 단계로 명령 데이터와 실행 자원을 분리하고 작업별 binding을 GPU 작업 스레드로 옮겼다. 공개 ABI 24와 개발 버전 1.37.1을 유지한다.

## 구현 범위

- 전체 명령, gradient stop·mask transfer table 및 불변 자원 참조를 `shared_ptr<const SceneData>`에 보관한다. 입력의 resource/stroke/data 포인터는 게시할 명령에 남기지 않는다. 빈 레이어를 정리한 뒤 자원 명령에만 binding index를 지정한다.
- `SceneBinding`은 컨텍스트 소유 Path/Bitmap/StrokeStyle 래퍼와 mutable gradient brush를 담는다. 장면 arena와 실행 상태가 분리되어 UI와 worker가 같은 brush transform을 변경하지 않는다.
- 요청은 명령·가변 데이터를 복사하지 않고 arena와 분석 데이터의 소유권만 공유한다. worker가 binding을 생성하고 64개 단위로 취소를 확인한다. 할당 예외·장치 오류는 기존 비동기 상태 경로로 보고한다. 정밀 갱신 실패 시 UI는 기존 빠른 프레임을 유지한다.
- arena의 자원 참조는 같은 D2D 장치를 전제로 한다. 장치 간 교환·디스크 직렬화용 순수 CPU 형식은 아니다. worker context 초기화와 최초 Python→네이티브 장면 생성은 아직 UI 경로에 남는다.
- GPU 합성 순서, backdrop·COPY·mask 장벽, 픽셀 밀도와 타일·gutter·Flush 경계는 바꾸지 않았다. 렌더 결과 캐시를 추가하지 않았다. 타일별 계획·새 합성기·투명 그래디언트 근사는 이번 단계에 포함하지 않는다.

## 중복 저장과 실행 스레드 확인

별도 진단 DLL에서 동일 arena 주소, 공유 소유자 2개와 요청 직후 binding 0개를 확인했다. 기준의 원본·worker 준비 thread ID는 모두 32848이었다. arena는 원본 준비 32848, 완료된 worker binding은 별도 thread(예: 13768)에서 수행됐다. 이 진단 빌드의 시간은 성능 표에 쓰지 않는다.

아래는 원본 하나와 완료된 worker 하나의 명령·가변 데이터·binding 배열 및 공유 binding 역인덱스의 **capacity 기준 요청 저장량**이다. 새 arena는 한 번만 센다. 이미 첫 단계에서 공유된 분석 배열은 양쪽 공통이므로 제외했다.

| 문서 | 명령 | 자원 binding | 기준 두 장면 | arena 두 장면 | 절감 |
|---|---:|---:|---:|---:|---:|
| ACB 2019 | 324 | 160 | 133,760byte | 80,524byte | 53,236byte (0.051MiB) |
| ACB 2015 | 31,302 | 13,620 | 12,522,880byte | 7,423,868byte | 5,099,012byte (4.863MiB) |

ACB 2015는 기준 `(6,260,400 + 1,040) × 2`, arena `6,260,400 + 1,040 + 72,828 + 544,800 × 2`다. 명령 레코드는 양쪽 모두 200byte이고 새 binding은 자원 명령 13,620개에만 40byte씩 배치한다. 원본의 명령 배열 자체가 없어진 것이 아니라 worker 복사본을 없앴다. 기존 원본/worker의 경로·bitmap·stroke 래퍼 수는 같다.

Scene 객체는 144→160byte이며 별도 SceneData 객체 48byte와 공유 제어 블록 등의 소규모 추가 비용이 있다. 표는 이 객체 헤더·allocator bookkeeping·동일하게 남는 개별 COM 래퍼·GPU bitmap을 포함한 RSS/commit/VRAM 측정이 아니다. worker가 없을 때는 두 문서 모두 binding·역인덱스 저장량이 추가된다. ACB 2015 원본 장면만 보면 추가 테이블은 617,628byte(약 0.59MiB)다. 약 4.86MiB는 원본+worker 기준 추가 절감이며 앞선 분석 공유 약 1MiB와 구분한다.

## 측정 조건

- Intel Iris Xe hardware / PyMuPDF 1.28.2 / 1200×900 물리px / 96 DPI / 이미지 준비 배율 1 / ACB 두 문서의 첫 페이지. 두 DLL 실행 순서를 교대한다.
- 매 표본 새 scene identity를 만들어 페이지·그룹·정밀 타일 결과 재사용을 배제한다. 준비 3회 후 요청과 장면 생성은 각 25회, 전체 완료는 15회 측정한다. P95는 nearest-rank다. 측정 중 GPU 검사·빌드·다른 benchmark를 실행하지 않는다.
- 요청 반환은 `request_sharp_scene` 호출만 재며 취소는 타이머 밖이다. 새 worker binding이 실행되는 시간 전체나 GPU 완료를 뜻하지 않는다. 기존 UI의 명령 복사·brush 준비가 worker로 옮겨진 효과를 측정한다.
- 전체 정밀 완료는 worker binding과 viewport atlas 준비·가져오기를 포함하고 30ms 간격으로 확인한다. 첫 타일 시간도 같은 간격의 관측값이다. 최초 PDF 해석·immutable geometry/bitmap 업로드·retained scene 생성·90ms 입력 안정화·Present/vsync는 제외한다.
- 별도 장면 생성 표는 Python 명령 변환·네이티브 arena 생성·원본 binding을 포함한다. 파일 해석·geometry/bitmap 업로드는 타이머 밖이다. 과거 441ms와 직접 빼지 않는다.

### UI 작업 요청 반환 (ms)

감소율은 양수가 단축, 음수가 악화다.

| 문서 | 보기 | 기준 | arena | 감소율 | 기준 P95 | arena P95 |
|---|---|---:|---:|---:|---:|---:|
| ACB 2019 | 화면 맞춤 | 4.62 | 0.79 | +82.8% | 6.45 | 3.52 |
| ACB 2019 | 100% | 4.95 | 0.74 | +85.0% | 6.85 | 3.12 |
| ACB 2019 | 200% | 3.29 | 0.75 | +77.2% | 6.49 | 4.47 |
| ACB 2015 | 화면 맞춤 | 13.47 | 0.70 | +94.8% | 16.27 | 2.68 |
| ACB 2015 | 100% | 13.33 | 0.78 | +94.1% | 17.07 | 3.78 |
| ACB 2015 | 200% | 9.35 | 0.77 | +91.7% | 15.73 | 3.87 |

### 정밀 화면 전체 완료 (ms)

| 문서 | 보기 | 기준 | arena | 감소율 | 기준 P95 | arena P95 |
|---|---|---:|---:|---:|---:|---:|
| ACB 2019 | 화면 맞춤 | 192.48 | 189.95 | +1.3% | 285.22 | 282.91 |
| ACB 2019 | 100% | 97.88 | 97.25 | +0.6% | 136.54 | 129.94 |
| ACB 2019 | 200% | 64.89 | 64.27 | +1.0% | 86.18 | 72.53 |
| ACB 2015 | 화면 맞춤 | 1492.82 | 1410.63 | +5.5% | 2102.16 | 2143.05 |
| ACB 2015 | 100% | 1497.32 | 1523.25 | -1.7% | 2196.39 | 2245.73 |
| ACB 2015 | 200% | 954.43 | 868.09 | +9.0% | 1314.33 | 1253.71 |

### 첫 타일 관측 (ms)

| 문서 | 보기 | 기준 | arena | 감소율 |
|---|---|---:|---:|---:|
| ACB 2019 | 화면 맞춤 | 64.86 | 62.77 | +3.2% |
| ACB 2019 | 100% | 36.42 | 33.01 | +9.4% |
| ACB 2019 | 200% | 36.03 | 32.66 | +9.4% |
| ACB 2015 | 화면 맞춤 | 1330.82 | 1286.52 | +3.3% |
| ACB 2015 | 100% | 655.12 | 650.12 | +0.8% |
| ACB 2015 | 200% | 83.54 | 65.48 | +21.6% |

### 최초 retained scene 생성 (ms)

| 문서 | 보기 | 기준 | arena | 감소율 | 기준 P95 | arena P95 |
|---|---|---:|---:|---:|---:|---:|
| ACB 2019 | 장면 생성 | 6.62 | 5.88 | +11.2% | 11.37 | 10.98 |
| ACB 2015 | 장면 생성 | 447.64 | 475.34 | -6.2% | 514.34 | 511.45 |

UI 요청 반환의 개선과 전체 GPU 완료 속도를 구분한다. 합성 명령은 그대로여서 드라이버·스케줄링 변동이 크고, 전체 완료가 모든 문서·배율에서 같은 비율로 빨라진다고 일반화하지 않는다. 최초 장면 생성에는 arena·원본 binding 준비가 남아 있으므로 해당 표의 변화도 함께 판단한다.

## 저장 화면

| 문서 | 보기 | 바뀐 픽셀 | 최대 채널 차이 |
|---|---|---:|---:|
| ACB 2019 | 화면 맞춤 | 0 | 0 |
| ACB 2019 | 100% | 0 | 0 |
| ACB 2019 | 200% | 0 | 0 |
| ACB 2015 | 화면 맞춤 | 0 | 0 |
| ACB 2015 | 100% | 0 | 0 |
| ACB 2015 | 200% | 0 | 0 |

두 문서의 세 배율에서 저장한 6개 BGRA 화면이 기준과 완전히 같다.

## 검증과 재현

- C++17 `/W4 /WX /O2` 및 strict shader 빌드 통과. GPU 관련 검사 103개가 54.905초에 통과했다. 별도 WARP 강제 빌드에서도 합성 검사 14개가 21.958초에 통과했다.
- 새 검사는 원본 Path/Bitmap/StrokeStyle 해제와 Python gradient/transfer 변경 후의 지연 binding, UI/worker의 서로 다른 gradient transform, 96/144 DPI·회전·취소·작업 교체를 확인한다.
- 별도의 fault-injection 빌드에서 worker의 첫 binding에 `std::bad_alloc`을 발생시켰다. `E_OUTOFMEMORY`가 비동기 상태로 보고되고, 취소 후 같은 queue의 다음 작업이 픽셀 변경 없이 완료됨을 확인했다. 진단용 실패 주입은 개발 DLL에 들어 있지 않다.
- 기준 DLL SHA-256: `acab92192814382989b3798db58a98afeed96bf04d0ec9bda02a22e686d8db72`.
- arena DLL SHA-256: `f3360f95b915594058f6a578d75161bc8c6ac948496f8a0e78db41e7156db527`. 최종 소스·개발 DLL과 측정 복사본의 동일성을 확인했다.
- 원자료: 개인 파일인 `tmp/gpu-scene-arena/{request,sharp,scene}-comparison/results.json`, `memory-baseline.txt`, `memory-arena.txt`, `final-tests.log`, `warp-tests.log`. 입력 PDF·BGRA·진단 DLL을 커밋하거나 공개하지 않는다.
- 재현: `tests/benchmark_gpu_pipeline.py`의 `--mode request --repeats 25`, `--mode sharp --repeats 15`, `--mode scene --repeats 25`와 `--library baseline=... --library arena=...`를 사용한다.
