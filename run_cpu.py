"""CPU 렌더링으로 새 읽기 창 실행 — 저장된 렌더러 설정은 유지한다."""
from pdfeditor.dev_startup import ensure_project_environment

ensure_project_environment(__file__)

import os
import sys

os.environ["LEAFLET_RENDER_BACKEND"] = "cpu"
if not any(arg == "--workspace" or arg.startswith("--workspace=") for arg in sys.argv[1:]):
    sys.argv.extend(["--workspace", "reader"])

from pdfeditor.__main__ import main

main(allow_residency=False)
