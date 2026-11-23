"""Offscreen Qt widget cases for the gui reading/steering shell.

Run as a plain script (never collected by pytest) with QT_QPA_PLATFORM=offscreen;
tests/test_qt_cases.py launches this file in an isolated subprocess so widget
coverage actually executes instead of being skipped. Every case is a function
that raises on failure; any failing case (or missing PySide6) exits nonzero.
"""

import os
import sys
import tempfile
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PySide6  # noqa: F401
except ImportError as _e:
    print("Qt widget cases require PySide6; provision it with: "
          "uv run --with pytest --with httpx --with 'pyside6>=6.12.0,<6.13' pytest -q tests "
          f"({type(_e).__name__}: {_e})", file=sys.stderr)
    sys.exit(2)

from PySide6.QtWidgets import QApplication  # noqa: E402

_APP = None


def app():
    """One QApplication shared by all cases (Qt allows only one per process)."""
    global _APP
    if _APP is None:
        _APP = QApplication([])
    return _APP


# ---------------------------------------------------------------- builders

import reader_support as rs  # noqa: E402  (shared synthetic project builders)


def _build_project(root, **kw):
    return rs.build_project(root, **kw)


# ------------------------------------------------------------------- cases

def case_owner_flow_reading(root):
    """Owner journey, reading half: one window, inactive node + notes readable."""
    import longform_core.gui_window as gw
    a = app()
    project = _build_project(root / "p", scenes=[
        _scene("s001", chapter=1, title="Opening"),
        _scene("s002", chapter=1, title="Next"),
    ], trees={
        "s001": _tree({"n1": _node("n1", None, "Active prose."),
                       "n2": _node("n2", "n1", "Inactive branch prose.")},
                      head="n1"),
        "s002": _tree({"n1": _node("n1", None, "Scene two.")}, head="n1"),
    }, bible="# Bible\n\n- Mira: tower", state="state line")
    win = gw.MainWindow(str(project))
    win.show()
    assert [w for w in a.topLevelWidgets() if isinstance(w, gw.MainWindow)] == [win]

    win.select_item("manuscript", "s001", None)
    assert "Active prose." in win.reading.toPlainText()

    win.select_item("node", "s001", "n2")
    assert "Inactive branch prose." in win.reading.toPlainText()
    assert win.reading.isReadOnly()
    assert "n2" in win.metadata.toPlainText()

    win.tabs.setCurrentIndex(gw.NOTES)
    win.select_note("bible")
    assert "Mira: tower" in win.notes_view.toPlainText()
    win.select_note("state")
    assert "state line" in win.notes_view.toPlainText()
    win.close()


def case_owner_flow_steering(root):
    """Owner journey, steering half: multiline Save persists; reopen sees it."""
    import longform_core.gui_window as gw
    app()
    project = _build_project(root / "p", scenes=[_scene("s001")], trees={
        "s001": _tree({"n1": _node("n1", None, "Active prose.")}, head="n1"),
    }, bible="B")
    win = gw.MainWindow(str(project))
    win.show()
    win.select_item("manuscript", "s001", None)
    win.steer_editor.setPlainText("Keep it slow.\nMention the tower.")
    assert win.dirty()
    win.save_btn.click()
    assert "saved" in win.status.text().lower()
    assert not win.dirty()

    after = json.loads((project / "trees" / "s001.json").read_text())
    assert after["head"] == "n1"
    assert set(after["nodes"]) == {"n1"}
    assert after["counter"] == 1
    assert after["steer"] == "Keep it slow.\nMention the tower."

    win.close()
    win2 = gw.MainWindow(str(project))
    assert win2.steer_editor.toPlainText() == "Keep it slow.\nMention the tower."
    win2.close()


CASES = {
    "owner_flow_reading": case_owner_flow_reading,
    "owner_flow_steering": case_owner_flow_steering,
}


def main(argv):
    names = argv[1:] or list(CASES)
    unknown = [n for n in names if n not in CASES]
    if unknown:
        print(f"unknown Qt widget case(s): {', '.join(unknown)}", file=sys.stderr)
        return 2
    failures = []
    for name in names:
        try:
            with tempfile.TemporaryDirectory() as td:
                CASES[name](Path(td))
            print(f"ok  {name}")
        except Exception:
            print(f"FAIL {name}")
            traceback.print_exc()
            failures.append(name)
    if failures:
        print(f"{len(failures)} Qt widget case(s) failed: {', '.join(failures)}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
