"""Run the test suite with Windows Qt GUI cases isolated by process."""

import ast
import os
from pathlib import Path
import subprocess
import sys
import unittest


if os.name == "nt":
    import ctypes
    # Affect this test process and its children only. Native failures still
    # return a failing exit code and faulthandler trace, without a blocking
    # Windows application-error dialog on the user's desktop.
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    os.environ.setdefault("PYTHONFAULTHANDLER", "1")


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
TESTS = ROOT / "tests"
DOCUMENT_WORKFLOW = TESTS / "test_document_workflow.py"


def _run(test_name):
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, (str(TESTS), env.get("PYTHONPATH", ""))))
    print("\n=== %s ===" % test_name, flush=True)
    return subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--single", test_name],
        cwd=ROOT,
        env=env,
        check=False,
    ).returncode


def _run_single(test_name):
    """Return the unittest result without running unstable Qt DLL teardown."""
    suite = unittest.defaultTestLoader.loadTestsFromName(test_name)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if result.wasSuccessful() else 1)


def _document_window_tests():
    tree = ast.parse(DOCUMENT_WORKFLOW.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "DocumentWorkflowTests":
            return sorted(
                child.name for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and child.name.startswith("test_"))
    raise RuntimeError("DocumentWorkflowTests was not found")


def main():
    test_names = []
    for path in sorted(TESTS.glob("test_*.py")):
        if path == DOCUMENT_WORKFLOW:
            test_names.extend(
                "test_document_workflow.DocumentWorkflowTests.%s" % method
                for method in _document_window_tests())
            test_names.append("test_document_workflow.RecoveryStoreTests")
        else:
            test_names.append(path.stem)

    for test_name in test_names:
        if _run(test_name):
            return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--single":
        _run_single(sys.argv[2])
    raise SystemExit(main())
