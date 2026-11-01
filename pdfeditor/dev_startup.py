"""Select the repository's build environment before importing GUI/native code."""
import os
from pathlib import Path
import subprocess
import sys


def ensure_project_environment(entry_script, *, windowless=False):
    """Replace a system-Python development launch with the project interpreter.

    Explorer's .pyw association can use a different Python/PyMuPDF from the one
    used to build the native SDK bridge. Packaged applications keep their own
    runtime. A source checkout without a local venv keeps the explicit caller's
    environment, whose native bridge must be built against that same SDK.
    """
    if getattr(sys, 'frozen', False):
        return
    root = Path(__file__).resolve().parents[1]
    environment = root / '.venv'
    if Path(sys.prefix).resolve() == environment.resolve():
        return
    executable = environment / 'Scripts' / ('pythonw.exe' if windowless else 'python.exe')
    if not (environment / 'pyvenv.cfg').is_file() or not executable.is_file():
        return
    child_environment = os.environ.copy()
    # Do not carry a different interpreter's prefix/import paths into the venv.
    for name in ('PYTHONHOME', 'PYTHONPATH', '__PYVENV_LAUNCHER__'):
        child_environment.pop(name, None)
    child_environment['VIRTUAL_ENV'] = str(environment)
    command = [str(executable), '-E', '-s', str(Path(entry_script).resolve()), *sys.argv[1:]]
    # Windows execve/CRT overlay is unreliable for Unicode paths. Spawn through
    # CreateProcessW and exit this lightweight bootstrap, rather than leaving a
    # second system-Python interpreter waiting alongside the GUI.
    subprocess.Popen(command, env=child_environment,
                     creationflags=(getattr(subprocess, 'CREATE_NO_WINDOW', 0) if windowless else 0))
    raise SystemExit(0)
