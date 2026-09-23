"""OCR — 서브프로세스 실행 + UI 믹스인(설계 §3.3).

왜 서브프로세스인가: PyQt5가 로드된 프로세스에서 onnxruntime를 import하면
Windows에서 DLL 초기화가 실패한다(스레드로도 못 피함 — 같은 프로세스라서).
그래서 실제 인식은 ocr_subprocess.py를 자식 프로세스로 띄워 처리하고,
부모(이 모듈)는 그 stdout에서 결과 JSON만 읽는다. 부모 프로세스는
onnxruntime를 절대 import하지 않는다.

엔진 확장(PaddleOCR-VL, Claude API): ocr_subprocess.py 안에서 엔진을
바꾸면 되고, 부모/UI는 손댈 필요 없다.
"""

import importlib.util
import json
import os
import subprocess
import sys

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import QMessageBox, QProgressDialog
from .access import editing_command

# 렌더 배율은 자식 프로세스가 페이지 크기에 맞춰 자동 결정한다
# (ocr_subprocess.TARGET_LONG_PX 참고). None이면 자동.
OCR_ZOOM = None


def ocr_installed():
    """OCR을 쓸 수 있는지 확인.

    - 프로즌(설치본): GUI EXE는 rapidocr/onnxruntime를 일부러 뺐으므로
      find_spec으로는 항상 False가 나온다. 실제 판단 기준은 별도 워커 EXE의
      존재 여부다(ocr_command()가 가리키는 경로).
    - 개발: 부모에서 onnxruntime를 import하면 Qt와 DLL 충돌이 나므로
      import 대신 find_spec으로 설치 여부만 본다.
    """
    from .paths import is_frozen, ocr_command
    if is_frozen():
        return os.path.exists(ocr_command()[0])
    try:
        return bool(importlib.util.find_spec("rapidocr")
                    and importlib.util.find_spec("onnxruntime"))
    except (ImportError, ValueError):
        return False


class OcrWorker(QThread):
    """자식 프로세스를 띄우고 결과 스트림을 읽어 시그널로 중계.

    이 스레드는 파이프 읽기만 한다(네이티브 OCR 코드는 자식 프로세스에서
    돈다) — Qt 스레드에서 onnxruntime를 만지지 않으므로 안전하다.
    """

    progress = pyqtSignal(int, int)      # 완료 수, 전체 수
    page_done = pyqtSignal(int, list)    # 페이지 번호, items(PDF 좌표)
    failed = pyqtSignal(str)

    def __init__(self, path, password, pages, engine="rapidocr", parent=None):
        super().__init__(parent)
        self._path = path
        self._password = password
        self._pages = pages
        self._engine = engine
        self._proc = None
        self._cancel = False

    def cancel(self):
        self._cancel = True
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except OSError:
                pass

    def kill_process(self):
        """정상 종료를 기다려도 남은 OCR 자식 프로세스를 강제로 정리한다."""
        self._cancel = True
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.kill()
            except OSError:
                pass

    def run(self):
        from .paths import is_frozen, ocr_command, resource, user_data_dir
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        # 프로즌 EXE만 모델 저장 위치를 사용자 폴더로 돌린다 — 임시 추출
        # 폴더는 읽기 전용/휘발성이라 거기 받으면 매번 다시 받게 된다.
        # 개발 환경은 site-packages 기본 경로가 이미 잘 동작하므로 안 건드림.
        cwd = None
        if is_frozen():
            env["RAPIDOCR_MODEL_DIR"] = os.path.join(user_data_dir(), "models")
        else:
            # 개발 실행: 워커를 `python -m pdfeditor.ocr_subprocess`로 띄운다.
            # -m은 CWD를 sys.path에 얹어 패키지를 찾는데, 앱이 리포 밖에서
            # 실행되면(PDF 더블클릭·바탕화면 등) CWD가 리포가 아니라
            # ModuleNotFoundError로 워커가 조용히 죽는다(stderr=DEVNULL이라
            # 부모는 눈치도 못 챈다 → "OCR이 아무 반응 없음"). 리포 루트를
            # CWD로 고정하고 PYTHONPATH에도 넣어 실행 위치와 무관하게 한다.
            repo_root = resource()
            cwd = repo_root
            old = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = (repo_root + os.pathsep + old) if old \
                else repo_root
        # 자식 stderr을 임시 파일로 받는다 — 워커가 결과 한 줄 못 내고
        # 죽으면(import 실패 등) 그 이유를 사용자에게 보여주기 위함.
        # 예전엔 DEVNULL로 버려 "아무 반응 없음"이 됐다.
        import tempfile
        errf = tempfile.TemporaryFile(mode="w+", encoding="utf-8",
                                      errors="replace")
        try:
            self._proc = subprocess.Popen(
                ocr_command(),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=errf, text=True, encoding="utf-8",
                env=env, cwd=cwd,
                # 콘솔 창이 잠깐 뜨지 않도록(pythonw/EXE 실행 시)
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as e:
            errf.close()
            self.failed.emit("OCR 프로세스를 시작할 수 없습니다: %s" % e)
            return

        job = {"path": self._path, "password": self._password,
               "pages": self._pages, "zoom": OCR_ZOOM, "engine": self._engine}
        got_result = False   # page/error 메시지를 하나라도 받았나
        clean_done = False    # 워커가 정상 종료(done) 신호를 줬나
        try:
            self._proc.stdin.write(json.dumps(job) + "\n")
            self._proc.stdin.flush()
            self._proc.stdin.close()
            for line in self._proc.stdout:
                if self._cancel:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue  # 자식이 찍은 로그 등 비-JSON 줄은 무시
                t = msg.get("type")
                if t == "page":
                    got_result = True
                    self.page_done.emit(msg["page"], msg["items"])
                elif t == "progress":
                    self.progress.emit(msg["done"], msg["total"])
                elif t == "error":
                    got_result = True
                    self.failed.emit(msg["message"])
                elif t == "done":
                    clean_done = True
                    break
        finally:
            if self._proc.poll() is None:
                self._proc.terminate()
            self._proc.wait()
            # 결과도 정상종료 신호도 없이 끝났다 = 워커가 뻗었다.
            # stderr 꼬리를 붙여 원인을 알린다(취소한 경우는 제외).
            if not got_result and not clean_done and not self._cancel:
                try:
                    errf.seek(0)
                    tail = "".join(errf.readlines()[-12:]).strip()
                except Exception:
                    tail = ""
                hint = ("OCR 작업 프로세스가 시작하자마자 종료되었습니다"
                        "(종료 코드 %s)." % self._proc.returncode)
                self.failed.emit(hint + ("\n\n%s" % tail if tail else ""))
            errf.close()
class OcrMixin:
    def _init_ocr_state(self):
        self._ocr_worker = None
        self._ocr_added = 0
        self._closing_doc = False

    def _ocr_available(self):
        if not ocr_installed():
            from .paths import is_frozen
            if is_frozen():
                # 설치본인데 워커가 없다 = 설치가 깨졌다. pip 안내는 무의미.
                msg = ("OCR 구성요소를 찾을 수 없습니다.\n\n"
                       "설치가 손상되었을 수 있습니다. Leaflet을 다시 설치해 "
                       "주세요.")
            else:
                msg = ("OCR 엔진이 설치되어 있지 않습니다.\n\n"
                       "명령 프롬프트에서 설치 후 다시 실행하세요:\n"
                       "pip install rapidocr onnxruntime")
            QMessageBox.information(self, "OCR 사용 불가", msg)
            return False
        return True

    @editing_command
    def ocr_current_page(self):
        if self.doc is None or not self._ocr_available():
            return
        # 이미 텍스트가 있는 페이지에 OCR하면 글자가 이중으로 들어가
        # 검색·복사 결과가 겹친다 — 먼저 물어본다(논문/출판물은 대개
        # 텍스트 레이어가 이미 있다).
        if self.doc.has_text(self.page_index):
            ret = QMessageBox.question(
                self, "이미 텍스트가 있음",
                "이 페이지에는 이미 텍스트 레이어가 있습니다.\n"
                "OCR을 실행하면 글자가 중복될 수 있습니다.\n\n"
                "그래도 진행할까요?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes:
                return
        self._start_ocr([self.page_index])

    @editing_command
    def ocr_document(self):
        """전체 문서 — 이미 텍스트가 있는 페이지는 건너뛴다(이중 삽입 방지)."""
        if self.doc is None or not self._ocr_available():
            return
        pages = [p for p in range(self.doc.page_count) if not self.doc.has_text(p)]
        if not pages:
            QMessageBox.information(
                self, "OCR", "모든 페이지에 이미 텍스트 레이어가 있습니다.")
            return
        self._start_ocr(pages)

    @editing_command
    def _start_ocr(self, pages):
        if self._ocr_worker is not None:
            return  # 이미 진행 중
        self._ocr_added = 0

        from . import settings, vl
        engine = settings.ocr_engine()
        # VL을 골라뒀어도 모델이 아직 없으면 OCR이 먹통이 되지 않게 기본
        # 엔진으로 실제 실행한다(선택 자체는 유지 — 모델 붙으면 자동 반영).
        if engine == "vl" and not vl.vl_installed():
            engine = "rapidocr"

        label = ("AI 고품질(VL) OCR 인식 중...\n"
                 "(첫 페이지는 모델 로드로 수십 초 걸릴 수 있습니다)"
                 if engine == "vl" else
                 "OCR 인식 중... (첫 페이지는 인식 엔진 준비로 몇 초 걸릴 수 있습니다)")
        dlg = QProgressDialog(label, "취소", 0, len(pages), self)
        dlg.setWindowTitle("OCR")
        dlg.setMinimumDuration(0)
        dlg.setValue(0)
        self._ocr_dlg = dlg
        w = OcrWorker(self.doc.path, self.doc._password, pages,
                      engine=engine, parent=self)
        self._ocr_worker = w
        w.page_done.connect(self._on_ocr_page)
        w.progress.connect(lambda done, total: dlg.setValue(done))
        w.failed.connect(self._on_ocr_failed)
        w.finished.connect(self._on_ocr_finished)
        dlg.canceled.connect(w.cancel)
        w.start()

    @editing_command
    def _on_ocr_page(self, page, items):
        if self._closing_doc or self.doc is None:
            return  # OCR 도중 문서를 닫은 경우
        # 자식은 [x0,y0,x1,y1,text] 리스트로 보낸다 → 코어가 기대하는 튜플로.
        tuples = [(it[0], it[1], it[2], it[3], it[4]) for it in items]
        n = self.doc.insert_ocr_text(page, tuples)
        if n:
            self._ocr_added += n
            self._words_cache.pop(page, None)  # 새 텍스트 레이어 반영
            self.mark_dirty()

    def _on_ocr_failed(self, msg):
        if self._closing_doc:
            return
        QMessageBox.critical(self, "OCR 실패", "OCR 중 오류가 발생했습니다.\n\n%s" % msg)

    def _on_ocr_finished(self):
        self._ocr_worker = None
        self._ocr_dlg.close()
        if self._closing_doc:
            return
        if self._ocr_added:
            self.refresh_page(self.page_index)  # 현재 페이지 검색 오버레이 갱신용
            self.statusBar().showMessage(
                "OCR 완료 — %d개 텍스트 블록 인식 (저장해야 파일에 반영됩니다)"
                % self._ocr_added, 8000)
        else:
            self.statusBar().showMessage("OCR 완료 — 인식된 텍스트가 없습니다", 5000)
