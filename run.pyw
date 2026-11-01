"""콘솔 없이 새 개발 프로세스 실행 — 기존 트레이 연결·상주 제외."""
from pdfeditor.dev_startup import ensure_project_environment

ensure_project_environment(__file__, windowless=True)

from pdfeditor.__main__ import main

main(allow_residency=False)
