# ACB GPU 파이프라인 구간별 계측

측정일: 2026-10-23 · Leaflet 1.37.1 개발 중 · Intel Iris Xe · ABI 24

## 판단

다음 우선순위는 **작은 합성 작업의 제출과 임시 표면 할당 구조**다. ACB 2015에서 복사 호출 자체보다 Direct2D `Flush`와 scratch 표면 준비에 CPU 시간이 크게 잡혔다. 이 두 구간은 재측정한 worker CPU 경과 시간의 약 78~80%에 해당한다. 마스크 산술식만 바꾸거나 복사 픽셀 수만 줄이는 접근보다 이 구조를 실험할 근거가 강하다.

이는 새 최적화의 속도 개선 결과가 아니다. 기본 네이티브 소스·DLL은 변경하지 않았고, 별도 진단 빌드로 구간을 측정했다. 렌더 결과 캐시나 근사는 추가하지 않았다. 실제 GPU의 복사 엔진·셰이더 활성 시간을 서로 완전히 분리한 측정도 아니다.

## 측정 범위

- ACB 2019와 ACB 2015 첫 페이지, 1200×900 viewport, 96 DPI, 맞춤·100%·200%, raster scale 1. 각 표본에서 새 장면을 만들어 결과 이미지 재사용을 막았다.
- CPU 진단은 `QueryPerformanceCounter`로 타일 target 준비, 계획, binding, replay, EndDraw를 잰다. 복사 helper 안의 Flush·CopyFromBitmap 호출과 나머지 상태 변경을 구분한다. replay의 명령 종류별 시간과 scratch 준비·새 할당도 별도로 집계한다.
- 한 프레임의 9개 타일 시간을 합산하고, 3회 예열 후 7개 프레임의 중앙값을 계산한다. 명령별 시간은 해당 API 호출을 CPU에서 처리하는 경과 시간이다. GPU 셰이더 시간이나 순수 CPU 사용률이 아니다.
- 기본 DLL과 CPU 진단 DLL의 실행 순서를 같은 프로세스에서 회전·교차했다. 첫 실행에서는 타일마다 로그 파일을 여닫아 관측 완료 시간을 교란했다. 최종 CPU 표는 로그를 작업당 한 번 열고 버퍼링한 재측정 값이다. 다른 GPU 테스트·빌드는 측정 중 실행하지 않았다.
- GPU 진단은 별도 실행에서 타일마다 timestamp 두 개, timestamp-disjoint, pipeline-statistics query를 사용했다. 3회 예열 후 3회 측정했다. EndDraw 뒤 진단용 D3D Flush와 최대 3초의 query 수집 대기가 추가되므로 이 실행의 완료 시간을 성능 비교에 사용하지 않는다.

## CPU 구간

단위 ms, 프레임당 중앙값. 열별 중앙값이므로 단순 합이 CPU 전체와 일치하지 않을 수 있다. Flush·복사 호출·scratch·도형 명령의 측정 구간은 서로 겹치지 않는다. scratch 시간에는 검색과 새 할당이 포함된다. 합성 명령 전체의 포괄 시간은 이 표에 더하지 않는다.

| 문서 | 보기 | Worker CPU 전체 | 명시적 Flush | 복사 호출 | Scratch 준비 | 도형 명령 처리 | 계획 | Binding |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| ACB 2019 | 맞춤 | 77.86 | 30.46 | 1.24 | 29.86 | 0.61 | 0.37 | 2.83 |
| ACB 2019 | 100% | 44.85 | 14.61 | 0.45 | 16.27 | 0.37 | 0.30 | 1.99 |
| ACB 2019 | 200% | 25.46 | 8.58 | 0.19 | 6.66 | 0.23 | 0.23 | 0.03 |
| ACB 2015 | 맞춤 | 707.04 | 337.62 | 20.57 | 215.22 | 33.99 | 5.53 | 4.77 |
| ACB 2015 | 100% | 589.06 | 276.78 | 12.08 | 193.72 | 19.30 | 4.62 | 2.49 |
| ACB 2015 | 200% | 307.01 | 140.24 | 6.53 | 106.40 | 5.67 | 1.88 | 1.09 |

도형 명령은 사각형·bitmap·path fill/stroke·linear/radial gradient의 transform 설정과 그리기 API 호출을 포함한다. 앞서 기록한 도형의 처리·tessellation·driver 제출·잠금·자원 의존 대기 등은 Flush에서 발생할 수 있다. 따라서 위의 작은 도형 명령 시간을 GPU가 그림을 그리는 전체 비용으로 해석하거나, Flush 시간을 전부 제거 가능한 고정 오버헤드로 해석해서는 안 된다. 직접 pixel readback은 worker 측정에 들어가지 않는다.

ACB 2015 scratch 준비 중 새 `CreateBitmap` 구간은 맞춤 214.09ms, 100% 193.00ms, 200% 105.95ms다. 이 값은 `borrow_scratch`가 담당하는 표면만의 측정이다. 격리 Normal source 등 직접 생성 경로의 할당과 effect 생성 비용은 다른 합성 구간에 남아 있으므로 전체 표면 할당 비용의 상한으로 사용하지 않는다.

첫 CPU 실행의 ACB 2015 전체 시간은 맞춤 529.77ms, 100% 431.23ms, 200% 317.47ms였고, Flush+scratch 비중은 약 77~81%였다. 두 실행의 절대 시간 차이는 크지만 해당 구간이 크다는 관측은 유지됐다.

## 호출 수와 복사 크기

9개 타일을 모두 합산한 프레임당 값이며 반복 간 동일했다. 복사 byte 수는 bitmap의 BGRA8 면적 합계 ×4로, GPU 메모리 버스의 실측 전송량이 아니다.

| 문서 | 보기 | 복사 호출 | ≤4096픽셀 복사 | 복사 면적 합계 | 복사 용량 MiB | Flush 호출 | Scratch 요청 | Scratch 새 할당 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| ACB 2019 | 맞춤 | 148 | 52 | 2,895,940 | 11.05 | 148 | 262 | 181 |
| ACB 2019 | 100% | 50 | 4 | 1,801,440 | 6.87 | 50 | 93 | 86 |
| ACB 2019 | 200% | 24 | 0 | 2,008,110 | 7.66 | 24 | 45 | 36 |
| ACB 2015 | 맞춤 | 1,966 | 1,936 | 1,482,688 | 5.66 | 2,324 | 3,503 | 1,235 |
| ACB 2015 | 100% | 1,618 | 1,592 | 1,275,710 | 4.87 | 1,912 | 2,885 | 1,416 |
| ACB 2015 | 200% | 774 | 738 | 1,634,016 | 6.23 | 910 | 1,379 | 674 |

ACB 2015는 복사의 약 95~98%가 4096픽셀 이하다. 더 많은 픽셀을 복사하는 ACB 2019보다 호출 수가 훨씬 많다. 이 차이와 CPU 구간은 작은 그룹마다 표면·effect·target을 준비하고 제출하는 구조를 우선 조사할 이유가 된다. 두 문서는 도형과 합성 내용도 다르므로 이 비교만으로 호출 수와 완료 시간 사이의 단순 인과식은 만들지 않는다.

## GPU 진단과 해석 한계

GPU 표는 CPU 표와 다른 실행이다. 각 타일의 BeginFrame 직전과 EndDraw 직후 timestamp 사이의 GPU timeline 경과 시간을 프레임당 합산했다. Disjoint가 false이고 모든 query 수집에 성공한 표본만 사용했다. 36개 프레임, 324개 타일에서 query 실패·disjoint는 없었다.

| 문서 | 보기 | GPU timeline 합계 중앙값 ms | Pixel shader 호출 수 |
|---|---|---:|---:|
| ACB 2019 | 맞춤 | 41.29 | 8,642,596 |
| ACB 2019 | 100% | 24.01 | 10,442,628 |
| ACB 2019 | 200% | 15.01 | 9,905,084 |
| ACB 2015 | 맞춤 | 423.59 | 19,940,316 |
| ACB 2015 | 100% | 357.08 | 23,655,312 |
| ACB 2015 | 200% | 180.34 | 17,626,056 |

Timestamp 간격에는 복사·도형·합성 작업뿐 아니라 CPU 공급 지연으로 GPU가 쉬는 시간도 들어갈 수 있다. 반대로 query를 포함한 D3D batch가 실제 제출되기 전의 CPU 시간은 GPU clock 구간에 전부 나타나지 않는다. 장치는 UI context와 공유한다. 이는 셰이더가 계속 활성 상태였던 시간이나 복사 엔진만의 시간이 아니며 CPU 표에 더할 수도 없다. Pixel shader 호출 수도 실행 비용이 다른 shader를 구분하지 않는다.

복사 API가 D2D와 D3D 사이에서 명령을 제출하는 방식 때문에 호출 앞뒤에 timestamp만 끼워 넣어 GPU 복사 시간을 단정하지 않았다. GPU copy/draw의 활성 시간까지 정확히 나누려면 드라이버 제출과 context scheduling을 함께 볼 수 있는 GPU trace가 더 필요하다. 이번 결과는 CPU 쪽 다음 최적화 대상을 정하는 자료다.

Direct2D Flush는 pending drawing commands를 실행하지만 D3D device context를 flush하는 명령과 같지 않다. Query의 단위와 완료 여부도 별도로 확인해야 한다. 근거: [Direct2D Flush](https://learn.microsoft.com/en-us/windows/win32/api/d2d1/nf-d2d1-id2d1rendertarget-flush), [D3D11 query 종류](https://learn.microsoft.com/en-us/windows/win32/api/d3d11/ne-d3d11-d3d11_query), [DONOTFLUSH 수집](https://learn.microsoft.com/en-us/windows/win32/api/d3d11/ne-d3d11-d3d11_async_getdata_flag).

## 계측 영향과 출력

같은 실행 안의 요청→전체 정밀 atlas 완료·UI import 중앙값이다. UI 관측 polling은 1ms다. CPU 진단이 기본 경로와 같은 속도라고 가정하지 않는다. 첫 타일 로그 방식의 결과는 원자료에 보존하고 아래는 작업당 버퍼링 재측정만 기재한다.

| 문서 | 보기 | 기본 DLL ms | CPU 진단 DLL ms |
|---|---|---:|---:|
| ACB 2019 | 맞춤 | 84.95 | 83.52 |
| ACB 2019 | 100% | 40.89 | 49.80 |
| ACB 2019 | 200% | 26.70 | 29.86 |
| ACB 2015 | 맞춤 | 758.55 | 713.22 |
| ACB 2015 | 100% | 592.32 | 595.34 |
| ACB 2015 | 200% | 273.10 | 311.05 |

증감 방향이 조건별로 섞여 있어 이 표에서 계측기의 일정한 오버헤드나 속도 개선율을 추정하지 않는다.

첫 CPU 비교 6개 화면, 버퍼링 CPU 재측정 6개 화면, 별도 GPU 진단 6개 화면을 기본 출력과 byte 단위로 비교해 모두 차이 0을 확인했다. 모든 benchmark case가 오류 없이 예정된 표본 수를 완료했다. 진단 빌드는 C++17 /W4 /WX /O2로 빌드했고, CPU 진단 DLL의 기존 합성 검사 16개도 통과했다.

## 다음 구현 후보

1. 타일 계획에서 합성 표면의 크기·형식·필요 시점·마지막 참조를 계산한다. 결과 이미지를 다음 프레임에 저장하는 대신 한 작업 안에서 필요한 임시 저장소를 묶어서 준비하는 후보를 만든다. 새 할당 횟수와 실제 메모리 peak를 함께 잰다.
2. 크기별 저장소 묶음 또는 atlas/배열 배치를 검토하되 D2D target과 input의 동시 사용 제한, 중첩 깊이, coverage·backdrop의 원점과 padding을 처리해야 한다. 미리 모든 표면을 개별 할당하는 변경만으로 호출 수가 줄어든다고 가정하지 않는다. 공유 texture를 D2D에 그대로 적용할 수 있다고 단정하지 않는다.
3. Normal clip/mask부터 전용 합성 실행기에 연결해 효과 그래프·target 전환·제출 경계를 줄이는 후보를 비교한다. 이전 [단독 자식 합성 통합](GPU_NESTED_MASK_BENCHMARK_2026-10-23.md)은 실제 대상이 적어 이득이 재현되지 않았다. 더 넓은 그룹을 다룰 수 있는 계획이 필요하다.
4. COPY·knockout·비격리 그룹, raw mask 생성, 비선형 transfer는 기존 경로를 유지하는 조건부터 시작한다. 합성 입력의 마지막 사용을 보장하지 않고 Flush를 삭제해서는 안 된다. 취소·할당 실패·장치 오류 fallback과 작업별 메모리 상한을 함께 설계한다.

최적화 후보의 채택 여부는 진단기를 제거한 두 DLL의 교차 비교와 출력 검사로 결정한다. 이번 CPU 비중을 그대로 예상 절감률로 발표하지 않는다. 투명 gradient 근사는 별도 후속 단계다.

## 원자료와 재현

- 기본 DLL SHA-256: `a70088460d3ec1d2678a80d3ecb7ab6a8ba3b4214d34179e14bc4e342ba1f429`.
- 기본 C++ SHA-256: `4c7e41c0d7612e1377cbc2e77dcf4fc362664d6dd69de90b3b57c99fd5a0648b`.
- CPU 진단 DLL SHA-256: `a31bfa0ab9e94360a4bc981aab2d9ac14ea405b815530cfd2e01d31e281b33ba`. GPU 진단 DLL SHA-256: `e52199eebb719655b455cc9afe9350998b386573be192629eaedb777e770661d`.
- 개인 폴더 `tmp/gpu-stage-profile/`의 `prepare.py`는 현재 C++에 진단 코드를 삽입한 별도 소스와 build-cpu/build-gpu 스크립트를 만든다. 출력은 cpu-bin/gpu-bin에 한정된다. 기본 소스·DLL의 byte 동일성을 확인했다.
- `cpu-timing/results.json`, `first-run/cpu.txt`: 최초 CPU 비교. `confirmation/results.json`, `cpu-corpus.txt`, `summary.json`: 버퍼링 재측정과 구간별 집계. `gpu-diagnostic/results.json`, `gpu.txt`: GPU 진단. `verify.py`는 표본 수·오류·18개 화면의 일치·기본 파일 보존을 확인한다.
- CPU 비교는 기존 `tests/benchmark_gpu_pipeline.py --mode sharp --repeats 7 --poll-ms 1`에 baseline과 cpu 두 library를 전달했다. GPU 진단은 gpu library만 전달하고 `--repeats 3`으로 실행했다. 문서·BGRA·진단 DLL·원자료는 공개하지 않는다.
- 미배포 버전은 1.37.1이다. 이번 작업은 계측과 문서이며 사용자에게 배포하는 렌더 동작은 바뀌지 않았다.
