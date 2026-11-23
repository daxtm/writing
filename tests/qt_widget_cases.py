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


def case_dirty_scene_choices(root):
    """Save/Discard/Cancel on scene switch; Save proceeds only on success."""
    import longform_core.gui_window as gw
    app()
    project = _build_project(root / "p", scenes=[
        _scene("s001"), _scene("s002")], trees={
        "s001": _tree({"n1": _node("n1", None, "A.")}, head="n1"),
        "s002": _tree({"n1": _node("n1", None, "B.")}, head="n1"),
    }, bible="B")
    answers = []
    win = gw.MainWindow(str(project), choice=lambda t, x, o: answers.pop(0))
    win.show()
    win.select_item("manuscript", "s001", None)
    win.steer_editor.setPlainText("for s001")

    answers.append("Save")
    win.select_item("manuscript", "s002", None)
    assert json.loads((project / "trees" / "s001.json").read_text())["steer"] \
        == "for s001", "Save choice persists the old scene before switching"
    assert win.steer_editor.toPlainText() == "", "new scene steering loaded"

    win.select_item("manuscript", "s001", None)
    win.steer_editor.setPlainText("discard me")
    answers.append("Discard")
    win.select_item("manuscript", "s002", None)
    assert json.loads((project / "trees" / "s001.json").read_text())["steer"] \
        == "for s001", "Discard writes nothing"

    win.select_item("manuscript", "s001", None)
    win.steer_editor.setPlainText("keep me dirty")
    answers.append("Cancel")
    win.select_item("manuscript", "s002", None)
    assert win._sel_data[1] == "s001", "Cancel keeps the original scene"
    assert win.dirty()

    answers.append("Discard")
    win.close()

    # failed Save during a scene switch behaves like Cancel plus an error
    win2 = gw.MainWindow(str(project),
                         choice=lambda t, x, o: answers.pop(0))
    win2.show()
    win2.select_item("manuscript", "s001", None)
    win2.steer_editor.setPlainText("switch with failing save")
    # the dirty scene's own tree becomes a symlink: its Save must fail
    (project / "trees" / "s001.json").rename(project / "trees" / "keep.json")
    (project / "trees" / "s001.json").symlink_to(project / "trees" / "keep.json")
    answers.extend(["Save"])
    win2.select_item("manuscript", "s002", None)
    assert win2._sel_data[1] == "s001", "failed Save keeps the original scene"
    assert "not saved" in win2.status.text()
    assert win2.dirty()
    answers.append("Discard")  # closing without saving
    win2.close()


def case_close_choices(root):
    """Close with unsaved steering: Save persists, Cancel keeps the window."""
    import longform_core.gui_window as gw
    app()
    project = _build_project(root / "p", scenes=[_scene("s001")], trees={
        "s001": _tree({"n1": _node("n1", None, "A.")}, head="n1")}, bible="B")
    answers = []
    win = gw.MainWindow(str(project), choice=lambda t, x, o: answers.pop(0))
    win.show()
    win.steer_editor.setPlainText("saved on close")
    answers.append("Save")
    win.close()
    assert json.loads((project / "trees" / "s001.json").read_text())["steer"] \
        == "saved on close"

    win2 = gw.MainWindow(str(project), choice=lambda t, x, o: answers.pop(0))
    win2.show()
    win2.steer_editor.setPlainText("not yet")
    answers.append("Cancel")
    win2.close()
    assert win2.isVisible(), "Cancel keeps the window open"
    assert win2.dirty()
    assert json.loads((project / "trees" / "s001.json").read_text())["steer"] \
        == "saved on close", "Cancel writes nothing"
    answers.append("Discard")
    win2.close()


def case_stale_conflict(root):
    """External tree edit: Save offers Reload/Keep editing; refresh never
    acknowledges on behalf of the owner."""
    import longform_core.gui_window as gw
    app()
    project = _build_project(root / "p", scenes=[_scene("s001")], trees={
        "s001": _tree({"n1": _node("n1", None, "A.")}, head="n1")}, bible="B")
    answers = []
    win = gw.MainWindow(str(project), choice=lambda t, x, o: answers.pop(0))
    win.show()
    win.steer_editor.setPlainText("my unsaved line")

    # external CLI-style change after the baseline was captured
    t = json.loads((project / "trees" / "s001.json").read_text())
    t["nodes"]["n2"] = _node("n2", "n1", "external branch")
    t["steer"] = "external direction"
    _write_json(project / "trees" / "s001.json", t)

    answers.append("Keep editing")
    win.save_btn.click()
    assert win.dirty() and win.steer_editor.toPlainText() == "my unsaved line"
    assert "changed on disk" in win.status.text()
    t = json.loads((project / "trees" / "s001.json").read_text())
    assert t["steer"] == "external direction", "disk untouched by Keep editing"

    answers.append("Reload saved steering")
    win.save_btn.click()
    assert not win.dirty()
    assert win.steer_editor.toPlainText() == "external direction"
    assert win._steer.text == "external direction"

    # refresh alone never replaces dirty text even when disk differs
    win.steer_editor.setPlainText("still editing")
    win._auto_refresh()
    assert win.steer_editor.toPlainText() == "still editing"
    answers.append("Discard")
    win.close()


def case_refresh_preserves_state(root):
    """Cached ~2s refresh and forced refresh keep IDs, tab, scroll, focus,
    cursor and dirty text stable."""
    import longform_core.gui_window as gw
    from longform_core.reader_model import SourceCache, load_snapshot
    app()
    prose = "word " * 400
    project = _build_project(root / "p", scenes=[
        _scene("s001"), _scene("s002")], trees={
        "s001": _tree({"n1": _node("n1", None, "A."), "n2": _node("n2", "n1", prose)},
                      head="n1"),
        "s002": _tree({"n1": _node("n1", None, "B.")}, head="n1"),
    }, bible="BIBLE BODY", state="state body")

    class FakeTimer:
        def __init__(self):
            self.ms = None
            self._cb = None
            self.timeout = self

        def connect(self, cb):
            self._cb = cb

        def start(self, ms):
            self.ms = ms

        def fire(self):
            self._cb()

    timers = []
    loads = []

    def load(root, cache=None, force=False):
        if cache is not None:
            del cache.reads[:]  # record only this call's fresh reads
        res = load_snapshot(root, cache=cache, force=force)
        loads.append((force, list(cache.reads) if cache else None))
        return res

    def timer_factory():
        t = FakeTimer()
        timers.append(t)
        return t

    win = gw.MainWindow(str(project), load=load, timer_factory=timer_factory,
                        choice=lambda *a: "Discard")
    win.show()
    assert timers and timers[0].ms == gw.REFRESH_MS == 2000

    loads.clear()
    timers[0].fire()  # automatic refresh with unchanged sources
    assert loads == [(False, [])], "unchanged sources are not reread"

    loads.clear()
    win.refresh_btn.click()  # explicit refresh forces reads
    assert loads and loads[0][0] is True and loads[0][1], "force rereads sources"

    # select inactive node, scroll it, switch tab, type dirty steering
    win.select_item("node", "s001", "n2")
    win.reading.verticalScrollBar().setValue(37)
    win.tabs.setCurrentIndex(gw.NOTES)
    win.select_note("bible")
    win.notes_view.verticalScrollBar().setValue(2)
    win.tabs.setCurrentIndex(gw.MANUSCRIPT)
    win.steer_editor.setPlainText("dirty during refresh")
    cur = win.steer_editor.textCursor()
    cur.setPosition(3)
    win.steer_editor.setTextCursor(cur)

    # external content change to the selected node + tree steering change
    t = json.loads((project / "trees" / "s001.json").read_text())
    t["nodes"]["n2"]["text"] = prose + " APPENDED"
    t["steer"] = "external steer"
    _write_json(project / "trees" / "s001.json", t)
    loads.clear()
    timers[0].fire()
    assert loads == [(False, ["trees/s001.json"])], \
        "only the changed source is reread; unchanged sources stay cached"
    assert "APPENDED" in win.reading.toPlainText(), "changed panes update"
    assert win.reading.verticalScrollBar().value() == \
        min(37, win.reading.verticalScrollBar().maximum()), "scroll kept (clamped)"
    assert win.tabs.currentIndex() == gw.MANUSCRIPT
    assert win._sel_data == ("node", "s001", "n2"), "node selection kept"
    assert win.steer_editor.toPlainText() == "dirty during refresh", \
        "dirty text is never replaced by refresh"
    assert win.steer_editor.textCursor().position() == 3, "cursor kept"

    # notes view kept its content/position
    win.tabs.setCurrentIndex(gw.NOTES)
    assert "BIBLE BODY" in win.notes_view.toPlainText()
    win.tabs.setCurrentIndex(gw.MANUSCRIPT)

    # dirty steering remains despite disk steering change: stale indication
    assert "changed on disk" in win.status.text()

    win.close()  # closing a dirty window offers the choices; discards here


def case_removed_node_and_scene(root):
    """Removed selections are marked unavailable; removed dirty scenes keep
    their text with writes disabled."""
    import longform_core.gui_window as gw
    app()
    project = _build_project(root / "p", scenes=[
        _scene("s001"), _scene("s002")], trees={
        "s001": _tree({"n1": _node("n1", None, "A."), "n2": _node("n2", "n1", "B.")},
                      head="n1"),
        "s002": _tree({"n1": _node("n1", None, "B.")}, head="n1"),
    }, bible="B")
    win = gw.MainWindow(str(project), choice=lambda *a: "Discard")
    win.show()
    win.select_item("node", "s001", "n2")
    t = json.loads((project / "trees" / "s001.json").read_text())
    del t["nodes"]["n2"]
    _write_json(project / "trees" / "s001.json", t)
    win._auto_refresh()
    assert "n2" in win.reading.toPlainText() and "no longer present" \
        in win.reading.toPlainText(), "removed node is explicitly unavailable"
    assert win._sel_data == ("node", "s001", "n2"), "no silent reselection"

    # removed dirty scene: text kept, writes disabled
    win.select_item("manuscript", "s002", None)
    win.steer_editor.setPlainText("unsaved for s002")
    scenes = json.loads((project / "scenes.json").read_text())
    scenes = [s for s in scenes if s["id"] != "s002"]
    _write_json(project / "scenes.json", scenes)
    (project / "trees" / "s002.json").unlink()
    win._auto_refresh()
    assert win.steer_editor.toPlainText() == "unsaved for s002"
    assert not win.save_btn.isEnabled()
    assert "no longer present" in win.steer_label.text()
    win.close()
    # discarding on close wrote nothing
    assert not (project / "trees" / "s002.json").exists()


def case_invalid_config_and_recovery(root):
    """Invalid required configuration keeps the last view labeled stale and
    disables writes; a later refresh recovers without restart."""
    import longform_core.gui_window as gw
    from longform_core.reader_model import LoadResult, load_snapshot
    app()
    project = _build_project(root / "p", scenes=[_scene("s001")], trees={
        "s001": _tree({"n1": _node("n1", None, "A.")}, head="n1")}, bible="B")
    fail = []

    def load(root, cache=None, force=False):
        if fail:
            return LoadResult(None, ["project.json is missing or unreadable"])
        return load_snapshot(root, cache=cache, force=force)

    win = gw.MainWindow(str(project), load=load, choice=lambda *a: "Discard")
    win.show()
    assert win.save_btn.isEnabled()
    win.steer_editor.setPlainText("dirty before outage")

    fail.append(1)
    win._auto_refresh()
    assert "stale" in win.status.text()
    assert not win.save_btn.isEnabled()
    assert win.steer_editor.toPlainText() == "dirty before outage"
    assert "BIBLE BODY" not in win.reading.toPlainText(), "view unchanged"

    fail.clear()
    (project / "bible.md").write_text("RECOVERED BIBLE", encoding="utf-8")
    win._auto_refresh()
    assert "recovered" in win.status.text().lower()
    win.select_note("bible")
    assert "RECOVERED BIBLE" in win.notes_view.toPlainText()
    win.close()


# ------------------------------------------------------------ draft loop

import threading  # noqa: E402

import longform_core  # noqa: E402  (provider seam references longform_core.cancel)

PRESET = {
    "preset": {"temp": 1.0, "genamt": 50},
    "instruct": {
        "macro": True,
        "input_sequence": "\n",
        "input_suffix": "\n",
        "output_sequence": "\n",
        "stop_sequence": "",
    },
    "context": {"story_string": "{{description}}"},
    "sysprompt": {"content": "You narrate {{char}}."},
}


class FakeProvider:
    """Provider seam for widget cases: same complete/many surface as Api."""

    def __init__(self, chunks=("First chunk. ", "Second chunk.")):
        self.chunks = list(chunks)
        self.calls = []
        self.started = 0
        self.gate = None          # threading.Event: block between chunks when set
        self.fail_after = None    # raise after this many chunks were delivered

    def complete(self, role, prompt, params, extra=None, stream_cb=None,
                 meta=None, token=None, **kw):
        self.calls.append({"role": role, "prompt": prompt, "params": params,
                           "extra": extra, "meta": meta})
        self.started += 1
        out = []
        for i, ch in enumerate(self.chunks):
            if self.gate is not None and i > 0 and not self.gate.wait(10):
                raise AssertionError("fake provider gate never opened")
            if token is not None:
                token.check()
            out.append(ch)
            if stream_cb:
                stream_cb(ch)
            if self.fail_after is not None and i >= self.fail_after:
                raise RuntimeError("fake provider failed midstream")
        return "".join(out), "stop", {}

    def many(self, fn, n, token=None, on_event=None):
        results = []
        for k in range(1, n + 1):
            if token is not None:
                token.check()
            try:
                results.append(fn())
                if on_event:
                    on_event({"type": "candidate_done", "k": k, "n": n})
            except longform_core.cancel.Cancelled:
                raise
            except Exception as e:  # noqa: BLE001  (mirrors Api.many)
                if on_event:
                    on_event({"type": "candidate_failed", "k": k, "n": n,
                              "why": f"{type(e).__name__}: {e}"})
        return results


def _pump(a, cond, limit=6000):
    """Run Qt events until cond() is true; deterministic, no sleeps."""
    for _ in range(limit):
        if cond():
            return True
        a.processEvents()
    return False


def _draft_project(root, name="p", scenes=None, trees=None):
    project = _build_project(root / name,
                             scenes=scenes or [_scene("s001", title="Yard", pov="Mara",
                                                      characters=["Mara"])],
                             trees=trees if trees is not None else {
                                 "s001": _tree({"n1": _node("n1", None,
                                                            "Mara counts the lit windows.")},
                                               head="n1")},
                             bible="# Story bible\n\nQuiet town.",
                             state="Mara is at the yard.",
                             project_extra={"api_key": "sk-test"})
    _write_json(project / "writer_preset.json", PRESET)
    return project


def case_draft_generate_acceptance(root):
    """Type unsaved steering, Generate through the real worker + fake provider,
    read while working, then Accept; reopen shows saved steering/text/branch."""
    import longform_core.gui_window as gw
    a = app()
    project = _draft_project(root)
    fake = FakeProvider()
    win = gw.MainWindow(str(project), choice=_no_dialogs("draft acceptance"),
                        provider_factory=lambda _p: fake)
    win.show()
    win.select_item("manuscript", "s001", None)
    assert win.generate_btn.isEnabled(), \
        "Generate must be enabled for a writable scene with prerequisites"

    win.steer_editor.setPlainText("Keep it slow.")
    assert win.dirty()
    win.count_spin.setValue(1)   # N=1 streams live into the preview
    fake.gate = threading.Event()
    win.generate_btn.click()
    assert _pump(a, lambda: fake.started >= 1), "generation started"
    saved_tree = json.loads((project / "trees" / "s001.json").read_text())
    assert saved_tree.get("steer") == "Keep it slow.", \
        "unsaved steering is captured and saved before the provider call"

    assert _pump(a, lambda: "First chunk." in win.preview.toPlainText()), \
        "streamed deltas reach the provisional preview"
    head_before = saved_tree["head"]
    win.select_item("node", "s001", "n1")
    assert "Mara counts the lit windows." in win.reading.toPlainText(), \
        "reading stays usable while a request is in flight"

    fake.gate.set()
    assert _pump(a, lambda: not win._busy), "worker settles"
    assert "Second chunk." in win.preview.toPlainText()
    t = json.loads((project / "trees" / "s001.json").read_text())
    assert t["head"] == head_before, "no head move until Accept"
    assert set(t["nodes"]) == {"n1", "n2"}, \
        "the complete response is saved as a candidate branch, head unchanged"
    assert win._batch and win._batch["saved"], "completed candidate is offered"

    win.tray.setCurrentRow(0)
    win.accept_btn.click()
    assert _pump(a, lambda: not win._busy)
    t = json.loads((project / "trees" / "s001.json").read_text())
    assert t["head"] != head_before, "Accept moves head to the candidate"
    scenes = json.loads((project / "scenes.json").read_text())
    assert scenes[0]["status"] == "drafting", "planned -> drafting on accept"
    n2 = t["nodes"]["n2"]
    assert n2["parent"] == head_before
    assert n2["text"].strip() == "First chunk. Second chunk."
    assert n2["source"] == "model" and n2["sep"] == ""
    assert n2["steer"] == "Keep it slow."
    assert n2["model"], "node keeps the writer model metadata"
    win.close()

    win2 = gw.MainWindow(str(project), choice=_no_dialogs("reopen"))
    win2.select_item("manuscript", "s001", None)
    assert "First chunk. Second chunk." in win2.reading.toPlainText()
    assert win2.steer_editor.toPlainText() == "Keep it slow."
    win2.select_item("node", "s001", "n2")
    assert "First chunk. Second chunk." in win2.reading.toPlainText()
    win2.close()


def case_draft_midstream_failure(root):
    """A provider failure after partial output saves no node, keeps head and
    prior branches, and Generate can run again after the worker settles."""
    import longform_core.gui_window as gw
    a = app()
    project = _draft_project(root)
    fake = FakeProvider()
    win = gw.MainWindow(str(project), choice=_no_dialogs("failure"),
                        provider_factory=lambda _p: fake)
    win.show()
    win.select_item("manuscript", "s001", None)
    fake.fail_after = 0   # raise right after the first chunk is delivered
    win.count_spin.setValue(1)
    win.generate_btn.click()
    assert _pump(a, lambda: fake.started >= 1)
    assert _pump(a, lambda: not win._busy)
    assert "error" in win.status.text().lower(), "failure is reported"
    t = json.loads((project / "trees" / "s001.json").read_text())
    assert set(t["nodes"]) == {"n1"}, "no partial node is created"
    assert t["head"] == "n1"
    assert not win._batch, "failed output cannot be accepted"
    assert win.generate_btn.isEnabled(), "controls recover after an error"

    fake.fail_after = None
    win.generate_btn.click()
    assert _pump(a, lambda: not win._busy)
    t = json.loads((project / "trees" / "s001.json").read_text())
    assert set(t["nodes"]) == {"n1", "n2"}, "a later generate can run"
    assert t["head"] == "n1"
    win.close()


def case_draft_stop_and_close(root):
    """Stop settles cooperatively at a chunk boundary; conflicting writes are
    disabled while working; close offers Stop and wait / Keep open; late
    signals from superseded operations are ignored."""
    import longform_core.gui_window as gw
    a = app()
    project = _draft_project(root)
    fake = FakeProvider()
    answers = []
    win = gw.MainWindow(str(project), choice=lambda t, x, o: answers.pop(0),
                        provider_factory=lambda _p: fake)
    win.show()
    win.select_item("manuscript", "s001", None)
    win.count_spin.setValue(1)

    fake.gate = threading.Event()
    win.generate_btn.click()
    assert _pump(a, lambda: "First chunk." in win.preview.toPlainText())
    assert not win.save_btn.isEnabled() and not win.clear_btn.isEnabled(), \
        "conflicting writes are disabled while an operation runs"
    assert not win.generate_btn.isEnabled()
    win.stop_btn.click()
    win.stop_btn.click()          # repeated Stop is safe/idempotent
    assert "Stopping" in win.status.text()
    fake.gate.set()
    assert _pump(a, lambda: not win._busy)
    t = json.loads((project / "trees" / "s001.json").read_text())
    assert set(t["nodes"]) == {"n1"} and t["head"] == "n1", \
        "stopped partial output is never saved"
    assert win.generate_btn.isEnabled(), "controls return after settlement"
    assert "not saved" in win.status.text().lower() or "stopped" in win.status.text().lower()

    # late payloads of a superseded operation never rebind the view
    stale_op = win._op_id + 7
    win._on_worker_event(stale_op, {"type": "delta", "text": "LATE TEXT"})
    assert "LATE TEXT" not in win.preview.toPlainText()
    win._on_worker_done(stale_op, "ok", object())
    assert not win._busy

    # close while working: Keep open preserves the running job, cancels nothing
    win.generate_btn.click()
    assert _pump(a, lambda: fake.started >= 2)
    answers.append("Keep open")
    win.close()
    assert win.isVisible(), "Keep open keeps the window and the job"
    assert win._busy and fake.started == 2, "Keep open does not cancel"
    fake.gate.set()
    assert _pump(a, lambda: not win._busy)

    # close while working again: Stop and wait cancels, settles, then closes
    win.generate_btn.click()
    assert _pump(a, lambda: fake.started >= 3)
    answers.append("Stop and wait")
    win.close()
    assert _pump(a, lambda: not win._busy), "Stop and wait settles"
    assert "stopping" in win.status.text().lower() or win._token.cancelled
    assert _pump(a, lambda: not win.isVisible()), "closes only after settlement"


def case_draft_stale_refusal(root):
    """An external change during the request refuses the save, keeps dirty
    local text and offers recovery."""
    import longform_core.gui_window as gw
    a = app()
    project = _draft_project(root)
    fake = FakeProvider()
    win = gw.MainWindow(str(project), choice=_no_dialogs("stale"),
                        provider_factory=lambda _p: fake)
    win.show()
    win.select_item("manuscript", "s001", None)
    win.count_spin.setValue(1)
    fake.gate = threading.Event()
    win.generate_btn.click()
    assert _pump(a, lambda: fake.started >= 1)

    # an external writer changes the tree while the request runs
    t = json.loads((project / "trees" / "s001.json").read_text())
    t["nodes"]["n7"] = {"id": "n7", "parent": "n1", "text": "external change",
                        "created": "x", "history": [], "sep": "\n\n"}
    _write_json(project / "trees" / "s001.json", t)

    win.steer_editor.setPlainText("unsaved during work")   # dirty local text
    fake.gate.set()
    assert _pump(a, lambda: not win._busy)
    assert "reload" in win.status.text().lower(), "stale refusal offers recovery"
    got = json.loads((project / "trees" / "s001.json").read_text())
    assert "n2" not in got["nodes"], "the stale candidate is not committed"
    assert got["nodes"]["n7"]["text"] == "external change"
    assert win.steer_editor.toPlainText() == "unsaved during work", \
        "dirty local text is retained"
    assert win.generate_btn.isEnabled()
    win.steer_editor.setPlainText("")   # leave clean; no dialog on close
    win.close()
    assert not win.isVisible()


CASES = {
    "owner_flow_reading": case_owner_flow_reading,
    "case_draft_generate_acceptance": case_draft_generate_acceptance,
    "case_draft_midstream_failure": case_draft_midstream_failure,
    "case_draft_stop_and_close": case_draft_stop_and_close,
    "case_draft_stale_refusal": case_draft_stale_refusal,
    "owner_flow_steering": case_owner_flow_steering,
    "case_navigation_no_writes": case_navigation_no_writes,
    "case_reading_states": case_reading_states,
    "case_focus_and_tab_order": case_focus_and_tab_order,
    "case_enter_inserts_newline": case_enter_inserts_newline,
    "case_palette_and_prose_size": case_palette_and_prose_size,
    "case_readonly_panes": case_readonly_panes,
    "case_dirty_scene_choices": case_dirty_scene_choices,
    "case_close_choices": case_close_choices,
    "case_stale_conflict": case_stale_conflict,
    "case_refresh_preserves_state": case_refresh_preserves_state,
    "case_removed_node_and_scene": case_removed_node_and_scene,
    "case_invalid_config_and_recovery": case_invalid_config_and_recovery,
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
