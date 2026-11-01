"""콘솔 표시 실행 — 개발/디버그용. 평소 사용은 run.pyw."""
from pdfeditor.dev_startup import ensure_project_environment

ensure_project_environment(__file__)

from pdfeditor.__main__ import main

main()
