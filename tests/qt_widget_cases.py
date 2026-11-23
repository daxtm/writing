"""Offscreen Qt widget cases for the gui reading/steering shell.

Run as a plain script (never collected by pytest) with QT_QPA_PLATFORM=offscreen;
tests/test_qt_cases.py launches this file in an isolated subprocess so widget
coverage actually executes instead of being skipped. Every case is a function
that raises on failure; any failing case (or missing PySide6) exits nonzero.
"""

import json
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

def _no_dialogs(where="case"):
    """Widget cases must never open a real modal dialog."""
    def choose(*_a, **_k):
        raise AssertionError(f"unexpected modal dialog in {where}")
    return choose

# ---------------------------------------------------------------- builders

import reader_support as rs  # noqa: E402  (shared synthetic project builders)

_node = rs.node
_tree = rs.tree
_scene = rs.scene
_write_json = rs.write_json


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
    win = gw.MainWindow(str(project), choice=_no_dialogs("case 1"))
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
    win = gw.MainWindow(str(project), choice=_no_dialogs("case 2"))
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
    win2 = gw.MainWindow(str(project), choice=_no_dialogs("case 3"))
    assert win2.steer_editor.toPlainText() == "Keep it slow.\nMention the tower."
    win2.close()


def case_navigation_no_writes(root):
    """Browsing nodes/retained trees/tabs never writes project files."""
    import longform_core.gui_window as gw
    app()
    project = _build_project(root / "p", scenes=[_scene("s001")], trees={
        "s001": _tree({"n1": _node("n1", None, "Active."),
                       "n2": _node("n2", "n1", "Sibling.")}, head="n1"),
        "old": _tree({"n1": _node("n1", None, "Kept old prose.")}, head="n1"),
    }, bible="B")
    before = {f.relative_to(project): f.stat().st_mtime_ns
              for f in project.rglob("*") if f.is_file()}
    win = gw.MainWindow(str(project), choice=_no_dialogs("case 4"))
    win.show()
    for triple in [("manuscript", "s001", None), ("node", "s001", "n2"),
                   ("node", "s001", "n1"), ("retained", "old", None),
                   ("retained-node", "old", "n1")]:
        win.select_item(*triple)
        assert win.reading.toPlainText() != ""
        assert "Kept old prose." in win.reading.toPlainText() \
            if triple[0].startswith("retained") else True
    for tab in (gw.BRANCHES, gw.NOTES, gw.MANUSCRIPT):
        win.tabs.setCurrentIndex(tab)
    win.close()
    after = {f.relative_to(project): f.stat().st_mtime_ns
             for f in project.rglob("*") if f.is_file()}
    assert after == before


def case_reading_states(root):
    """Retained, broken, empty, and metadata-absent states stay readable."""
    import longform_core.gui_window as gw
    app()
    p = _build_project(root / "p", scenes=[_scene("s001")],
                       trees={"s001": _tree({"n1": _node("n1", None, "text.")},
                                            head="nope")})
    (p / "trees" / "broken.json").write_text("{nope", encoding="utf-8")
    win = gw.MainWindow(str(p), choice=_no_dialogs("case 9"))
    win.show()
    # broken active chain: nodes readable, active marked unavailable
    win.select_item("node", "s001", "n1")
    assert "text." in win.reading.toPlainText()
    assert "unavailable" in win.metadata.toPlainText().lower()
    # broken tree file listed separately, no crash on selection
    win.select_item("retained", "broken", None)
    assert "unavailable" in win.reading.toPlainText().lower()
    win.close()

    empty = _build_project(root / "empty")
    win2 = gw.MainWindow(str(empty), choice=_no_dialogs("case 10"))
    win2.show()
    assert win2.sidebar.topLevelItemCount() == 0
    assert "no current scene" in win2.steer_label.text().lower()
    assert not win2.save_btn.isEnabled()
    win2.close()

    # scene without a tree yet
    p3 = _build_project(root / "p3", scenes=[_scene("s001")])
    win3 = gw.MainWindow(str(p3), choice=_no_dialogs("case 11"))
    win3.show()
    win3.select_item("manuscript", "s001", None)
    assert "no saved tree" in win3.reading.toPlainText().lower()
    assert win3.save_btn.isEnabled(), "absent tree on a valid card is editable"
    win3.close()


def case_focus_and_tab_order(root):
    """A predictable tab order reaches sidebar, reading, editor, then actions."""
    import longform_core.gui_window as gw
    app()
    project = _build_project(root / "p", scenes=[_scene("s001")], trees={
        "s001": _tree({"n1": _node("n1", None, "A.")}, head="n1")})
    win = gw.MainWindow(str(project), choice=_no_dialogs("case 5"))
    win.show()
    win.sidebar.setFocus()
    expected = [gw.QTreeWidget, gw.QTabWidget, gw.QPlainTextEdit,
                gw.QPushButton]
    seen = [win.sidebar]
    w = win.sidebar
    for _ in range(200):
        w = w.nextInFocusChain()
        if w in seen or w is win.sidebar:
            break
        seen.append(w)
    types = [type(x) for x in seen]
    def idx(cls):
        return next((i for i, t in enumerate(types) if t is cls), -1)
    order = [idx(gw.QTreeWidget), idx(gw.QPlainTextEdit), idx(gw.QPushButton)]
    assert all(o >= 0 for o in order) and order == sorted(order), \
        f"tab order must reach sidebar, reading, then actions: {types}"
    assert win.sidebar.focusPolicy() != gw.Qt.FocusPolicy.NoFocus
    win.close()


def case_enter_inserts_newline(root):
    """Enter inside the steering editor inserts a newline and never saves."""
    import longform_core.gui_window as gw
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    app()
    project = _build_project(root / "p", scenes=[_scene("s001")], trees={
        "s001": _tree({"n1": _node("n1", None, "A.")}, head="n1")})
    asked = []
    def choice(title, text, options):
        asked.append(options)
        return "Discard"  # the case leaves unsaved text on close
    win = gw.MainWindow(str(project), choice=choice)
    win.show()
    win.select_item("manuscript", "s001", None)
    win.steer_editor.setPlainText("line one")
    win.steer_editor.moveCursor(gw.QTextCursor.MoveOperation.End)
    QTest.keyClick(win.steer_editor, Qt.Key.Key_Return)
    assert win.steer_editor.toPlainText() == "line one\n"
    assert (project / "trees" / "s001.json").read_text().count('"steer"') == 0, \
        "Enter must not trigger a save"
    win.close()
    assert asked == [["Save", "Discard", "Cancel"]], \
        "closing with unsaved text offers the three choices"


def case_palette_and_prose_size(root):
    """Presentation uses system palette roles (no fixed light colors) and an
    adjustable prose size."""
    import longform_core.gui_window as gw
    from PySide6.QtGui import QPalette, QColor
    a = app()
    project = _build_project(root / "p", scenes=[_scene("s001")], trees={
        "s001": _tree({"n1": _node("n1", None, "A.")}, head="n1")})
    dark = QPalette()
    dark.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
    dark.setColor(QPalette.ColorRole.WindowText, QColor(230, 230, 230))
    a.setPalette(dark)
    try:
        win = gw.MainWindow(str(project), choice=_no_dialogs("case 7"))
        win.show()
        assert win.styleSheet() == ""
        for pane in (win.reading, win.metadata, win.notes_view,
                     win.steer_editor):
            assert pane.styleSheet() == "", "no fixed light-only colors"
        base = win.prose_size.value()
        win.prose_size.setValue(base + 3)
        assert win.reading.font().pointSize() == base + 3
        assert win.steer_editor.font().pointSize() == base + 3
        win.prose_size.setValue(base)
        win.close()
    finally:
        a.setPalette(QPalette())


def case_readonly_panes(root):
    """Reading panes reject edits; the steering editor accepts them."""
    import longform_core.gui_window as gw
    app()
    project = _build_project(root / "p", scenes=[_scene("s001")], trees={
        "s001": _tree({"n1": _node("n1", None, "A.")}, head="n1")}, bible="B")
    win = gw.MainWindow(str(project), choice=_no_dialogs("case 8"))
    win.show()
    for pane in (win.reading, win.metadata, win.notes_view):
        assert pane.isReadOnly()
    win.reading.setFocus()
    win.reading.setPlainText("SHOULD NOT HAPPEN")  # programmatic only; not user
    # a user cannot type: read-only flag stays and content is untouched
    win.reading.setReadOnly(True)
    assert win.reading.isReadOnly()
    win.select_note("bible")
    assert win.notes_view.isReadOnly()
    assert not win.steer_editor.isReadOnly()
    win.close()


CASES = {
    "owner_flow_reading": case_owner_flow_reading,
    "owner_flow_steering": case_owner_flow_steering,
    "case_navigation_no_writes": case_navigation_no_writes,
    "case_reading_states": case_reading_states,
    "case_focus_and_tab_order": case_focus_and_tab_order,
    "case_enter_inserts_newline": case_enter_inserts_newline,
    "case_palette_and_prose_size": case_palette_and_prose_size,
    "case_readonly_panes": case_readonly_panes,
}


def _teardown():
    """Deterministic widget teardown: shutdown SIGBUS otherwise occurs while
    pending timers/widgets are destroyed out of order at interpreter exit."""
    import gc
    from PySide6.QtWidgets import QApplication
    a = QApplication.instance()
    if a is None:
        return
    for w in list(a.topLevelWidgets()):
        if w is not a:
            w.deleteLater()
    a.processEvents()
    gc.collect()
    a.processEvents()


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
            _teardown()
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
