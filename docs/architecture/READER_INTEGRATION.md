# sPDF 리더 API 연동 가이드

외부 앱에서 sPDF 리더를 재사용하기 위한 API와 동작을 설명합니다.
대상은 읽기 전용 보기와 선택적 주석 기능이며, 외부 앱 자체의 기능·설정 UI·개발 계획은 다루지 않습니다.

sPDF 1.20.0의 독립 실행 리더·편집기는 서로 다른 OS 프로세스로 동작합니다.
아래 내장 API는 기존처럼 호스트의 `QApplication`과 프로세스 안에서 동작합니다.
`workspace_mode`를 생략하면 독립 실행용 편집 프로세스 버튼을 만들지 않으며,
`read_only`·주석 옵션·자체 업데이트 비활성 계약은 그대로입니다.
독립 실행 구조는 [프로세스 분리 문서](PROCESS_ISOLATION.md)를 참고하세요.

독립 실행 `workspace_mode="reader"`는 형광펜·메모를 허용하며 Ctrl+S로 원본 PDF에
저장합니다. Ctrl+Shift+S는 PDF 사본을 저장하고 현재 경로를 바꿉니다. 원본 자동저장은
사용하지 않습니다. 아래 별도 주석 저장 계약은 `workspace_mode`를 생략한 내장 API에 적용됩니다.

## ON/OFF 설정

호스트가 실행한 `QApplication`의 GUI 스레드에서 호출합니다. sPDF를 따로 실행하거나
두 번째 `QApplication`을 만들 필요는 없습니다. 파일 열기는 이벤트 루프에서 진행됩니다.

```python
from pdfeditor.app import new_window

viewer = new_window(
    pdf_path,
    read_only=True,                 # 본문·페이지 편집 OFF
    annotations_enabled=True,       # 메모·형광펜 추가/수정/삭제 ON
    autosave_annotations=True,      # 주석 별도 자동저장 ON
    updates_enabled=False,          # 호스트 내부에서는 자체 업데이트 OFF
)
```

| 옵션 | 값 | 동작 |
| --- | --- | --- |
| `read_only` | `True` | 본문·페이지·책갈피 편집과 OCR 차단 |
| `annotations_enabled` | `True` | 주석 작성 허용 |
| `annotations_enabled` | `False` | 주석 보기만 허용, 작성/수정/삭제 차단 |
| `autosave_annotations` | `True` | 마지막 주석 변경 약 0.8초 후 별도 파일 저장 |
| `autosave_annotations` | `False` | Ctrl+S로 직접 저장, 미저장 상태로 닫으면 확인 |

`annotations_enabled`를 생략하면 `read_only=True`에서는 OFF, 일반 편집 창에서는 ON입니다.
`autosave_annotations` 기본값은 ON이지만 **읽기 전용 + 주석 허용 창에서만** 작동합니다.
일반 편집 창(`read_only=False`)의 기존 PDF 저장 방식은 바꾸지 않습니다.
`AppWindow(read_only=..., annotations_enabled=..., autosave_annotations=...)`도 지원합니다.

## 호스트 설정과 연결하는 예

아래 변수들은 예시이며 호스트의 실제 설정 키 이름을 가정하지 않습니다.

```python
def open_reader(pdf_path, allow_annotations, automatic_save):
    return new_window(
        pdf_path,
        read_only=True,
        annotations_enabled=allow_annotations,
        autosave_annotations=automatic_save,
        updates_enabled=False,
    )
```

세 옵션은 **창을 열 때 정하며 열린 창의 속성을 직접 변경하지 않습니다**.
설정을 바꾸어 다시 열려면 먼저 기존 창의 `close()`가 `True`를 반환했는지 확인합니다.
저장 실패나 사용자의 취소로 `False`를 반환하면 기존 창과 주석을 유지해야 합니다.
`force_new=True`는 같은 설정의 창이 있어도 별도 창을 만듭니다.
다른 설정의 창은 재사용하지 않으며, 새 창에도 설정이 그대로 이어집니다.
설정이 다른 창 사이의 탭 이동은 거부합니다. 주석 미저장 탭을 다른 프로세스로 옮기려면
먼저 주석을 저장해야 합니다.

## 저장 위치와 복원

- 원본 `paper.pdf` 옆의 `paper.pdf.spdf-annotations.json`에 주석 변경만 기록합니다.
- 원본 PDF는 자동저장이나 Ctrl+S로 수정하지 않습니다.
- 같은 PDF를 읽기 전용 창으로 다시 열면 별도 주석을 복원합니다. 주석 작성 OFF여도
  저장된 주석은 볼 수 있습니다.
- 일반 편집 창이나 다른 PDF 앱은 이 별도 파일을 불러오지 않습니다.
- PDF를 이동·이름 변경할 때 주석 파일도 함께 이동·이름 변경해야 합니다.
- 저장 권한이 있는 폴더가 필요합니다. USB·공유 폴더에서도 쓰기 권한과 여유 공간을 확인합니다.
- Ctrl+S는 주석 즉시 저장, Ctrl+Shift+S는 **주석 포함 PDF 저장**입니다.
  내보내기는 원본과 다른 경로만 허용하며 현재 창의 원본 경로를 바꾸지 않습니다.
- 다른 PDF 앱에서 주석을 보거나 다른 사람에게 전달하려면 내보낸 PDF를 사용합니다.
- 자동저장 ON이면 창을 닫을 때 남은 변경도 저장합니다. 실행 취소/다시 실행도 저장 대상입니다.
  자동저장 뒤 창을 닫는 것은 변경을 취소하는 동작이 아닙니다.

## 실패·동시 사용·보호 문서

- 원본 해시가 달라지거나 주석 파일이 손상되면 별도 주석을 덮어쓰지 않고 보기 모드로 엽니다.
- 다른 창이 먼저 주석을 저장했다면 덮어쓰지 않습니다. 현재 변경은 창에 남기며,
  다른 이름의 주석 포함 PDF로 내보내서 두 버전을 보존할 수 있습니다.
- 디스크 부족·권한 오류 때는 저장 완료로 표시하지 않습니다. 닫기를 취소하고 재시도하거나
  다른 폴더로 PDF를 내보낼 수 있습니다. 내보내기 자체가 주석 파일의 저장 실패를 해소하지는 않습니다.
- 저장 중에는 짧게 `.spdf-annotations.json.lock` 파일을 사용합니다. 비정상 종료로 남았으면
  관련 창이 모두 종료되어 저장 작업이 없음을 확인한 뒤 해당 잠금 파일만 제거할 수 있습니다.
- 암호화 PDF는 주석을 평문으로 유출하지 않도록 별도 주석 모드를 허용하지 않습니다.
  PDF 자체의 주석 권한도 존중합니다. 문서 보기는 기존 암호 입력 방식으로 가능합니다.
- 주석 파일은 최대 16 MiB이며 저장 중 임시 파일을 완성한 뒤 교체합니다.
- 이 기능은 편집 기능 선택 옵션이며 DRM이 아닙니다. 텍스트 복사와 인쇄는 유지합니다.

## GUI 없는 모델 사용

```python
from pdfeditor.core import Document

doc = Document(pdf_path, read_only=True, annotations_enabled=True)
try:
    if doc.annotation_error:
        raise RuntimeError(doc.annotation_error)
    doc.add_note(0, 72, 72, "검토 메모")  # 페이지 인덱스는 0부터
    doc.save_annotations()               # 모델에는 자동저장 타이머가 없음
    doc.export_annotated_pdf(output_path) # 원본과 다른 경로
finally:
    doc.close()
```

모델 API의 본문 변경·원본 저장·외부 스냅샷 복원은 `PermissionError`로 차단합니다.
GUI를 우회해 모델을 직접 변경했다면 호출자가 저장과 오류 처리를 담당해야 합니다.
