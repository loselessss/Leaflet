import sys


def main():
    if "--gpu-scene-worker" in sys.argv:
        from .gpu_scene_worker import main as gpu_scene_main
        index = sys.argv.index("--gpu-scene-worker")
        sys.exit(gpu_scene_main(sys.argv[index + 1:]))

    # GUI와 OCR 작업 프로세스가 Windows에서 같은 Leaflet 앱으로 인식되도록
    # 어떤 실행 모드에서도 UI/작업 초기화보다 먼저 명시한다.
    from .windows_integration import set_current_process_app_id
    set_current_process_app_id()

    # OCR은 별도 실행 파일(spdf-ocr.exe)이 처리한다 — 같은 프로세스에서
    # Qt와 onnxruntime를 함께 로드하면 DLL 초기화가 깨지기 때문(paths.py).
    # 개발 모드에서 `--ocr-worker`로 직접 호출하는 경우만 지원(테스트용).
    if "--ocr-worker" in sys.argv:
        from .ocr_subprocess import main as ocr_main
        sys.exit(ocr_main())

    import argparse
    from . import settings
    parser = argparse.ArgumentParser(prog="Leaflet")
    parser.add_argument("path", nargs="?")
    parser.add_argument("--workspace", choices=("reader", "editor"))
    parser.add_argument("--peer")
    parser.add_argument("--peer-token")
    parser.add_argument("--peer-request")
    parser.add_argument("--no-updates", action="store_true")
    args = parser.parse_args()
    from .paths import is_packaged
    # MSIX updates are installed through the package channel, not Inno Setup.
    args.no_updates = args.no_updates or is_packaged()
    workspace = args.workspace or settings.startup_workspace()

    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QIcon
    from PyQt5.QtWidgets import QApplication

    from .meta import APP_NAME, APP_VERSION
    from .paths import app_icon
    from .theme import apply_fluent_theme

    # Windows의 모든 Qt 대화상자 제목 표시줄에 자동으로 붙는 `?`
    # 컨텍스트 도움말 버튼을 앱 전체에서 제거한다.
    QApplication.setAttribute(Qt.AA_DisableWindowContextHelpButton, True)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    # Preserve Windows fractional scales (125%, 150%, 175%) instead of
    # rounding them to an integer device pixel ratio.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    # Reader tabs can move between top-level windows without recreating GL
    # contexts. Embedded hosts retain full control of their own QApplication.
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    app = QApplication(sys.argv)
    app._spdf_standalone_reader = workspace == "reader"
    # Forward ordinary file launches before importing the document/editor UI.
    # Peer handoffs retain their authenticated, acknowledged process channel.
    if workspace == "reader" and not args.peer and settings.reader_resident():
        from .reader_resident import forward_to_resident
        if forward_to_resident(args.path):
            return
    from .app import new_window
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_NAME)
    from .i18n import install as install_i18n
    install_i18n(app)
    apply_fluent_theme(app)
    from .recovery_ui import application_recovery_store
    try:
        application_recovery_store()
    except OSError:
        from PyQt5.QtWidgets import QMessageBox
        from .i18n import localize
        QMessageBox.warning(None, APP_NAME, localize(
            "The recovery folder is not writable. Save your work manually.",
            "복구 폴더에 쓸 수 없습니다. 작업을 직접 저장하세요."))
    import os
    icon = app_icon()
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))

    # 공식 실행 진입점에서만 자체 업데이트를 켠다. 다른 프로그램이
    # pdfeditor를 내부 모듈로 불러 new_window/AppWindow를 만들면 기본값은 꺼짐이다.
    new_window(args.path, updates_enabled=not args.no_updates,
               workspace_mode=workspace)
    if workspace == "reader" and settings.reader_resident():
        from .reader_resident import configure_residency
        configure_residency(True, updates_enabled=not args.no_updates)
    from .process_workspace import application_bridge
    bridge = application_bridge()
    if args.peer and args.peer_token:
        bridge.connect_parent(args.peer, args.peer_token, args.peer_request)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
