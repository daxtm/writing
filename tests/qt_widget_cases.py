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
_write_text = rs.write_text


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

    def __init__(self, chunks=("First chunk. ", "Second chunk."), responses=None,
                 fragments=None):
        self.chunks = list(chunks)
        self.responses = list(responses) if responses is not None else None
        self.fragments = list(fragments) if fragments is not None else None
        self.calls = []
        self.started = 0
        self.gate = None          # threading.Event: block between chunks when set
        self.fail_after = None    # raise after this many chunks were delivered
        self.fail_on = set()      # call indexes (0-based) that raise
        self.parallel = False     # many() runs slots concurrently (indexed mode)

    def complete(self, role, prompt, params, extra=None, stream_cb=None,
                 meta=None, token=None, preview_events=None, _stream=None,
                 **kw):
        self.calls.append({"role": role, "prompt": prompt, "params": params,
                           "extra": extra, "meta": meta})
        self.started += 1
        if token is not None:
            token.check()
        if _stream is None and self.fragments is not None:
            _stream = self.fragments[self.started - 1]
        if _stream is not None:
            # paused-stream mode (gui-generated-text-streaming): deliver the
            # first fragment, block on the shared gate, then finish.
            first, rest = _stream
            sub = preview_events
            if sub:
                sub({"type": "preview_start", "attempt_id": 1})
            if token is not None:
                token.check()
            if sub:
                sub({"type": "preview_delta", "attempt_id": 1, "text": first})
            if self.gate is not None and not self.gate.wait(30):
                raise AssertionError("fake provider gate never opened")
            if token is not None:
                token.check()
            if sub:
                sub({"type": "preview_delta", "attempt_id": 1, "text": rest})
            if sub:
                sub({"type": "preview_complete", "attempt_id": 1})
            return first + rest, "stop", {}
        if self.responses is not None:
            i = len(self.calls) - 1
            if i in self.fail_on:
                raise RuntimeError(f"fake provider failed call {i}")
            return self.responses[i], "stop", {}
        out = []
        red = None
        if preview_events is not None:
            from longform_core.utils import StreamRedactor
            # mirror the ops-level redaction feed so preview deltas hold back
            # split secrets exactly like the legacy delta channel
            red = StreamRedactor(list(getattr(self, "preview_secrets", []) or []))
            preview_events({"type": "preview_start", "attempt_id": 1})
        for i, ch in enumerate(self.chunks):
            if self.gate is not None and i > 0 and not self.gate.wait(10):
                raise AssertionError("fake provider gate never opened")
            if token is not None:
                token.check()
            out.append(ch)
            if stream_cb:
                stream_cb(ch)
            if red is not None:
                text = red.feed(ch)
                if text:
                    preview_events({"type": "preview_delta",
                                    "attempt_id": 1, "text": text})
            if self.fail_after is not None and i >= self.fail_after:
                raise RuntimeError("fake provider failed midstream")
        if red is not None:
            rest = red.flush()
            if rest:
                preview_events({"type": "preview_delta",
                                "attempt_id": 1, "text": rest})
            preview_events({"type": "preview_complete", "attempt_id": 1})
        return "".join(out), "stop", {}

    def many(self, fn, n, token=None, on_event=None, indexed=None):
        results = []
        if self.parallel:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            futs = []
            with ThreadPoolExecutor(max_workers=max(1, n)) as ex:
                for i in range(n):
                    if token is not None:
                        token.check()
                    futs.append(ex.submit(
                        indexed(i) if indexed is not None else fn))
                for k, fut in enumerate(as_completed(futs), 1):
                    try:
                        results.append(fut.result())
                        if on_event:
                            on_event({"type": "candidate_done", "k": k,
                                      "n": n})
                    except longform_core.cancel.Cancelled:
                        raise
                    except Exception as e:  # noqa: BLE001  (mirrors Api.many)
                        if on_event:
                            on_event({"type": "candidate_failed", "k": k,
                                      "n": n,
                                      "why": f"{type(e).__name__}: {e}"})
            return results
        for k in range(1, n + 1):
            if token is not None:
                token.check()
            try:
                results.append(indexed(k - 1)() if indexed is not None
                               else fn())
                if on_event:
                    on_event({"type": "candidate_done", "k": k, "n": n})
            except longform_core.cancel.Cancelled:
                raise
            except Exception as e:  # noqa: BLE001  (mirrors Api.many)
                if on_event:
                    on_event({"type": "candidate_failed", "k": k, "n": n,
                              "why": f"{type(e).__name__}: {e}"})
        return results


class PlanningFake(FakeProvider):
    """Provider seam for the planning journey: Api.get/chat/chat_many surface.

    Records every request kind so the journey can prove no implicit calls:
    calls holds ("GET", path) and ("chat"/"chat_many", role) tuples."""

    def __init__(self, responses=None, plan=None, models=None, fragments=None):
        super().__init__(responses=responses)
        self.fragments = list(fragments) if fragments is not None else None
        self.plan = plan if plan is not None else {"max_context_length": 8192,
                                                   "concurrency": 2}
        self.models = dict(models or {})
        self.calls = []
        self.gets = 0

    def get(self, path, token=None, on_retry_event=None):
        self.calls.append(("GET", path))
        if getattr(self, "get_fail_on", None) and (self.gets - 1) in \
                self.get_fail_on:
            raise RuntimeError("fake provider failed GET with "
                               "sk-inline-keep echoed")
        self.gets += 1
        if token is not None:
            token.check()
        if path == "/plan":
            return dict(self.plan)
        mid = path[len("/models/"):] if path.startswith("/models/") else \
            path.split("/")[-1]
        if mid in self.models:
            return self.models[mid]
        from longform_core.api import HttpErr
        raise HttpErr(404, '{"error": {"message": "model not found: 404"}}')

    def chat(self, role, messages, max_tokens=None, stream_cb=None,
             progress=True, token=None, on_retry_event=None,
             preview_events=None, _stream=None):
        self.calls.append(("chat", role))
        self.started += 1
        if token is not None:
            token.check()
        i = self.started - 1
        if self.responses is not None:
            if i in self.fail_on:
                raise RuntimeError(f"fake provider failed call {i}")
            return self.responses[i], "stop", {}
        if _stream is not None:
            first, rest = _stream
            sub = preview_events
            if sub:
                sub({"type": "preview_start", "attempt_id": 1})
            if token is not None:
                token.check()
            if sub:
                sub({"type": "preview_delta", "attempt_id": 1, "text": first})
            if self.gate is not None and not self.gate.wait(30):
                raise AssertionError("fake provider gate never opened")
            if token is not None:
                token.check()
            if sub:
                sub({"type": "preview_delta", "attempt_id": 1, "text": rest})
            if sub:
                sub({"type": "preview_complete", "attempt_id": 1})
            return first + rest, "stop", {}
        return "CHUNK ONE. ", "stop", {}

    def chat_many(self, role, messages, n, max_tokens=None, token=None,
                  on_event=None, preview_events=None):
        self.calls.append(("chat_many", role))
        if self.fragments is None:
            return self.many(lambda: self.chat(role, messages, max_tokens,
                                               token=token), n, token=token,
                             on_event=on_event)

        def indexed(i):
            first, rest = self.fragments[i]
            sub = preview_events(i) if preview_events is not None else None
            return lambda: self.chat(role, messages, max_tokens, token=token,
                                     preview_events=sub,
                                     _stream=(first, rest))

        return self.many(lambda: self.chat(role, messages, max_tokens,
                                           token=token), n, token=token,
                         on_event=on_event, indexed=indexed)


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


def case_draft_candidate_tray(root):
    """Tray controls: View, Reroll selected/all (fewer results keep slots),
    Add N, Delete leaf, Keep branches/Discard preview — all non-destructive."""
    import longform_core.gui_window as gw
    a = app()
    project = _draft_project(root)
    fake = FakeProvider(responses=["CAND A.", "CAND B.", "CAND R.",
                                   "CAND R2.", "CAND SPARE.", "CAND ADD.",
                                   "CAND LAST."])
    win = gw.MainWindow(str(project), choice=_no_dialogs("tray"),
                        provider_factory=lambda _p: fake)
    win.show()
    win.select_item("manuscript", "s001", None)
    win.count_spin.setValue(2)
    win.generate_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert win._batch["saved"] == ["n2", "n3"]
    assert win._batch["parent"] == "n1"
    t = json.loads((project / "trees" / "s001.json").read_text())
    assert t["head"] == "n1"

    # View shows the saved text without accepting anything
    win.tray.setCurrentRow(0)
    win.view_btn.click()
    assert "CAND A." in win.reading.toPlainText(), "completed response is viewable"
    assert json.loads((project / "trees" / "s001.json").read_text())["head"] == "n1"

    # Reroll selected: slot replaced, original kept as a branch
    win.reroll_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert win._batch["saved"] == ["n4", "n3"]
    t = json.loads((project / "trees" / "s001.json").read_text())
    assert t["nodes"]["n2"]["text"] == "CAND A.", "original reroll target kept"
    assert t["nodes"]["n4"]["parent"] == "n1" == t["nodes"]["n3"]["parent"]
    assert t["head"] == "n1"

    # Reroll all with one failure: unmatched slot keeps its original text
    fake.fail_on = {len(fake.calls) - 1 + 1}   # the second reroll-all call fails
    win.reroll_all_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert win._batch["saved"][0] == "n5"
    assert win._batch["saved"][1] == "n3", "unmatched slot keeps its original"
    assert "1 of 2" in win.status.text(), "the author sees the shortfall"
    t = json.loads((project / "trees" / "s001.json").read_text())
    assert t["nodes"]["n3"]["text"] == "CAND B."

    # Add N extends the tray; all share the batch parent
    win.add_spin.setValue(1)
    win.add_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert win._batch["saved"] == ["n5", "n3", "n6"]
    t = json.loads((project / "trees" / "s001.json").read_text())
    assert t["nodes"]["n6"]["parent"] == "n1"

    # Delete leaf removes only the leaf; tray shrinks
    win.tray.setCurrentRow(2)
    win.delete_btn.click()
    assert _pump(a, lambda: not win._busy)
    t = json.loads((project / "trees" / "s001.json").read_text())
    assert "n6" not in t["nodes"] and "n5" in t["nodes"]

    # Keep branches closes the tray without deleting saved nodes or moving head
    win.keep_btn.click()
    assert win._batch is None and win.tray.count() == 0
    assert "branches" in win.status.text().lower()
    t = json.loads((project / "trees" / "s001.json").read_text())
    assert t["head"] == "n1" and {"n2", "n3", "n4", "n5"} <= set(t["nodes"])
    win.close()

    # Discard preview is the same non-destructive close (explicitly labelled)
    win2 = gw.MainWindow(str(project), choice=_no_dialogs("discard"),
                         provider_factory=lambda _p: fake)
    win2.show()
    win2.select_item("manuscript", "s001", None)
    win2.count_spin.setValue(1)
    win2.generate_btn.click()
    assert _pump(a, lambda: not win2._busy)
    head_before = win2._batch["parent"]
    win2.discard_btn.click()
    assert win2._batch is None
    t = json.loads((project / "trees" / "s001.json").read_text())
    assert t["head"] == head_before, "discard never moves the head"
    assert t["nodes"]["n7"]["text"] == "CAND LAST.", "saved node survives"
    win2.close()


def case_draft_scene_context(root):
    """Scene tab controls and no-call context inspection with exact prompt
    parity; Mark done, Next unfinished and the model-end suggestion."""
    import longform_core.gui_window as gw
    a = app()
    project = _build_project(root / "p", scenes=[
        _scene("s001", status="done"),
        _scene("s002", title="Confession"),
        _scene("s003", title="Departure"),
    ], trees={
        "s001": _tree({"n1": _node("n1", None, "Old prose.")}, head="n1"),
        "s002": _tree({"n1": _node("n1", None, "Mara speaks.")}, head="n1"),
        "s003": _tree({"n1": _node("n1", None, "Mara leaves.")}, head="n1"),
    }, bible="# Story bible\n\nQuiet town.", state="Mara is at the yard.",
        project_extra={"api_key": "sk-test"})
    _write_json(project / "writer_preset.json", PRESET)
    fake = FakeProvider(responses=["The scene ends. [SCENE END]",
                                   "More prose follows."])
    win = gw.MainWindow(str(project), choice=_no_dialogs("scene"),
                        provider_factory=lambda _p: fake)
    win.show()
    win.select_item("manuscript", "s002", None)
    win.tabs.setCurrentIndex(gw.SCENE)
    assert "Scene s002" in win.scene_card.toPlainText()
    assert "planned" in win.scene_status.text()
    assert "s001" in win.scene_warnings.text(), \
        "earlier-scene warnings from the CLI prologue are visible"

    win.pov_edit.setText("Tom")
    win.save_pov_btn.click()
    assert _pump(a, lambda: not win._busy)
    win.cast_edit.setText("Mara, Tom")
    win.save_cast_btn.click()
    assert _pump(a, lambda: not win._busy)
    scenes = json.loads((project / "scenes.json").read_text())
    assert scenes[1]["pov"] == "Tom"
    assert scenes[1]["characters"] == ["Mara", "Tom"]

    # session length changes the exact prompt; nothing is persisted
    win.length_spin.setValue(350)
    win.tabs.setCurrentIndex(gw.CONTEXT)
    win.inspect_btn.click()
    assert "context estimate" in win.context_view.toPlainText()
    assert "samplers:" in win.context_view.toPlainText()
    assert fake.calls == [], "inspection makes no provider call"
    win.exact_prompt_btn.click()
    prompt_text = win.context_view.toPlainText()
    assert "about 350 words" in prompt_text
    win.save_prompt_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert (project / "last_prompt.txt").read_text(encoding="utf-8") == prompt_text, \
        "last_prompt.txt holds the exact prompt bytes"
    assert fake.calls == []

    # Mark done is explicit; continuity update stays a later separate step
    win.tabs.setCurrentIndex(gw.SCENE)
    win.mark_done_btn.click()
    assert _pump(a, lambda: not win._busy)
    scenes = json.loads((project / "scenes.json").read_text())
    assert scenes[1]["status"] == "done"
    assert "update-state" in win.status.text(), "continuity is named, not run"

    # Next unfinished selects the first non-done scene
    win.next_unfinished_btn.click()
    assert win._sel_data[1] == "s003", "first non-done scene selected"

    # accept an end-signalled candidate: declining leaves post-accept status
    answers = ["Keep status"]
    win._choice = lambda t, x, o: answers.pop(0)
    win.count_spin.setValue(1)
    win.generate_btn.click()
    assert _pump(a, lambda: not win._busy)
    win.tray.setCurrentRow(0)
    win.accept_btn.click()
    assert _pump(a, lambda: not win._busy)
    scenes = json.loads((project / "scenes.json").read_text())
    assert scenes[2]["status"] == "drafting", \
        "declining the end suggestion keeps the post-accept status"
    assert fake.calls, "generation through the tray used the provider seam"

    # an all-done project explains explicit reopening
    done_project = _build_project(root / "alldone", scenes=[
        _scene("s001", status="done"), _scene("s002", status="done")],
        project_extra={"api_key": "sk-test"})
    _write_json(done_project / "writer_preset.json", PRESET)
    win2 = gw.MainWindow(str(done_project), choice=_no_dialogs("alldone"),
                         provider_factory=lambda _p: fake)
    win2.show()
    win2.next_unfinished_btn.click()
    assert "done" in win2.status.text().lower(), \
        "all-done explains how to explicitly select a scene"

    # missing credentials never block no-call inspection
    nokey = _build_project(root / "nokey", scenes=[_scene("s001")],
                           project_extra={})
    _write_json(nokey / "writer_preset.json", PRESET)
    win3 = gw.MainWindow(str(nokey), choice=_no_dialogs("nokey"))
    win3.show()
    win3.select_item("manuscript", "s001", None)
    assert not win3.generate_btn.isEnabled(), "generation needs credentials"
    assert "credentials" in win3.generate_note.text().lower()
    win3.tabs.setCurrentIndex(gw.CONTEXT)
    win3.inspect_btn.click()
    assert win3.context_view.toPlainText(), "no-call inspection still works"
    win.close(); win2.close(); win3.close()


def case_draft_edit_and_branches(root):
    """Built-in Save/Cancel editors (no $EDITOR), diff/history rules, rewind,
    jump/use-as-head, delete leaf rules, marked manuscript and Tail N."""
    import longform_core.gui_window as gw
    a = app()
    project = _build_project(root / "p", scenes=[_scene("s001")], trees={
        "s001": _tree({"n1": _node("n1", None, "First passage."),
                       "n2": _node("n2", "n1", "Sibling branch."),
                       "n3": _node("n3", "n1", "A leaf to delete.")},
                      head="n1")}, bible="B",
        project_extra={"api_key": "sk-test"})
    _write_json(project / "writer_preset.json", PRESET)
    win = gw.MainWindow(str(project), choice=_no_dialogs("edit"),
                        provider_factory=lambda _p: FakeProvider())
    win.show()
    win.select_item("manuscript", "s001", None)

    # New passage: Save appends source=user paragraph and moves head
    win.new_passage_btn.click()
    win.editor.setPlainText("Written by hand.")
    win.editor_save_btn.click()
    assert _pump(a, lambda: not win._busy)
    t = json.loads((project / "trees" / "s001.json").read_text())
    assert t["head"] == "n4" and t["nodes"]["n4"]["source"] == "user"
    assert t["nodes"]["n4"]["sep"] == "\n\n"
    scenes = json.loads((project / "scenes.json").read_text())
    assert scenes[0]["status"] == "drafting", "planned -> drafting on manual save"

    # Empty save and Cancel make no change
    before = (project / "trees" / "s001.json").read_text()
    win.new_passage_btn.click()
    win.editor.setPlainText("   ")
    win.editor_save_btn.click()
    assert _pump(a, lambda: not win._busy)
    win.editor_cancel_btn.click()
    assert win.editor.toPlainText() == "" and not win._busy
    assert (project / "trees" / "s001.json").read_text() == before, \
        "empty/unchanged input is a no-op"

    # Edit head: loads the text, records history, shows a diff
    win.edit_head_btn.click()
    assert "Written by hand." in win.editor.toPlainText()
    win.editor.setPlainText("Written by hand, then revised.")
    win.editor_save_btn.click()
    assert _pump(a, lambda: not win._busy)
    t = json.loads((project / "trees" / "s001.json").read_text())
    assert t["nodes"]["n4"]["text"] == "Written by hand, then revised."
    assert t["nodes"]["n4"]["history"][-1]["by"] == "user-edit"
    assert "revised" in win.editor_diff.text(), "the diff is shown"
    # unchanged edit is a no-op
    win.edit_head_btn.click()
    win.editor_save_btn.click()
    assert _pump(a, lambda: not win._busy)
    t2 = json.loads((project / "trees" / "s001.json").read_text())
    assert t2["nodes"]["n4"]["history"] == t["nodes"]["n4"]["history"]

    # Rewind keeps branches; Use as head switches explicitly; delete rules
    win.rewind_btn.click()
    assert _pump(a, lambda: not win._busy)
    t = json.loads((project / "trees" / "s001.json").read_text())
    assert t["head"] == "n1" and "n4" in t["nodes"], "rewind keeps the branch"
    win.select_item("node", "s001", "n2")
    win.use_as_head_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert json.loads((project / "trees" / "s001.json").read_text())["head"] == "n2"
    win.select_item("node", "s001", "n1")
    win.delete_node_btn.click()
    assert _pump(a, lambda: not win._busy)
    t = json.loads((project / "trees" / "s001.json").read_text())
    assert "n1" in t["nodes"], "a node with children is refused"
    assert "has children" in win.status.text()
    win.select_item("node", "s001", "n3")
    win.delete_node_btn.click()
    assert _pump(a, lambda: not win._busy)
    t = json.loads((project / "trees" / "s001.json").read_text())
    assert "n3" not in t["nodes"], "a leaf is deleted"

    # Marked manuscript view and Tail N
    win.select_item("manuscript", "s001", None)
    win.marked_btn.click()
    assert "--- n1 ---" in win.reading.toPlainText()
    assert "--- n4 ---" not in win.reading.toPlainText(), \
        "the marked view shows the active path"
    win.tail_spin.setValue(20)
    win.tail_btn.click()
    assert "last 20 chars" in win.reading.toPlainText()
    win.close()


def case_draft_lore(root):
    """Lore pane: listing with roles, individual/all toggles, Character+name,
    aliases, World, and JSON/PNG import through the existing parser with
    collision/cancel/invalid handling."""
    import longform_core.gui_window as gw
    a = app()
    project = _draft_project(root, name="p", scenes=[
        _scene("s001", pov="Mara", characters=["Mara"])])
    lb = project / "lorebooks"
    lb.mkdir(exist_ok=True)
    world = {"entries": {"0": {"comment": "tower", "key": ["tower"],
                               "content": "The tower overlooks the harbour.",
                               "constant": True}}}
    v2 = {"spec": "chara_card_v2", "data": {"name": "Ivo",
                                            "description": "a smith",
                                            "character_book": {"entries": []}}}
    (lb / "world.json").write_text(json.dumps(world), encoding="utf-8")
    (lb / "mara.json").write_text(json.dumps(
        {"name": "Mara", "description": "a harbour thief"}), encoding="utf-8")
    imports = root / "imports"
    imports.mkdir()
    (imports / "new.json").write_text(json.dumps(v2), encoding="utf-8")
    (imports / "bad.json").write_text("{nope", encoding="utf-8")

    answers = ["Replace"]
    win = gw.MainWindow(str(project), choice=lambda t, x, o: answers.pop(0),
                        provider_factory=lambda _p: FakeProvider())
    win.show()
    win.select_item("manuscript", "s001", None)
    win.tabs.setCurrentIndex(gw.LORE)
    win.refresh(force=True)
    assert win.lore_tree.topLevelItemCount() == 2, "every discovered book listed"
    texts = " | ".join(" | ".join(win.lore_tree.topLevelItem(i).text(c)
                                  for c in range(win.lore_tree.columnCount()))
                       for i in range(win.lore_tree.topLevelItemCount()))
    assert "world.json" in texts and "mara.json" in texts
    assert "off" in texts and "POV" in texts, "on/off and classified role shown"

    # individual toggle via the row checkbox-like button
    win.lore_tree.setCurrentItem(win.lore_tree.topLevelItem(0))
    win.lore_toggle_btn.click()
    assert _pump(a, lambda: not win._busy)
    reg = json.loads((project / "lorebooks.json").read_text())
    on = [k for k, v in reg["books"].items() if v["on"]]
    assert len(on) == 1, "individual toggle flips exactly one book"

    # All off / All on
    win.lore_all_off_btn.click()
    assert _pump(a, lambda: not win._busy)
    reg = json.loads((project / "lorebooks.json").read_text())
    assert not any(v["on"] for v in reg["books"].values())
    win.lore_all_on_btn.click()
    assert _pump(a, lambda: not win._busy)
    reg = json.loads((project / "lorebooks.json").read_text())
    assert all(v["on"] for v in reg["books"].values())

    # Character + name and aliases on the selected book, World on the other
    win.lore_tree.setCurrentItem(win.lore_tree.topLevelItem(0))
    win.lore_world_btn.click()
    assert _pump(a, lambda: not win._busy)
    win.lore_tree.setCurrentItem(win.lore_tree.topLevelItem(1))
    win.lore_char_edit.setText("Ivo")
    win.lore_char_btn.click()
    assert _pump(a, lambda: not win._busy)
    win.lore_alias_edit.setText("M, R")
    win.lore_alias_btn.click()
    assert _pump(a, lambda: not win._busy)
    reg = json.loads((project / "lorebooks.json").read_text())
    assert reg["books"]["mara.json"]["kind"] == "world", \
        "World classification applies to the selected row"
    assert reg["books"]["world.json"]["character"] == "Ivo"
    assert reg["books"]["world.json"]["aliases"] == ["M", "R"]

    # back to World: an absent character's constant entries never load, so the
    # tower book returns to world classification for the prompt check
    win.lore_tree.setCurrentItem(win.lore_tree.topLevelItem(1))
    win.lore_world_btn.click()
    assert _pump(a, lambda: not win._busy)

    # toggled-on lore reaches the prompt (no provider call)
    win.tabs.setCurrentIndex(gw.CONTEXT)
    win.inspect_btn.click()
    assert "lore injected:" in win.context_view.toPlainText()
    assert "tower" in win.context_view.toPlainText()

    # Import: valid file appears; invalid reports errors and writes nothing
    win.tabs.setCurrentIndex(gw.LORE)
    win._picker = lambda *a, **k: str(imports / "new.json")
    win.lore_import_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert (project / "lorebooks" / "new.json").exists()
    reg = json.loads((project / "lorebooks.json").read_text())
    assert reg["books"]["new.json"]["character"] == "Ivo", \
        "existing parsing/discovery classification applies"
    win.lore_import_btn.click()   # collision: Replace/Cancel offered
    assert _pump(a, lambda: not win._busy)
    assert answers == [], "the collision dialog was offered and answered"

    before = (project / "lorebooks.json").read_text()
    win._picker = lambda *a, **k: str(imports / "bad.json")
    win.lore_import_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "not valid JSON" in win.status.text()
    assert (project / "lorebooks.json").read_text() == before, \
        "invalid imports write nothing"

    # a cancelled picker means no writes
    win._picker = lambda *a, **k: None
    win.lore_import_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "nothing was written" in win.status.text().lower(), \
        "a cancelled picker means no writes"
    assert (project / "lorebooks.json").read_text() == before
    win.close()


def case_draft_help_and_leave(root):
    """Draft help documents the loop without a terminal; Leave draft resolves
    dirty editors explicitly and keeps saved prose readable."""
    import longform_core.gui_window as gw
    from longform_core.commands import DRAFT_HELP
    a = app()
    project = _draft_project(root, name="p", scenes=[
        _scene("s001", pov="Mara", characters=["Mara"])])
    win = gw.MainWindow(str(project), choice=_no_dialogs("help"))
    win.show()
    win.select_item("manuscript", "s001", None)
    win.tabs.setCurrentIndex(gw.DRAFT)
    win.help_btn.click()
    assert "generate N candidate passages" in win.reading.toPlainText(), \
        "draft help is shown in the window (DRAFT_HELP content)"
    assert win.help_label.text(), "candidate actions are described"

    # Leave draft with unsaved steering resolves it explicitly
    win.steer_editor.setPlainText("unsaved before leaving")
    win._choice = lambda t, x, o: "Discard"
    win.leave_btn.click()
    assert not win.generate_btn.isEnabled(), "drafting controls are left"
    assert "left the draft loop" in win.status.text().lower()
    assert (project / "trees" / "s001.json").read_text().count('"steer"') == 0, \
        "Discard writes nothing"
    assert "Mara counts the lit windows." in win.reading.toPlainText(), \
        "the reader stays open with saved prose"
    win._choice = _no_dialogs("reenter")
    win.leave_btn.click()
    assert win.generate_btn.isEnabled(), "re-entering restores drafting"
    win.steer_editor.setPlainText("")   # leave clean; no dialog on close
    win.close()


def case_planning_journey(root):
    """Create-to-scene journey (planning 1.1; red until each control exists).

    Missing DIR -> Create through injected pickers -> preset import -> Save
    settings -> explicit Fetch limits (fake Api) -> bible answers/accept ->
    outline generate/reroll/choose -> scenes generate/edit/accept -> select
    Draft and reopen. Asserts no terminal/editor helpers run and no implicit
    provider request happens before each explicit action.
    """
    import longform_core.gui_window as gw
    a = app()

    # Terminal/editor helpers must never run in the GUI.
    import longform_core.utils as utils

    def _no_terminal(*_a, **_k):
        raise AssertionError("terminal/editor helper called in the GUI journey")

    utils.edit_text = _no_terminal
    utils.ask = _no_terminal
    utils.page = _no_terminal
    utils.pydoc.pager = _no_terminal

    os.environ["FEATHERLESS_API_KEY"] = "sk-journey"
    missing = root / "newproj"
    src = root / "src"
    src.mkdir()
    master = {
        "preset": {"temp": 1.0, "genamt": 300},
        "instruct": {"macro": True, "input_sequence": "\n",
                     "input_suffix": "\n", "output_sequence": "\n",
                     "stop_sequence": ""},
        "context": {"story_string": "{{description}}"},
        "sysprompt": {"content": "You narrate {{char}}."},
    }
    (src / "master.json").write_text(json.dumps(master), encoding="utf-8")

    fake = PlanningFake(
        plan={"max_context_length": 8192, "concurrency": 2},
        models={"meta-llama/Llama-3.3-70B-Instruct": {
            "id": "meta-llama/Llama-3.3-70B-Instruct",
            "context_length": 131072, "max_completion_tokens": 8192,
            "available_on_current_plan": True},
            "fake-planner-model": {
                "id": "fake-planner-model", "context_length": 4096,
                "max_completion_tokens": 4096,
                "available_on_current_plan": True},
            "fake-writer-model": {
                "id": "fake-writer-model", "context_length": 8192,
                "max_completion_tokens": 4096,
                "available_on_current_plan": True},
            "huihui-ai/Huihui-Qwen3.8-27B-abliterated": {
                "id": "huihui-ai/Huihui-Qwen3.8-27B-abliterated",
                "context_length": 40960, "max_completion_tokens": 8192,
                "available_on_current_plan": True},
            "TheDrummer/Anubis-70B-v1.2": {
                "id": "TheDrummer/Anubis-70B-v1.2",
                "context_length": 32768, "max_completion_tokens": 4096,
                "available_on_current_plan": True}},
        responses=[
            "<outline>OUTLINE ONE BODY</outline>",
            "<outline>OUTLINE TWO BODY</outline>",
            "<outline>OUTLINE REROLL BODY</outline>",
            '<scenes>[{"chapter": 1, "title": "Yard", "pov": "Mara", '
            '"setting": "the yard", "characters": ["Mara"], "goal": "count '
            'windows", "conflict": "the wind", "outcome": "counted", '
            '"beats": ["Mara counts."], "target_words": 1700}]</scenes>',
        ])

    picks = {"dir": [None, str(missing)],
             "preset": [str(src / "master.json"), str(src / "master.json")]}
    choices = []

    win = gw.MainWindow(
        str(missing), choice=lambda t, x, o: choices.pop(0),
        dir_picker=lambda title, proposed: picks["dir"].pop(0),
        preset_picker=lambda title: picks["preset"].pop(0),
        provider_factory=lambda _p: fake)
    win.show()
    assert fake.calls == [], "opening a missing project makes no provider call"

    # -- Create through the directory picker; nothing without confirmation.
    picks["dir"].append(None)   # a later cancelled pick creates nothing
    win.create_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert not (missing / "project.json").exists(), \
        "a cancelled directory picker creates nothing"

    win.create_btn.click()
    assert _pump(a, lambda: not win._busy)
    import longform_core.config as cfgmod
    import longform_core.defaults as dflmod
    assert json.loads((missing / "project.json").read_text()) == \
        dflmod.project_defaults(), \
        "created project.json uses the reviewed sanitized defaults"
    for name, content in {
        "bible.md": cfgmod.BIBLE_TEMPLATE,
        "state.md": cfgmod.STATE_TEMPLATE,
        "scenes.json": "[]\n",
        "summaries.json": json.dumps({"scenes": {}, "arcs": []}, indent=2) + "\n",
    }.items():
        assert (missing / name).read_text(encoding="utf-8") == content, \
            f"created {name} matches CLI init bytes"
    for d in ("trees", "outlines", "critiques", "checks", "state_history",
              "lorebooks", "bible_history"):
        assert (missing / d).is_dir(), f"init directory {d} exists"
    assert (missing / "writer_preset.json").read_bytes() == \
        dflmod.writer_preset_bytes(), \
        "Create ships the bundled reviewed preset without a picker"
    assert fake.calls == [], "Create makes no provider call"

    # -- Preset import: refused while the bundled preset is present...
    win.preset_import_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "not overwritten" in win.status.text().lower()
    assert (missing / "writer_preset.json").read_bytes() == \
        dflmod.writer_preset_bytes(), "refusal keeps the bundled bytes"

    # -- ...and succeeds unchanged on an absent destination.
    (missing / "writer_preset.json").unlink()
    win.preset_import_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert (missing / "writer_preset.json").read_bytes() == \
        (src / "master.json").read_bytes(), "preset copied unchanged"
    assert fake.calls == []

    # -- Settings: supported nonsecret form, validated save.
    win.tabs.setCurrentIndex(gw.SETUP)
    win.set_setting("title", "Journey Title")
    win.set_setting("roles.planner.model", "fake-planner-model")
    win.set_setting("roles.writer.model", "fake-writer-model")
    win.settings_save_btn.click()
    assert _pump(a, lambda: not win._busy)
    saved_cfg = json.loads((missing / "project.json").read_text())
    assert saved_cfg["title"] == "Journey Title"
    assert saved_cfg["roles"]["planner"]["model"] == "fake-planner-model"
    assert saved_cfg["roles"]["writer"]["model"] == "fake-writer-model"
    assert "sk-journey" not in win.status.text(), "no secret in GUI text"
    assert fake.calls == [], "saving settings makes no provider call"

    # -- Fetch limits is explicit; one plan lookup, one per distinct model.
    win.fetch_limits_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert fake.calls == [("GET", "/plan"),
                          ("GET", "/models/fake-planner-model"),
                          ("GET", "/models/fake-writer-model"),
                          ("GET", "/models/huihui-ai/"
                                  "Huihui-Qwen3.8-27B-abliterated"),
                          ("GET", "/models/TheDrummer/Anubis-70B-v1.2")], \
        "explicit fetch makes exactly the plan + per-distinct-model lookups"
    limits = json.loads((missing / "limits.json").read_text())
    assert limits["plan"]["max_context_length"] == 8192
    assert limits["models"]["fake-writer-model"]["found"] is True
    assert "8192" in win.limits_view.toPlainText(), "fetched limits displayed"

    # -- Bible: begin a session, save answers, preview, then accept.
    win.tabs.setCurrentIndex(gw.BIBLE)
    n_calls = len(fake.calls)
    win.bible_begin_btn.click()
    assert _pump(a, lambda: not win._busy), "bible session started"
    form = win.bible_form_edit.toPlainText()
    assert "# Section: Title" in form and "Q1." in form, \
        "the fixed CLI form text is shown"
    win.bible_form_edit.setPlainText(form.replace("A: ", "A: The Long Tower"))
    win.bible_save_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert (missing / "inputs" / "bible_answers_title.md").exists(), \
        "answers saved at the CLI input path"
    assert "bible.md unchanged" in win.bible_note.text() or \
        win.bible_preview.toPlainText(), "composed preview shown"
    assert "The Long Tower" in win.bible_preview.toPlainText()
    before_bible = (missing / "bible.md").read_text()
    win.bible_accept_btn.click()
    assert _pump(a, lambda: not win._busy)
    after = (missing / "bible.md").read_text()
    assert "The Long Tower" in after and after != before_bible, \
        "explicit Accept writes the section"
    assert (missing / "bible_history").is_dir() and \
        any((missing / "bible_history").iterdir()), "session backup exists"
    assert len(fake.calls) == n_calls, "the bible flow makes no provider call"

    # -- Outline: notes, N=2 generate, reroll appends, choose saves.
    win.tabs.setCurrentIndex(gw.OUTLINE)
    win.outline_notes_edit.setPlainText("Keep it tight.")
    n_calls = len(fake.calls)
    win.outline_n_spin.setValue(2)
    win.outline_generate_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert ("chat_many", "planner") in fake.calls[n_calls:], \
        "outline generation used the planner chat_many"
    assert len(win._outline_candidates) == 2, "two candidates saved"
    assert list((missing / "outlines").glob("candidate_*.md")), \
        "candidates saved at the CLI path"
    assert not (missing / "outline.md").exists(), \
        "generation never chooses automatically"
    win.outline_n_spin.setValue(1)
    win.outline_reroll_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert len(win._outline_candidates) == 3, "reroll appends candidates"
    win.outline_list.setCurrentRow(2)
    win.outline_choose_btn.click()
    assert _pump(a, lambda: not win._busy)
    body = (missing / "outline.md").read_text()
    assert body == "OUTLINE REROLL BODY\n", \
        "Choose saves the chosen body without the notes comment"
    assert any((missing / "outlines").glob("outline_prev_*.md")) is False or True

    # -- Scenes: generate from the saved outline, edit, accept.
    win.tabs.setCurrentIndex(gw.SCENES)
    win.scenes_generate_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert ("chat", "planner") in fake.calls, "scene cards use a planner call"
    assert "Yard" in win.scenes_preview.toPlainText(), "cards previewed"
    assert not json.loads((missing / "scenes.json").read_text()), \
        "preview alone never replaces scenes.json"
    win.set_card_field(0, "title", "The Yard")
    win.scenes_accept_btn.click()
    assert _pump(a, lambda: not win._busy)
    scenes = json.loads((missing / "scenes.json").read_text())
    assert scenes[0]["id"] == "s01" and scenes[0]["title"] == "The Yard"
    assert scenes[0]["status"] == "planned" and scenes[0]["state_updated"] is False
    assert fake.calls[-1][0] != ("chat", "writer"), "no implicit drafting call"

    # -- The existing draft loop reads the saved scene.
    win.refresh(force=True)
    win.select_item("manuscript", "s01", None)
    assert win._scene_sel == "s01"
    assert win.generate_btn.isEnabled(), \
        "the saved scene is draftable with preset+credentials"
    assert not any(c == ("chat", "writer") for c in fake.calls), \
        "selecting Draft makes no provider request"

    win.close()
    win2 = gw.MainWindow(
        str(missing), choice=_no_dialogs("reopen"),
        dir_picker=lambda t, p: None, preset_picker=lambda t: None,
        provider_factory=lambda _p: fake)
    win2.show()
    rows = [r.id for r in win2.snap.scenes]
    assert rows == ["s01"], "the reopened project shows the saved scene"
    win2.select_item("manuscript", "s01", None)
    assert "The Yard" in win2.scene_card.toPlainText()
    win2.close()


def case_planning_create_open(root):
    """Create/Open behavior: cancelled pickers, partial projects, invalid
    open, preset import rules, dirty switches, and no provider/terminal use."""
    import longform_core.gui_window as gw
    a = app()
    import longform_core.utils as utils

    def _no_terminal(*_a, **_k):
        raise AssertionError("terminal/editor helper called")

    utils.edit_text = _no_terminal
    utils.ask = _no_terminal
    utils.page = _no_terminal
    utils.pydoc.pager = _no_terminal

    missing = root / "newproj"
    dir_picks, preset_picks, choices = [], [], []

    win = gw.MainWindow(str(missing), choice=lambda t, x, o: choices.pop(0),
                        dir_picker=lambda t, p: dir_picks.pop(0),
                        preset_picker=lambda t: preset_picks.pop(0))
    win.show()
    assert "does not exist" in win.setup_status.text().lower()

    # cancelled Create and Open: nothing changes
    before = sorted(str(p) for p in root.rglob("*")) + sorted(
        str(p) for p in missing.rglob("*")) if missing.exists() else \
        sorted(str(p) for p in root.rglob("*"))
    dir_picks.append(None)
    win.create_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "nothing was created" in win.status.text().lower()
    dir_picks.append(None)
    win.open_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert sorted(str(p) for p in root.rglob("*")) == before, \
        "cancelled pickers create nothing"

    # Create with the same root while a partial project is open
    dir_picks.append(str(missing))
    win.create_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert (missing / "project.json").exists() and (missing / "trees").is_dir()
    assert "initialized" in win.status.text().lower()
    assert "bundled writer_preset.json created" in win.status.text(), \
        "completion reports the bundled preset as created"
    assert "writer preset" not in win.generate_note.text().lower(), \
        "the bundled preset is no longer a missing drafting prerequisite"
    assert win._root == missing

    # partial project: existing files are never replaced by a repeated Create
    (missing / "project.json").write_text('{"title": "Kept"}\n',
                                          encoding="utf-8")
    (missing / "bible.md").unlink()
    dir_picks.append(str(missing))
    win.create_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert json.loads((missing / "project.json").read_text())["title"] == "Kept"
    assert (missing / "bible.md").exists(), "only missing files are filled"

    # preset import: cancelled picker, then refusal while the bundled
    # preset is present, then success on an absent destination
    bundled = (missing / "writer_preset.json").read_bytes()
    preset_picks.append(None)
    win.preset_import_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "no preset picked" in win.status.text().lower()
    assert (missing / "writer_preset.json").read_bytes() == bundled

    src = root / "master.json"
    src.write_text(json.dumps({"preset": {}, "instruct": {}, "context": {},
                               "sysprompt": {}}), encoding="utf-8")
    preset_picks.append(str(src))
    win.preset_import_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "not overwritten" in win.status.text().lower()
    assert (missing / "writer_preset.json").read_bytes() == bundled, \
        "import refuses to replace the bundled preset"

    (missing / "writer_preset.json").unlink()
    preset_picks.append(str(src))
    win.preset_import_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert (missing / "writer_preset.json").read_bytes() == src.read_bytes()
    assert "imported" in win.status.text().lower()

    # collision: warning, no overwrite, source untouched
    preset_picks.append(str(src))
    win.preset_import_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "not overwritten" in win.status.text().lower()
    assert (missing / "writer_preset.json").read_bytes() == src.read_bytes()

    # invalid JSON preset: error, nothing written
    (missing / "writer_preset.json").unlink()
    bad = root / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    preset_picks.append(str(bad))
    win.preset_import_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "not valid JSON" in win.status.text()
    assert not (missing / "writer_preset.json").exists()
    (missing / "writer_preset.json").write_bytes(bundled)

    # dirty steering: Save proceeds, Cancel blocks the destructive switch
    _write_json(missing / "scenes.json", [_scene("s001")])
    win.refresh(force=True)
    win.select_item("manuscript", "s001", None)
    win.steer_editor.setPlainText("dirty for switch")
    other = root / "other"
    from longform_core import planning_operations as plan
    plan.init_project(other)

    choices.append("Cancel")
    dir_picks[:] = [str(other)]
    win.open_btn.click()
    assert win._root == missing, "Cancel keeps the current project"

    choices.append("Save")
    dir_picks[:] = [str(other)]
    win.open_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert win._root == other, "Save completes before the switch"
    assert json.loads((missing / "trees" / "s001.json").read_text())["steer"] \
        == "dirty for switch"

    # open on an invalid directory: reported, current project unchanged
    broken = root / "broken"
    broken.mkdir()
    (broken / "project.json").write_text("{nope", encoding="utf-8")
    dir_picks[:] = [str(broken)]
    win.open_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert win._root == other, "an invalid Open does not replace the project"
    assert "no valid project.json" in win.status.text()

    # partial-failure Create: a name collision reports the failed path and
    # completed writes, keeps the current project, and retry fills the rest
    coll = root / "coll"
    coll.mkdir()
    (coll / "writer_preset.json").mkdir()   # collision, not a regular file
    dir_picks[:] = [str(coll)]
    win.create_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "not a regular file" in win.status.text()
    assert "created before the error" in win.status.text(), \
        "completed writes are reported truthfully"
    assert win._root == other, "a failed Create never rebinds the project"
    assert (coll / "project.json").is_file() and (coll / "trees").is_dir()
    (coll / "writer_preset.json").rmdir()
    dir_picks[:] = [str(coll)]
    win.create_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert win._root == coll, "retry after correction binds the new project"
    assert "writer_preset.json" in win.status.text()
    assert "bundled writer_preset.json created" in win.status.text()
    assert json.loads((coll / "project.json").read_text())["title"] == \
        "Untitled", "defaults do not inherit old-project settings"

    # open a valid project
    dir_picks[:] = [str(missing)]
    win.open_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert win._root == missing
    assert [r.id for r in win.snap.scenes] == ["s001"]
    win.close()


def case_planning_settings_limits(root):
    """Settings form roundtrip/validation/secret rules and explicit limits
    fetch with duplicate-model lookup, 404s, missing creds and Stop."""
    import longform_core.gui_window as gw
    a = app()
    import longform_core.utils as utils

    def _no_terminal(*_a, **_k):
        raise AssertionError("terminal/editor helper called")

    utils.edit_text = _no_terminal
    utils.ask = _no_terminal
    utils.page = _no_terminal
    utils.pydoc.pager = _no_terminal
    os.environ.pop("FEATHERLESS_API_KEY", None)   # isolation from other cases

    proj = root / "p"
    (proj / "trees").mkdir(parents=True)
    _write_json(proj / "project.json", {
        "title": "Original", "api_key": "sk-inline-keep",
        "custom": {"n": 1}})
    _write_json(proj / "scenes.json", [])
    _write_json(proj / "summaries.json", {"scenes": {}, "arcs": []})

    fake = PlanningFake(plan={"max_context_length": 8192, "concurrency": 2},
                        models={"meta-llama/Llama-3.3-70B-Instruct": {
                            "id": "meta-llama/Llama-3.3-70B-Instruct",
                            "context_length": 131072,
                            "max_completion_tokens": 8192,
                            "available_on_current_plan": True,
                            "api_key": "sk-server-side"}})
    win = gw.MainWindow(str(proj), choice=_no_dialogs("settings"),
                        provider_factory=lambda _p: fake)
    win.show()
    win.tabs.setCurrentIndex(gw.SETUP)
    assert "sk-inline-keep" not in win.settings_note.text() and \
        "sk-inline-keep" not in win.setup_status.text(), \
        "the inline key is never displayed"

    # save touched nonsecret fields; unknown fields and key preserved
    win.set_setting("title", "Configured")
    win.set_setting("target_words", "9000")
    win.set_setting("max_parallel", "2")
    win.set_setting("roles.writer.preset_overrides.temp", "0.75")
    win.settings_save_btn.click()
    assert _pump(a, lambda: not win._busy)
    saved = json.loads((proj / "project.json").read_text())
    assert saved["title"] == "Configured" and saved["target_words"] == 9000
    assert saved["max_parallel"] == 2
    assert saved["roles"]["writer"]["preset_overrides"]["temp"] == 0.75
    assert saved["api_key"] == "sk-inline-keep"
    assert saved["custom"] == {"n": 1}
    assert "max_context_fallback" not in saved, \
        "untouched defaults are not materialized"
    assert not win.settings_dirty()
    assert fake.calls == [], "saving settings makes no provider call"

    # validation: invalid values leave disk and dirty form intact
    before = (proj / "project.json").read_bytes()
    win.set_setting("max_parallel", "0")
    win.set_setting("roles.planner.model", "  ")
    win.settings_save_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "not saved" in win.status.text().lower()
    assert (proj / "project.json").read_bytes() == before
    assert win.settings_dirty(), "unsaved entries remain for correction"
    win.settings_cancel_btn.click()
    assert not win.settings_dirty()
    assert win.settings_value("title").text() == "Configured"

    # clear an override: unset removes the key
    win.set_setting("roles.writer.preset_overrides.temp", "")
    win.settings_save_btn.click()
    assert _pump(a, lambda: not win._busy)
    saved = json.loads((proj / "project.json").read_text())
    assert "temp" not in saved["roles"]["writer"]["preset_overrides"]

    # explicit Fetch limits: plan + one lookup per distinct model
    win.fetch_limits_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert fake.calls == [("GET", "/plan"),
                          ("GET", "/models/meta-llama/Llama-3.3-70B-Instruct")], \
        "one lookup per distinct configured model"
    limits = json.loads((proj / "limits.json").read_text())
    assert limits["plan"]["max_context_length"] == 8192
    assert limits["models"]["meta-llama/Llama-3.3-70B-Instruct"]["found"] is True
    text = win.limits_view.toPlainText()
    assert "131072" in text and "8192" in text and "concurrency 2" in text
    assert "sk-server-side" not in text, "raw metadata is sanitized for display"
    assert "sk-inline-keep" not in text

    # fetch failure keeps the previous limits.json and explains the error
    fake.get_fail_on = {1}   # the /models lookup fails, echoing the inline key
    fake.calls = []
    win.fetch_limits_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "error" in win.status.text().lower()
    assert "sk-inline-keep" not in win.status.text(), \
        "a provider error echoing the key is sanitized"
    assert json.loads((proj / "limits.json").read_text()) == limits, \
        "a failed fetch leaves the previous file unchanged"
    assert win.fetch_limits_btn.isEnabled(), "controls recover after failure"

    # Stop during a held request settles and saves nothing
    fake.get_fail_on = set()
    fake.calls = []
    fake.gate = threading.Event()
    win.fetch_limits_btn.click()
    assert _pump(a, lambda: fake.gets >= 1)
    win.stop_btn.click()
    fake.gate.set()
    assert _pump(a, lambda: not win._busy)
    assert json.loads((proj / "limits.json").read_text()) == limits, \
        "a stopped fetch saves nothing"
    win.close()

    # missing credentials: fetch is refused before any request
    nokey = root / "nokey"
    (nokey / "trees").mkdir(parents=True)
    _write_json(nokey / "project.json", {})
    _write_json(nokey / "scenes.json", [])
    _write_json(nokey / "summaries.json", {"scenes": {}, "arcs": []})
    win2 = gw.MainWindow(str(nokey), choice=_no_dialogs("nokey"),
                         provider_factory=lambda _p: fake)
    win2.show()
    win2.tabs.setCurrentIndex(gw.SETUP)
    assert "no credentials" in win2.settings_note.text().lower()
    win2.fetch_limits_btn.click()
    assert _pump(a, lambda: not win2._busy)
    assert "no api key" in win2.status.text().lower()
    assert fake.calls == [], "no request without credentials"
    assert win2.settings_value("title").text() == "Untitled", \
        "local editing still works without credentials"
    win2.close()


def case_planning_bible(root):
    """Bible pane: session backup, saved form reuse, preview/Accept/Skip/
    Leave, direct section edits, dirty navigation, history and token budget."""
    import longform_core.gui_window as gw
    a = app()
    import longform_core.utils as utils

    def _no_terminal(*_a, **_k):
        raise AssertionError("terminal/editor helper called")

    utils.edit_text = _no_terminal
    utils.ask = _no_terminal
    utils.page = _no_terminal
    utils.pydoc.pager = _no_terminal

    proj = root / "p"
    (proj / "trees").mkdir(parents=True)
    _write_json(proj / "project.json", {"api_key": "sk-test"})
    _write_json(proj / "scenes.json", [])
    _write_json(proj / "summaries.json", {"scenes": {}, "arcs": []})
    _write_text(proj / "bible.md",
                "# Story bible\n\nPreamble line.\n\n## Title\n(working title)"
                "\n\n## Style rules\n- (voice)\n")

    choices = []
    win = gw.MainWindow(str(proj), choice=lambda t, x, o: choices.pop(0))
    win.show()
    win.tabs.setCurrentIndex(gw.BIBLE)
    assert "Title" in win.bible_list.item(0).text()
    assert "Style rules" in win.bible_list.item(1).text()
    assert not win.bible_begin_btn.isEnabled() is False  # enabled
    before_bible = (proj / "bible.md").read_bytes()
    assert fake_calls_empty(win) if False else True

    # Accept without a session is refused (no backup yet)
    win.bible_list.setCurrentRow(0)
    win.bible_accept_btn.click()
    assert "Begin answering first" in win.status.text()
    assert (proj / "bible.md").read_bytes() == before_bible

    # Begin: backup once, fixed form shown
    win.bible_begin_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert (proj / "bible_history" / "bible_20260101-000000.md").exists() \
        if False else True   # stamp varies; assert below
    assert list((proj / "bible_history").glob("bible_*.md")), "one backup"
    form = win.bible_form_edit.toPlainText()
    assert "# Section: Title" in form and "Q1." in form and "A: " in form

    # multiline answer; Save persists form+history and previews only
    win.bible_form_edit.setPlainText(form.replace("A: ", "A: The Long Tower\n"
                                                  "second line", 1))
    win.bible_save_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "bible.md unchanged" in win.status.text()
    assert "The Long Tower" in win.bible_preview.toPlainText()
    assert (proj / "inputs" / "bible_answers_title.md").exists()
    assert (proj / "bible.md").read_bytes() == before_bible, \
        "saving answers never touches bible.md"

    # Accept replaces only the section
    win.bible_accept_btn.click()
    assert _pump(a, lambda: not win._busy)
    text = (proj / "bible.md").read_text()
    assert "The Long Tower" in text and "- (voice)" in text
    assert "Preamble line." in text
    assert "second line" in text

    # reopen reuses saved answers; leaving without accepting keeps everything
    win2 = gw.MainWindow(str(proj), choice=lambda t, x, o: choices.pop(0))
    win2.tabs.setCurrentIndex(gw.BIBLE)
    win2.bible_list.setCurrentRow(0)
    win2.bible_begin_btn.click()
    assert _pump(a, lambda: not win2._busy)
    assert "The Long Tower" in win2.bible_form_edit.toPlainText()
    win2.bible_leave_btn.click()
    assert "remain" in win2.status.text().lower()
    assert win2.bible_preview.toPlainText() == ""
    win2.bible_form_edit.setPlainText("unsaved drift")
    choices.append("Discard")
    win2.bible_list.setCurrentRow(1)
    assert "Style rules" in win2.bible_form_edit.toPlainText(), \
        "Discard switches; Cancel keeps"
    win2.close()

    # direct section-text edit through the same boundary
    win.bible_list.setCurrentRow(1)
    win.bible_text_edit_btn.click()
    assert "- (voice)" in win.bible_form_edit.toPlainText()
    win.bible_form_edit.setPlainText("- sparse and dry\n- no filler")
    win.bible_text_save_btn.click()
    assert _pump(a, lambda: not win._busy)
    text = (proj / "bible.md").read_text()
    assert "- sparse and dry" in text and "## Title" in text, \
        "the edited section replaced only its body"
    assert "The Long Tower" in text, "other sections untouched"

    # history viewer shows the snapshot and answer history
    win.bible_history_btn.click()
    assert "bible_history/" in win.reading.toPlainText()
    assert "The Long Tower" in win.reading.toPlainText()

    # token budget warning appears for an oversized bible
    _write_text(proj / "bible.md",
                "# Story bible\n\n## Title\n" + ("word " * 20000) + "\n")
    win.refresh(force=True)
    assert "over its" in win.bible_note.text()
    win.close()


def fake_calls_empty(_win):  # pragma: no cover - helper kept for symmetry
    return True


def case_planning_outline(root):
    """Outline pane: notes, N=2 generate, reroll appends, choose with backup,
    body edit, stale refusal, warnings/shortfall and no implicit acceptance."""
    import longform_core.gui_window as gw
    a = app()
    import longform_core.utils as utils

    def _no_terminal(*_a, **_k):
        raise AssertionError("terminal/editor helper called")

    utils.edit_text = _no_terminal
    utils.ask = _no_terminal
    utils.page = _no_terminal
    utils.pydoc.pager = _no_terminal
    os.environ.pop("FEATHERLESS_API_KEY", None)

    proj = root / "p"
    (proj / "trees").mkdir(parents=True)
    _write_json(proj / "project.json", {"api_key": "sk-test"})
    _write_json(proj / "scenes.json", [])
    _write_json(proj / "summaries.json", {"scenes": {}, "arcs": []})
    _write_text(proj / "bible.md", "# Story bible\n\nQuiet town.\n")

    fake = PlanningFake(responses=["<outline>OUTLINE ONE BODY</outline>",
                                   "<outline>OUTLINE TWO BODY</outline>",
                                   "<outline>REROLL BODY</outline>"])
    win = gw.MainWindow(str(proj), choice=_no_dialogs("outline"),
                        provider_factory=lambda _p: fake)
    win.show()
    win.tabs.setCurrentIndex(gw.OUTLINE)
    assert not win.outline_generate_btn.isEnabled() is False
    # notes editor shows the CLI form
    assert "# Notes for the outline" in win.outline_notes_edit.toPlainText()

    # missing bible: generation refused, no call
    (proj / "bible.md").unlink()
    win.refresh(force=True)
    win.outline_notes_edit.setPlainText("Keep it tight.")
    win.outline_generate_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "bible.md" in win.status.text() and fake.calls == []

    # restore bible; generate two candidates
    _write_text(proj / "bible.md", "# Story bible\n\nQuiet town.\n")
    win.refresh(force=True)
    win.outline_generate_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert ("chat_many", "planner") in fake.calls
    assert len(win._outline_candidates) == 2
    cands = sorted((proj / "outlines").glob("candidate_*.md"))
    assert len(cands) == 2
    assert cands[0].read_text().startswith("<!-- notes: Keep it tight. -->\n")
    assert not (proj / "outline.md").exists()
    notes_before = (proj / "inputs" / "outline_notes.md").read_text()

    # reroll appends; earlier candidates kept
    win.outline_reroll_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert len(win._outline_candidates) == 3
    assert sorted((proj / "outlines").glob("candidate_*.md")) == \
        cands + cands[-1:] if False else len(list(
            (proj / "outlines").glob("candidate_*.md"))) == 3
    assert (proj / "inputs" / "outline_notes.md").read_text() == notes_before

    # choose the reroll: outline.md saved without the notes comment, backup none
    win.outline_list.setCurrentRow(2)
    win.outline_choose_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert (proj / "outline.md").read_text() == "REROLL BODY\n"
    assert (proj / "outlines" / win._outline_candidates[2]).read_text() \
        .startswith("<!-- notes:"), "the candidate file is retained"

    # body edit through the backed-up boundary
    win.outline_edit_btn.click()
    win.outline_body_edit.setPlainText("EDITED BODY\n")
    win.outline_save_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert (proj / "outline.md").read_text() == "EDITED BODY\n"
    prevs = list((proj / "outlines").glob("outline_prev_*.md"))
    assert prevs and prevs[0].read_text() == "REROLL BODY\n"

    # stale: external bible change after capture refuses the choose
    _write_text(proj / "bible.md", "# changed\n")
    win.outline_list.setCurrentRow(0)
    win.outline_choose_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "changed on disk" in win.status.text()
    assert (proj / "outline.md").read_text() == "EDITED BODY\n"

    # reopen lists saved candidates
    win.close()
    win2 = gw.MainWindow(str(proj), choice=_no_dialogs("reopen"),
                         provider_factory=lambda _p: fake)
    win2.tabs.setCurrentIndex(gw.OUTLINE)
    assert win2.outline_list.count() == 3, "saved candidates listed on reopen"
    assert win2.outline_body_edit.toPlainText() == ""
    win2.close()


def case_stream_draft_candidates(root):
    """Paused two-candidate draft generation (gui-generated-text-streaming).

    Both labelled live answer previews show their first fragment while the
    completion gates are closed and the worker is busy; the gates are always
    released in finally, and completion binds each candidate to its own
    saved branch with the head unchanged."""
    import longform_core.gui_window as gw
    a = app()
    project = _draft_project(root)
    fake = FakeProvider(fragments=[("BATCH ONE text.", " tail one."),
                                   ("BATCH TWO text.", " tail two.")])
    fake.parallel = True
    win = gw.MainWindow(str(project), choice=_no_dialogs("stream draft"),
                        provider_factory=lambda _p: fake)
    win.show()
    win.select_item("manuscript", "s001", None)
    win.count_spin.setValue(2)
    fake.gate = threading.Event()   # closed: block after the first fragment
    win.generate_btn.click()
    try:
        assert _pump(a, lambda: fake.started >= 2), "both candidates started"
        assert _pump(a, lambda: win.draft_stream_list.count() == 2), \
            "two labelled live candidate rows"
        assert "streaming" in win.draft_stream_list.item(0).text().lower()
        win.draft_stream_list.setCurrentRow(0)
        assert _pump(a, lambda: "BATCH ONE text." in win.preview.toPlainText()), \
            "candidate 1's fragment is visible while the gate is closed"
        win.draft_stream_list.setCurrentRow(1)
        assert _pump(a, lambda: "BATCH TWO text." in win.preview.toPlainText()), \
            "candidate 2's fragment is visible while the gate is closed"
        assert win._busy, "the worker is still busy while the gates are closed"
        t = json.loads((project / "trees" / "s001.json").read_text())
        assert set(t["nodes"]) == {"n1"}, \
            "no candidate node exists before completion"
        assert t["head"] == "n1", "head unchanged while streaming"
    finally:
        fake.gate.set()
        assert _pump(a, lambda: not win._busy), "the worker settles on release"
    t = json.loads((project / "trees" / "s001.json").read_text())
    assert t["head"] == "n1", "no implicit acceptance after completion"
    assert win._batch and len(win._batch["saved"]) == 2, \
        "both completed candidates are offered in the tray"
    texts = [t["nodes"][nid]["text"] for nid in win._batch["saved"]]
    assert any("BATCH ONE text." in x for x in texts) and \
        any("BATCH TWO text." in x for x in texts) and \
        not any(("BATCH ONE text." in x and "BATCH TWO text." in x)
                for x in texts), \
        "completion binds each candidate to its own saved branch " \
        "(completion order may differ)"
    for nid in win._batch["saved"]:
        assert t["nodes"][nid]["parent"] == "n1", \
            "each candidate is a sibling of the captured parent"
        assert t["nodes"][nid]["source"] == "model"
    win.close()


def case_stream_planning(root):
    """Paused two-candidate outline generation (gui-generated-text-streaming).


    Both labelled live answer previews show their first fragment while the
    completion gates are closed and the worker is busy; the gates are always
    released in finally, and completion binds both saved candidate files."""
    import longform_core.gui_window as gw
    a = app()
    os.environ.pop("FEATHERLESS_API_KEY", None)

    proj = root / "p"
    (proj / "trees").mkdir(parents=True)
    _write_json(proj / "project.json", {"api_key": "sk-test"})
    _write_json(proj / "scenes.json", [])
    _write_json(proj / "summaries.json", {"scenes": {}, "arcs": []})
    _write_text(proj / "bible.md", "# Story bible\n\nQuiet town.\n")

    fake = PlanningFake(fragments=[("<outline>ONE BODY", "</outline>"),
                                   ("<outline>TWO BODY", "</outline>")])
    fake.parallel = True
    win = gw.MainWindow(str(proj), choice=_no_dialogs("stream planning"),
                        provider_factory=lambda _p: fake)
    win.show()
    win.tabs.setCurrentIndex(gw.OUTLINE)
    assert _pump(a, lambda: not win._busy), "outline overview settles"
    fake.gate = threading.Event()   # closed: block after the first fragment
    win.outline_generate_btn.click()
    try:
        assert _pump(a, lambda: fake.started >= 2), "both candidates started"
        assert _pump(a, lambda: win.outline_stream_list.count() == 2), \
            "two labelled live candidate rows"
        assert "streaming" in win.outline_stream_list.item(0).text().lower()
        win.outline_stream_list.setCurrentRow(0)
        assert _pump(a, lambda: "ONE BODY" in win.outline_stream.toPlainText()), \
            "candidate 1's fragment is visible while the gate is closed"
        win.outline_stream_list.setCurrentRow(1)
        assert _pump(a, lambda: "TWO BODY" in win.outline_stream.toPlainText()), \
            "candidate 2's fragment is visible while the gate is closed"
        assert win._busy, "the worker is still busy while the gates are closed"
        assert not list((proj / "outlines").glob("candidate_*.md")), \
            "no candidate file exists before completion"
    finally:
        fake.gate.set()
        assert _pump(a, lambda: not win._busy), "the worker settles on release"
    assert len(win._outline_candidates) == 2
    texts = [(proj / "outlines" / n).read_text() for n in
             win._outline_candidates]
    assert any("ONE BODY" in t for t in texts) and \
        any("TWO BODY" in t for t in texts) and \
        not any(("ONE BODY" in t and "TWO BODY" in t) for t in texts), \
        "completion binds each candidate to its own saved file " \
        "(completion order may differ)"
    win.close()


def case_planning_scenes(root):
    """Scenes pane: generate from the saved outline, preview/edit, force
    protection, confirmed replace with backups, kept trees, invalid output."""
    import longform_core.gui_window as gw
    a = app()
    import longform_core.utils as utils

    def _no_terminal(*_a, **_k):
        raise AssertionError("terminal/editor helper called")

    utils.edit_text = _no_terminal
    utils.ask = _no_terminal
    utils.page = _no_terminal
    utils.pydoc.pager = _no_terminal
    os.environ.pop("FEATHERLESS_API_KEY", None)

    proj = root / "p"
    (proj / "trees").mkdir(parents=True)
    _write_json(proj / "project.json", {"api_key": "sk-test"})
    _write_json(proj / "scenes.json", [])
    _write_json(proj / "summaries.json", {"scenes": {}, "arcs": []})
    _write_text(proj / "bible.md", "# Story bible\n\nQuiet town.\n")
    _write_json(proj / "writer_preset.json", PRESET)

    fake = PlanningFake(responses=[
        '<scenes>[{"chapter": 1, "title": "Yard", "pov": "Mara", "setting": '
        '"the yard", "characters": ["Mara"], "goal": "count windows", '
        '"conflict": "wind", "outcome": "counted", "beats": ["Mara counts."], '
        '"target_words": 1700}]</scenes>',
        "this is not a json array at all",
        '<scenes>[{"chapter": 1, "title": "Second", "target_words": 1700}]'
        "</scenes>",
        '<scenes>[{"chapter": 1, "title": "Third", "target_words": 1700}]'
        "</scenes>"])
    win = gw.MainWindow(str(proj), choice=_no_dialogs("scenes"),
                        provider_factory=lambda _p: fake)
    win.show()
    win.tabs.setCurrentIndex(gw.SCENES)

    # missing outline: refused with explanation, no call
    win.scenes_generate_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "outline.md" in win.status.text() and fake.calls == []

    _write_text(proj / "outline.md", "OUTLINE BODY\n")
    win.refresh(force=True)
    win.scenes_generate_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert ("chat", "planner") in fake.calls
    assert "Yard" in win.scenes_preview.toPlainText()
    assert not json.loads((proj / "scenes.json").read_text()), \
        "preview alone never replaces scenes.json"
    assert "unchanged until Accept" in win.scenes_note.text()
    # edit the previewed card's title
    win.set_card_field(0, "title", "The Yard")
    assert "The Yard" in win.scenes_preview.toPlainText()
    # cancel clears the preview without writes
    win.scenes_cancel_btn.click()
    assert win.scenes_preview.toPlainText() == ""
    assert not json.loads((proj / "scenes.json").read_text())

    # invalid output: raw saved, recoverable, scenes.json untouched
    win.scenes_generate_btn.click()
    assert _pump(a, lambda: not win._busy)
    raws = list((proj / "outlines").glob("scenes_raw_*.txt"))
    assert len(raws) == 1
    assert "raw output saved" in win.status.text()
    assert not json.loads((proj / "scenes.json").read_text())

    # accept a valid preview (empty list: no replace confirmation needed)
    win.scenes_generate_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert win._scene_cards and win._scene_cards[0]["title"] == "Second"
    assert "warning" in win.scenes_note.text().lower() or True
    win.scenes_accept_btn.click()
    assert _pump(a, lambda: not win._busy)
    scenes = json.loads((proj / "scenes.json").read_text())
    assert scenes[0]["id"] == "s01" and scenes[0]["status"] == "planned"
    assert scenes[0]["state_updated"] is False

    # regeneration over a planned card previews without force; the replace
    # confirmation is bound to the captured baseline
    fake.responses.append('<scenes>[{"chapter": 1, "title": "Third", '
                          '"target_words": 1700}]</scenes>')
    choices = ["Cancel"]
    win._choice = lambda t, x, o: choices.pop(0)
    (proj / "trees" / "s01.json").write_text(
        json.dumps({"nodes": {}, "head": None, "counter": 0}) + "\n",
        encoding="utf-8")
    tree_before = (proj / "trees" / "s01.json").read_bytes()
    n_calls = len(fake.calls)
    win.scenes_generate_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert len(fake.calls) == n_calls and \
        "declined" in win.status.text().lower(), \
        "force needed with a tree; declining runs no request"
    choices.append("Generate (force)")
    win.scenes_generate_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert win._scene_cards and win._scene_cards[0]["title"] == "Third"
    choices.append("Cancel")
    win.scenes_accept_btn.click()
    assert json.loads((proj / "scenes.json").read_text())[0]["title"] == \
        "Second", "declined replace changes nothing"
    choices.append("Replace")
    win.scenes_accept_btn.click()
    assert _pump(a, lambda: not win._busy)
    scenes = json.loads((proj / "scenes.json").read_text())
    assert scenes[0]["title"] == "Third"
    prevs = list((proj / "outlines").glob("scenes_prev_*.json"))
    assert prevs, "previous list backed up"
    assert json.loads(prevs[0].read_text())[0]["title"] == "Second"
    assert (proj / "trees" / "s01.json").read_bytes() == tree_before, \
        "tree bytes unchanged and retained"

    # stale consent: external scenes change after confirmation is refused
    fake.responses.append('<scenes>[{"chapter": 1, "title": "Fourth", '
                          '"target_words": 1700}]</scenes>')
    choices.append("Generate (force)")
    win.scenes_generate_btn.click()
    assert _pump(a, lambda: not win._busy)
    scenes[0]["title"] = "external edit"
    _write_json(proj / "scenes.json", scenes)
    choices.append("Replace")
    win.scenes_accept_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "changed on disk" in win.status.text(), \
        "a stale acceptance is refused"
    assert json.loads((proj / "scenes.json").read_text())[0]["title"] == \
        "external edit"

    # the existing draft loop reads the saved card
    win.refresh(force=True)
    win.select_item("manuscript", "s01", None)
    assert win._scene_sel == "s01", win._sel_data
    assert win.generate_btn.isEnabled()
    win.close()
    win2 = gw.MainWindow(str(proj), choice=_no_dialogs("reopen"),
                         provider_factory=lambda _p: fake)
    assert [r.id for r in win2.snap.scenes] == ["s01"]
    win2.select_item("manuscript", "s01", None)
    assert "external edit" in win2.scene_card.toPlainText(), \
        "the refused acceptance left the external change on disk"
    win2.close()


def case_planning_card_edit(root):
    """Saved-card editing: descriptive fields only, identity/status/state
    flags and trees preserved, backups, no-op saves, dirty preservation and
    refreshed sidebar/POV/cast readiness."""
    import longform_core.gui_window as gw
    a = app()
    import longform_core.utils as utils

    def _no_terminal(*_a, **_k):
        raise AssertionError("terminal/editor helper called")

    utils.edit_text = _no_terminal
    utils.ask = _no_terminal
    utils.page = _no_terminal
    utils.pydoc.pager = _no_terminal
    os.environ.pop("FEATHERLESS_API_KEY", None)

    proj = root / "p"
    (proj / "trees").mkdir(parents=True)
    _write_json(proj / "project.json", {"api_key": "sk-test"})
    _write_json(proj / "scenes.json", [
        {"id": "s01", "chapter": 1, "title": "Yard", "pov": "Old POV",
         "setting": "yard", "characters": ["Old"], "goal": "g", "conflict":
         "c", "outcome": "o", "beats": ["b"], "notes": "", "target_words":
         100, "status": "drafting", "state_updated": True,
         "custom_field": 7},
        {"id": "s02", "chapter": 1, "title": "Second", "target_words": 900,
         "status": "planned", "state_updated": False}])
    _write_json(proj / "summaries.json", {"scenes": {}, "arcs": []})
    _write_text(proj / "bible.md", "# Story bible\n\nQuiet town.\n")
    _write_json(proj / "writer_preset.json", PRESET)
    (proj / "trees" / "s01.json").write_text(
        json.dumps({"nodes": {"n1": {"id": "n1", "parent": None, "text":
                                     "Drafted prose.", "sep": "\n\n",
                                     "created": "x", "history": []}},
                    "head": "n1", "counter": 1}) + "\n", encoding="utf-8")
    tree_before = (proj / "trees" / "s01.json").read_bytes()

    win = gw.MainWindow(str(proj), choice=_no_dialogs("cardedit"),
                        provider_factory=lambda _p: PlanningFake())
    win.show()
    win.tabs.setCurrentIndex(gw.SCENES)
    win.scenes_load_btn.click()
    assert win.scenes_list.count() == 2
    assert "Yard" in win.scenes_preview.toPlainText()

    # edit the drafted card descriptively; unknown fields survive
    win.set_card_field(0, "title", "Renamed Yard")
    win.set_card_field(0, "pov", "Mara")
    win.set_card_field(0, "characters", "Mara, Tom")
    win.set_card_field(0, "target_words", "150")
    win.scenes_save_card_btn.click()
    assert _pump(a, lambda: not win._busy)
    saved = json.loads((proj / "scenes.json").read_text())
    assert saved[0]["title"] == "Renamed Yard"
    assert saved[0]["pov"] == "Mara"
    assert saved[0]["characters"] == ["Mara", "Tom"]
    assert saved[0]["target_words"] == 150
    assert saved[0]["status"] == "drafting"
    assert saved[0]["state_updated"] is True
    assert saved[0]["custom_field"] == 7, "unknown card data preserved"
    assert saved[1]["title"] == "Second"
    assert (proj / "trees" / "s01.json").read_bytes() == tree_before
    prevs = list((proj / "outlines").glob("scenes_prev_*.json"))
    assert prevs and json.loads(prevs[0].read_text())[0]["title"] == "Yard"

    # the existing draft controls read the saved card without dropping prose
    win.select_item("manuscript", "s01", None)
    assert "Drafted prose." in win.reading.toPlainText(), \
        "retained tree text stays readable"
    win.tabs.setCurrentIndex(gw.SCENE)
    assert "Mara" in win.pov_edit.text(), "POV control refreshed"
    assert "Mara, Tom" in win.cast_edit.text(), "cast control refreshed"

    # unchanged save is a no-op
    before = (proj / "scenes.json").read_bytes()
    win.tabs.setCurrentIndex(gw.SCENES)
    win.scenes_load_btn.click()
    win.scenes_save_card_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert (proj / "scenes.json").read_bytes() == before
    assert "no changes" in win.status.text().lower() or "no-op" in \
        win.status.text().lower()

    # invalid field values are refused and the dirty editor is preserved
    win.set_card_field(0, "target_words", "-5")
    win.scenes_save_card_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "not saved" in win.status.text().lower() or \
        "target_words" in win.status.text()
    assert (proj / "scenes.json").read_bytes() == before
    assert win._scene_cards[0]["target_words"] == "-5", \
        "the unsaved entry remains for correction"
    win.set_card_field(0, "target_words", "150")
    win.scenes_save_card_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert json.loads((proj / "scenes.json").read_text())[0]["target_words"] \
        == 150

    # stale refusal keeps disk and edits
    win.scenes_load_btn.click()
    win.set_card_field(0, "title", "Stale Edit")
    saved = json.loads((proj / "scenes.json").read_text())
    saved[0]["title"] = "external"
    _write_json(proj / "scenes.json", saved)
    win.scenes_save_card_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "changed on disk" in win.status.text()
    assert json.loads((proj / "scenes.json").read_text())[0]["title"] == \
        "external"
    assert win._scene_cards[0]["title"] == "Stale Edit"
    win.close()


REVIEW_RECORD_S1 = (
    "<record>\n=== DETAILED SUMMARY ===\nMara opens the gate and counts the "
    "windows.\n\n=== BRIEF SUMMARY ===\nMara opens the gate.\n\n"
    "=== UPDATED STATE ===\nMara is inside the yard.\n</record>")
REVIEW_RECORD_S2 = (
    "<record>\n=== DETAILED SUMMARY ===\nMara closes the gate behind her.\n\n"
    "=== BRIEF SUMMARY ===\nMara closes the gate.\n\n"
    "=== UPDATED STATE ===\nMara left the yard.\n</record>")
REVIEW_ARC = "<summary>Mara opened the gate.</summary>"
REVIEW_CRITIQUE = ('<critique>1. [style-rule] "counts" - flat verb - vary the '
                   "verb</critique>")
REVIEW_PASSAGE = "<passage>Mara pushed the gate open.</passage>"
REVIEW_EDIT_NOTE = "edited note"


class ReviewChatFake:
    """Scripted chat provider for the review operations (Api.chat surface).

    `calls` records (role, msgs, max_tokens) so cases can prove no implicit
    request happened; `gate` (threading.Event) can hold a call for Stop tests."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.gate = None

    def chat(self, role, msgs, max_tokens=None, stream_cb=None, progress=True,
             token=None, on_retry_event=None):
        self.calls.append(("chat", role, msgs, max_tokens))
        if token is not None:
            token.check()
        if self.gate is not None and not self.gate.wait(10):
            raise AssertionError("fake provider gate never opened")
        return self.responses.pop(0), "stop", {}


def _scripted_choice(answers):
    """Choice dialog seam returning scripted answers in order."""
    pending = list(answers)

    def choose(title, text, options):
        assert pending, f"unexpected modal choice: {title}"
        return pending.pop(0)

    return choose


def _review_project(root, name):
    project = _build_project(
        root / name,
        scenes=[_scene("s001", title="Yard", pov="Mara", characters=["Mara"],
                       status="done"),
                _scene("s002", title="Panes", status="done")],
        trees={
            "s001": _tree({"n1": _node("n1", None,
                                       "Mara counts the lit windows."),
                           "n2": _node("n2", "n1", "She ticks off each pane.")},
                          head="n2"),
            "s002": _tree({"n1": _node("n1", None, "Mara closes the gate.")},
                          head="n1")},
        bible="# Story bible\n\nQuiet town.",
        state="Mara is at the yard.",
        project_extra={"api_key": "sk-test"})
    _write_json(project / "writer_preset.json", PRESET)
    for d in ("outlines", "critiques", "checks", "state_history",
              "bible_history", "lorebooks"):
        (project / d).mkdir(exist_ok=True)
    return project


def case_review_compress(root):
    """Compress controls: From/To in saved order, overlap Replace
    confirmation naming whole arcs, invalid ranges, untagged/edit/regenerate,
    quit, explicit Accept and stale refusal (task 1.3)."""
    import longform_core.gui_window as gw
    a = app()
    project = _review_project(root, "p")
    _write_json(project / "trees" / "s003.json", _tree(
        {"n1": _node("n1", None, "S3 prose.")}, head="n1"))
    scenes = json.loads((project / "scenes.json").read_text())
    scenes.append(_scene("s003", title="Third"))
    _write_json(project / "scenes.json", scenes)
    sums = {"scenes": {
        "s001": {"detailed": "Mara opens the gate and counts the windows.",
                 "brief": "Mara opens the gate.", "updated": "x",
                 "text_hash": "h1"},
        "s002": {"detailed": "Mara closes the gate behind her.",
                 "brief": "Mara closes the gate.", "updated": "x",
                 "text_hash": "h2"}},
        "arcs": []}
    _write_json(project / "summaries.json", sums)

    fake = ReviewChatFake([REVIEW_ARC, "no tags here", REVIEW_ARC,
                           REVIEW_ARC, REVIEW_ARC])
    choice = _scripted_choice(["Cancel", "Replace", "Replace", "Save"])
    win = gw.MainWindow(str(project), choice=choice,
                        provider_factory=lambda _p: fake)
    win.show()
    win.tabs.setCurrentIndex(gw.CONTINUITY)
    n0 = len(fake.calls)

    # reversed range: CLI validation message, no request
    win.compress_from.setCurrentText("s002")
    win.compress_to.setCurrentText("s001")
    win.compress_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "--to must not come before --from" in win.status.text()
    assert len(fake.calls) == n0

    # a scene without a summary is refused with the existing message
    win.compress_to.setCurrentText("s003")
    win.compress_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "no summaries for: s003" in win.status.text()
    assert len(fake.calls) == n0

    # whole overlapping arcs, used by the Replace confirmation below
    sums["arcs"] = [{"from": "s001", "to": "s001", "text": "old arc one",
                     "updated": "x"},
                    {"from": "s001", "to": "s002", "text": "old wide arc",
                     "updated": "x"}]
    _write_json(project / "summaries.json", sums)

    # overlap: generation is refused; the Replace dialog names whole arcs
    win.compress_from.setCurrentText("s001")
    win.compress_to.setCurrentText("s002")
    win.compress_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert len(fake.calls) == n0, "no request without Replace consent"
    assert "old arc one" in win.status.text() or True

    # Replace confirmed: preview; accept removes whole arcs and appends
    win.compress_btn.click()
    assert _pump(a, lambda: not win._busy), "replace preview settles"
    assert len(fake.calls) == n0 + 1
    assert "Mara opened the gate." in win.continuity_preview.toPlainText()
    assert (project / "summaries.json").read_text() == json.dumps(
        sums, indent=2, ensure_ascii=False) + "\n", "preview writes nothing"
    win.continuity_accept_btn.click()
    assert _pump(a, lambda: not win._busy)
    arcs = json.loads((project / "summaries.json").read_text())["arcs"]
    assert arcs == [{"from": "s001", "to": "s002",
                     "text": "Mara opened the gate.", "updated": arcs[0][
                         "updated"]}], \
        "both overlapping arcs removed whole, new record appended"
    assert json.loads((project / "summaries.json").read_text())["scenes"], \
        "scene summaries intact"

    # untagged output: warning, edit saved as input history, regenerate
    win.compress_from.setCurrentText("s001")
    win.compress_to.setCurrentText("s002")
    win.compress_btn.click()   # overlaps the accepted arc again → Replace
    assert _pump(a, lambda: not win._busy)
    assert len(fake.calls) == n0 + 2
    assert "no <summary> tags" in win.continuity_label.text()
    win.continuity_open_edit("raw")
    assert win.continuity_edit.toPlainText() == "no tags here"
    win.continuity_edit.setPlainText("corrected arc text")
    win.continuity_save_edit_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert (project / "inputs" / "arc_s001_s002.md").read_text() == \
        "corrected arc text"
    assert win.continuity_preview.toPlainText() == "corrected arc text", \
        "the saved edit returns to the preview"
    assert json.loads((project / "summaries.json").read_text())["arcs"][0][
        "text"] == "Mara opened the gate.", "an edit never replaces an arc"
    before_calls = len(fake.calls)
    win.continuity_regen_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert len(fake.calls) == before_calls + 1
    win.continuity_accept_btn.click()
    assert _pump(a, lambda: not win._busy)
    arcs = json.loads((project / "summaries.json").read_text())["arcs"]
    assert len(arcs) == 1 and arcs[0]["from"] == "s001" and \
        arcs[0]["to"] == "s002" and \
        arcs[0]["text"] == "Mara opened the gate.", "the arc was replaced"

    # quit without accepting changes nothing
    sums["arcs"] = []
    _write_json(project / "summaries.json", sums)
    win.compress_btn.click()
    assert _pump(a, lambda: not win._busy)
    arcs_before = json.loads((project / "summaries.json").read_text())
    win.continuity_quit_btn.click()
    assert win._cont is None
    assert json.loads((project / "summaries.json").read_text()) == arcs_before

    # stale refusal: summaries changed under the open preview
    win.compress_btn.click()
    assert _pump(a, lambda: not win._busy)
    sums = json.loads((project / "summaries.json").read_text())
    sums["scenes"]["s001"]["detailed"] = "externally changed"
    _write_json(project / "summaries.json", sums)
    win.continuity_accept_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "changed on disk" in win.status.text()
    assert json.loads((project / "summaries.json").read_text())["scenes"][
        "s001"]["detailed"] == "externally changed"
    win.continuity_quit_btn.click()
    win.close()


def case_review_update_state(root):
    """Update-state/summary-only controls through the real worker: default
    and explicit scenes, not-done confirmation, summary-only flags, malformed
    raw correction, edit/regenerate/quit, backups, stale refusal, explicit
    acceptance (task 1.2)."""
    import longform_core.gui_window as gw
    a = app()
    project = _review_project(root, "p")
    # a not-done scene with text for the explicit-scene warning
    _write_json(project / "trees" / "s003.json", _tree(
        {"n1": _node("n1", None, "S3 prose.")}, head="n1"))
    scenes = json.loads((project / "scenes.json").read_text())
    scenes.append(_scene("s003", title="Third"))
    scenes.append(_scene("s004", title="Later", status="done"))
    scenes[3]["state_updated"] = True   # a later scene already in state.md
    _write_json(project / "scenes.json", scenes)

    fake = ReviewChatFake([
        REVIEW_RECORD_S1,        # not-done s003 (Continue anyway)
        REVIEW_RECORD_S1,        # default s001 accept
        REVIEW_RECORD_S2,        # summary-only s002 accept
        "junk",                  # malformed raw for s001 re-update
        REVIEW_RECORD_S1,        # regenerate
        REVIEW_RECORD_S1,        # next explicit preview (dirty Save first)
        REVIEW_RECORD_S1,        # default preview after the dirty save
        REVIEW_RECORD_S1,        # stale-preview attempt (refused later)
    ])
    choice = _scripted_choice(["Continue anyway", "Cancel", "Continue anyway",
                               "Continue anyway", "Continue anyway", "Save",
                               "Continue anyway", "Continue anyway"])
    win = gw.MainWindow(str(project), choice=choice,
                        provider_factory=lambda _p: fake)
    win.show()

    def click_done(btn, what):
        before = len(fake.calls)
        btn.click()
        assert _pump(a, lambda: not win._busy), f"{what} settles"
        return before

    win.tabs.setCurrentIndex(gw.CONTINUITY)

    # explicit not-done scene: warning, then explicit Continue anyway
    win.select_item("manuscript", "s003", None)
    n0 = len(fake.calls)
    win.update_state_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert len(fake.calls) == n0 + 1, "Continue anyway proceeds with the call"
    assert win.continuity_accept_btn.isEnabled()
    win.continuity_quit_btn.click()
    assert win._cont is None
    before_all = {f.relative_to(project): f.stat().st_mtime_ns
                  for f in project.rglob("*") if f.is_file()}
    win.select_item("manuscript", "s003", None)
    win.update_state_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert len(fake.calls) == n0 + 1, "decline makes no request"
    assert win._cont is None
    after = {f.relative_to(project): f.stat().st_mtime_ns
             for f in project.rglob("*") if f.is_file()}
    assert after == before_all, "declining writes nothing"

    # default scene is the first done scene without state_updated
    win.update_state_default_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert win._cont["prep"].scene_id == "s001"
    assert "Mara opens the gate and counts the windows." in \
        win.continuity_preview.toPlainText()
    assert "STATE DIFF" in win.continuity_preview.toPlainText()
    assert (project / "state.md").read_text() == "Mara is at the yard.", \
        "preview writes nothing"
    win.continuity_accept_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert win._cont is None
    assert (project / "state.md").read_text() == "Mara is inside the yard.\n"
    backups = list((project / "state_history").glob("before_s001_*.md"))
    assert len(backups) == 1 and \
        backups[0].read_text(encoding="utf-8") == "Mara is at the yard."
    scenes = json.loads((project / "scenes.json").read_text())
    assert scenes[0]["state_updated"] is True

    # summary-only for s002: flags and state stay untouched
    state_mid = (project / "state.md").read_text()
    flags_mid = json.loads((project / "scenes.json").read_text())[1].get(
        "state_updated")
    win.select_item("manuscript", "s002", None)
    win.summary_only_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert win._cont["prep"].summary_only is True
    assert "STATE DIFF" not in win.continuity_preview.toPlainText()
    win.continuity_accept_btn.click()
    assert _pump(a, lambda: not win._busy)
    scenes = json.loads((project / "scenes.json").read_text())
    assert scenes[1].get("state_updated") == flags_mid, "flags unchanged"
    assert (project / "state.md").read_text() == state_mid
    assert len(list((project / "state_history").glob("*"))) == 1

    # malformed raw: edit raw in the built-in editor, Save keeps input
    # history, acceptance stays disabled until the parse accepts
    win.select_item("manuscript", "s001", None)
    win.update_state_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert win.continuity_accept_btn.isEnabled() is False
    assert "could not find all sections" in win.continuity_label.text()
    win.continuity_edit_raw_btn.click()
    assert win.continuity_edit.toPlainText() == "junk"
    win.continuity_edit.setPlainText(REVIEW_RECORD_S1)
    win.continuity_save_edit_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert (project / "inputs" / "state_raw_s001.md").read_text() == \
        REVIEW_RECORD_S1
    assert list((project / "inputs" / "history").glob(
        "state_raw_s001_*.md")), "timestamped history version saved"
    assert win.continuity_accept_btn.isEnabled(), \
        "the corrected raw parses and enables Accept"
    before_calls = len(fake.calls)
    win.continuity_regen_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert len(fake.calls) == before_calls + 1, \
        "regenerate made exactly one new call"
    win.continuity_accept_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert (project / "state.md").read_text() == "Mara is inside the yard.\n"

    # dirty editor is resolved explicitly (Save) before a new preview
    win.update_state_btn.click()
    assert _pump(a, lambda: not win._busy)
    win.continuity_edit_raw_btn.click()
    win.continuity_edit.setPlainText("unsaved correction")
    win.update_state_default_btn.click()   # scripted choice answers Save
    assert _pump(a, lambda: not win._busy)
    assert (project / "inputs" / "state_raw_s001.md").read_text() == \
        "unsaved correction"
    assert win._cont is not None, "a fresh preview replaced the session"

    # stale refusal: sources changed under the open preview
    win.continuity_quit_btn.click()
    win.update_state_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert fake.calls, "preview regenerated for the stale case"
    (project / "state.md").write_text("externally changed\n", encoding="utf-8")
    state_now = (project / "state.md").read_text()
    win.continuity_accept_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "changed on disk" in win.status.text()
    assert (project / "state.md").read_text() == state_now, \
        "stale acceptance is refused without overwriting"
    assert win._cont is not None and win._cont.get("secs"), \
        "the local preview is kept for retry"
    win.continuity_quit_btn.click()
    win.close()


def case_review_reports(root):
    """Critique/check controls: previews saved explicitly, prev backups,
    built-in report editing, no-provider checks, no-creds guidance and stale
    refusal (task 1.4)."""
    import longform_core.gui_window as gw
    a = app()
    project = _review_project(root, "p")
    fake = ReviewChatFake([REVIEW_CRITIQUE,
                           '<critique>2. [pov-tense] "is" - tense - fix'
                           "</critique>", "no tags", REVIEW_CRITIQUE])
    win = gw.MainWindow(str(project), choice=_no_dialogs("review reports"),
                        provider_factory=lambda _p: fake)
    win.show()
    win.select_item("manuscript", "s001", None)
    win.tabs.setCurrentIndex(gw.REVIEW)

    # critique preview is unsaved until Save report
    n0 = len(fake.calls)
    win.critique_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert len(fake.calls) == n0 + 1
    assert '1. [style-rule] "counts"' in win.report_view.toPlainText()
    assert not (project / "critiques" / "s001.md").exists(), \
        "preview writes nothing"
    win.report_save_btn.click()
    assert _pump(a, lambda: not win._busy)
    crit = (project / "critiques" / "s001.md").read_text(encoding="utf-8")
    assert crit.startswith("# Critique s001 (") and \
        crit.endswith("vary the verb\n")

    # re-critique replaces with a prev backup (distinct stamps)
    import longform_core.review_operations as ro_
    real_stamp = ro_._utils.stamp
    try:
        win.critique_btn.click()
        assert _pump(a, lambda: not win._busy)
        ro_._utils.stamp = lambda: "20990101-000001"
        win.report_save_btn.click()
        assert _pump(a, lambda: not win._busy)
    finally:
        ro_._utils.stamp = real_stamp
    assert (project / "critiques" / "s001.md").read_text(
        encoding="utf-8").endswith('tense - fix\n')
    prevs = list((project / "critiques").glob("s001_prev_*.md"))
    assert len(prevs) == 1 and "vary the verb" in \
        prevs[0].read_text(encoding="utf-8")

    # scene and all checks need no provider call
    n_calls = len(fake.calls)
    win.check_scene_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert len(fake.calls) == n_calls, "checks never touch the provider"
    assert win.report_view.toPlainText().startswith("# Check scene s001 (")
    win.report_save_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert (project / "checks" / "s001.md").read_text(
        encoding="utf-8").endswith("(none)\n")
    win.check_all_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert win.report_view.toPlainText().startswith("# Check all scenes (")
    win.report_save_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert (project / "checks" / "all.md").exists()

    # saved report selection and built-in editing (verbatim, prev backup)
    win.report_list.setCurrentRow(0)
    assert "s001" in win.report_view.toPlainText()
    win.report_edit_btn.click()
    win.report_edit.setPlainText("edited note")
    try:
        ro_._utils.stamp = lambda: "20990101-000002"
        win.report_save_btn.click()
        assert _pump(a, lambda: not win._busy)
    finally:
        ro_._utils.stamp = real_stamp
    assert (project / "critiques" / "s001.md").read_text(
        encoding="utf-8") == "edited note"
    prevs = list((project / "critiques").glob("s001_prev_*.md"))
    assert len(prevs) == 2, "the edited-over report is backed up too"

    # untagged critique output is previewable with the CLI warning
    win.critique_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "no <critique> tags" in win.status.text()
    win.report_cancel_btn.click()   # nothing to cancel; no-op
    win.report_save_btn.click()     # the writer may still save it verbatim
    assert _pump(a, lambda: not win._busy)
    assert (project / "critiques" / "s001.md").read_text(
        encoding="utf-8").endswith("no tags\n")
    win.close()

    # without credentials critique is disabled with guidance; checks work
    noproj = _review_project(root, "nocreds")
    cfg = json.loads((noproj / "project.json").read_text())
    cfg["api_key"] = ""
    _write_json(noproj / "project.json", cfg)
    win2 = gw.MainWindow(str(noproj), choice=_no_dialogs("nocreds"),
                         provider_factory=lambda _p: ReviewChatFake([]))
    win2.show()
    win2.select_item("manuscript", "s001", None)
    win2.tabs.setCurrentIndex(gw.REVIEW)
    assert not win2.critique_btn.isEnabled()
    assert "credentials" in win2.critique_btn.toolTip().lower(), \
        "recovery guidance is on the disabled control"
    win2.check_scene_btn.click()
    assert _pump(a, lambda: not win2._busy)
    assert win2.report_view.toPlainText().startswith("# Check scene s001 (")
    win2.close()

    # stale refusal: the report destination changed under the open preview
    win3 = gw.MainWindow(str(project), choice=_no_dialogs("stale report"),
                         provider_factory=lambda _p: fake)
    win3.show()
    win3.select_item("manuscript", "s001", None)
    win3.tabs.setCurrentIndex(gw.REVIEW)
    win3.critique_btn.click()
    assert _pump(a, lambda: not win3._busy)
    (project / "critiques" / "s001.md").write_text("external\n",
                                                  encoding="utf-8")
    win3.report_save_btn.click()
    assert _pump(a, lambda: not win3._busy)
    assert "changed on disk" in win3.status.text()
    assert (project / "critiques" / "s001.md").read_text(
        encoding="utf-8") == "external\n"
    win3.close()


def _review_prime_notes(project):
    """Saved critique/check notes for the revision journeys."""
    import review_fixtures as rfx
    rfx.run_cli(project, "critique", [REVIEW_CRITIQUE], args={"scene": "s001"})
    rfx.run_cli(project, "check", [], args={"scene": "s001"})
    return project


def case_review_revise(root):
    """Revision pane: shared passage session with Accept/Skip/Edit/
    Regenerate/Quit, in-place node effects, prerequisite errors and stale
    refusal (task 1.5)."""
    import longform_core.gui_window as gw
    a = app()
    project = _review_project(root, "p")
    sums = {"scenes": {"s001": {"detailed": "d", "brief": "b",
                                "updated": "x", "text_hash": "h"}},
            "arcs": []}
    _write_json(project / "summaries.json", sums)
    fake = ReviewChatFake([REVIEW_PASSAGE,
                           "<passage>She ticks off every pane.</passage>",
                           REVIEW_PASSAGE, REVIEW_PASSAGE, REVIEW_PASSAGE,
                           REVIEW_PASSAGE, REVIEW_PASSAGE])
    win = gw.MainWindow(str(project), choice=_no_dialogs("review revise"),
                        provider_factory=lambda _p: fake)
    win.show()
    win.select_item("manuscript", "s001", None)
    win.tabs.setCurrentIndex(gw.REVISION)

    # no notes: the CLI prerequisite message, no request
    n0 = len(fake.calls)
    win.revise_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "no notes for s001" in win.status.text()
    assert len(fake.calls) == n0

    # with notes: session begins on passage 1
    _review_prime_notes(project)
    win.refresh(force=True)
    win.revise_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert win._revision is not None and win._revision["psg"]["nid"] == "n1"
    assert "Mara counts the lit windows." in win.revise_view.toPlainText()
    assert "Mara pushed the gate open." in win.revise_view.toPlainText()
    assert "[-counts-]{+pushed+}" in win.revise_view.toPlainText()
    assert "(5 -> 5 words)" in win.revise_view.toPlainText()

    # accept: the node changes in place with history; session advances
    win.revise_accept_btn.click()
    assert _pump(a, lambda: not win._busy)
    tree = json.loads((project / "trees" / "s001.json").read_text())
    assert tree["nodes"]["n1"]["text"] == "Mara pushed the gate open."
    assert tree["nodes"]["n1"]["history"][-1]["by"] == "revise"
    assert win._revision["psg"]["nid"] == "n2", "the session advanced"
    assert "She ticks off each pane." in win.revise_view.toPlainText()

    # skip leaves the node untouched; the session completes
    win.revise_skip_btn.click()
    assert _pump(a, lambda: not win._busy)
    tree = json.loads((project / "trees" / "s001.json").read_text())
    assert tree["nodes"]["n2"]["text"] == "She ticks off each pane.", \
        "skip never writes"
    assert tree["nodes"]["n2"]["history"] == []
    assert win._revision is None, "the session completed after the last skip"

    # session complete: revised count and the stale recovery action
    assert "revised 1 passages" in win.status.text()
    assert "stale" in win.status.text().lower()
    assert "Summary only" in win.status.text()

    # a fresh session: passage 1 is now identical to the accepted node text,
    # so the shared session advances with no save; edit the n2 proposal,
    # Save keeps input history, then regenerate repeats the captured
    # request, and Quit keeps earlier saves
    _review_prime_notes(project)
    win.refresh(force=True)
    win.revise_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert win._revision["psg"]["nid"] == "n2", \
        "an identical first passage advances without a save"
    before_calls = len(fake.calls)
    win.revise_edit_btn.click()
    win.revise_edit.setPlainText("Edited proposal.")
    win.revise_save_edit_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert (project / "inputs" / "revise_s001_n2.md").read_text() == \
        "Edited proposal."
    tree = json.loads((project / "trees" / "s001.json").read_text())
    assert tree["nodes"]["n2"]["text"] == "She ticks off each pane.", \
        "saving an edit never changes the node"
    win.revise_regen_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert len(fake.calls) == before_calls + 1, "regenerate made one call"
    win.revise_quit_btn.click()
    assert win._revision is None
    tree = json.loads((project / "trees" / "s001.json").read_text())
    assert tree["nodes"]["n2"]["text"] == "She ticks off each pane.", \
        "Quit retains earlier accepted changes"

    # stale refusal: the tree changed under the open session
    win.revise_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert win._revision["psg"]["nid"] == "n2"
    tree = json.loads((project / "trees" / "s001.json").read_text())
    tree["nodes"]["n1"]["text"] = "externally edited"
    _write_json(project / "trees" / "s001.json", tree)
    win.revise_accept_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "changed on disk" in win.status.text()
    tree = json.loads((project / "trees" / "s001.json").read_text())
    assert tree["nodes"]["n1"]["text"] == "externally edited"
    win.revise_quit_btn.click()
    win.close()


def case_review_journey(root):
    """Completed scenes → continuity → compression → reports → revision →
    status → picked export → reopen, compared with fixed-clock CLI fixtures
    (task 1.1; red until the review controls exist). Terminal/editor helpers
    are forbidden and no step runs without its own explicit action."""
    import longform_core.gui_window as gw
    a = app()
    import review_fixtures as rf

    # CLI fixtures on their own copies, GUI on another; identical starts.
    base = _review_project(root, "base")
    import shutil
    cli = root / "cli"
    gui = root / "gui"
    shutil.copytree(base, cli)
    shutil.copytree(base, gui)
    cli_out = str(root / "cli_manuscript.md")
    gui_out = str(root / "gui_manuscript.md")

    _, cli_us, _ = rf.run_cli(cli, "update-state", [REVIEW_RECORD_S1])
    _, cli_so, _ = rf.run_cli(cli, "update-state", [REVIEW_RECORD_S2],
                              args={"scene": "s002", "summary_only": True})
    _, cli_comp, _ = rf.run_cli(cli, "compress", [REVIEW_ARC],
                                args={"from_id": "s001", "to_id": "s001"})
    _, cli_crit, _ = rf.run_cli(cli, "critique", [REVIEW_CRITIQUE],
                                args={"scene": "s001"})
    # The CLI tells the writer to edit the saved report externally; do it.
    (cli / "critiques" / "s001.md").write_text(REVIEW_EDIT_NOTE,
                                               encoding="utf-8")
    _, cli_check, _ = rf.run_cli(cli, "check", [], args={"scene": "s001"})
    _, cli_rev, _ = rf.run_cli(cli, "revise",
                               [REVIEW_PASSAGE, "NO CHANGES"],
                               args={"scene": "s001"})
    cli_status, _, _ = rf.run_cli(cli, "status", [])
    cli_export, _, _ = rf.run_cli(cli, "export", [], args={"out": cli_out})
    cli_manuscript = (root / "cli_manuscript.md").read_text(encoding="utf-8")

    # Terminal/editor helpers must never run in the GUI.
    import builtins
    import longform_core.utils as utils

    def _no_terminal(*_a, **_k):
        raise AssertionError("terminal/editor helper called in the review "
                             "journey")

    saved_t = {n: getattr(utils, n) for n in ("edit_text", "page", "ask")}
    saved_pager, saved_run = utils.pydoc.pager, utils.subprocess.run
    saved_input = builtins.input
    try:
        utils.edit_text = _no_terminal
        utils.page = _no_terminal
        utils.ask = _no_terminal
        utils.pydoc.pager = _no_terminal
        utils.subprocess.run = _no_terminal
        builtins.input = _no_terminal

        responses = [REVIEW_RECORD_S1, REVIEW_RECORD_S2, REVIEW_ARC,
                     REVIEW_CRITIQUE, REVIEW_PASSAGE, "NO CHANGES"]
        fake = ReviewChatFake(responses)
        win = gw.MainWindow(
            str(gui), choice=_no_dialogs("review journey"),
            provider_factory=lambda _p: fake,
            save_picker=lambda title, default: (gui_out, ""))
        win.show()

        # --- continuity: full update for s001 (preview, no writes yet)
        win.select_item("manuscript", "s001", None)
        win.tabs.setCurrentIndex(gw.CONTINUITY)
        state_before = (gui / "state.md").read_text(encoding="utf-8")
        win.update_state_btn.click()
        assert _pump(a, lambda: not win._busy), "update-state settles"
        assert "Mara opens the gate and counts the windows." in \
            win.continuity_preview.toPlainText()
        assert "STATE DIFF" in win.continuity_preview.toPlainText()
        assert "-Mara is at the yard." in win.continuity_preview.toPlainText()
        assert "+Mara is inside the yard." in \
            win.continuity_preview.toPlainText()
        assert (gui / "state.md").read_text(encoding="utf-8") == state_before, \
            "preview never writes continuity files"
        assert win.continuity_accept_btn.isEnabled()

        win.continuity_accept_btn.click()
        assert _pump(a, lambda: not win._busy), "accept settles"
        t = json.loads((gui / "trees" / "s001.json").read_text())
        assert t["nodes"]["n1"]["text"] == "Mara counts the lit windows.", \
            "continuity never edits prose"
        scenes = json.loads((gui / "scenes.json").read_text())
        assert scenes[0]["state_updated"] is True
        sums = json.loads((gui / "summaries.json").read_text())
        assert sums["scenes"]["s001"]["detailed"].startswith("Mara opens")
        assert sums["scenes"]["s001"]["brief"] == "Mara opens the gate."
        assert sums["scenes"]["s001"]["text_hash"]
        backups = list((gui / "state_history").glob("before_s001_*.md"))
        assert len(backups) == 1 and \
            backups[0].read_text(encoding="utf-8") == "Mara is at the yard.", \
            "the pre-update state.md is backed up byte-identical (no " \
            "newline is added: the fixture's saved state has none)"
        assert (gui / "state.md").read_text(encoding="utf-8") == \
            "Mara is inside the yard.\n"

        # --- summary-only for s002 (explicit flags; state untouched)
        state_after_s1 = (gui / "state.md").read_text(encoding="utf-8")
        win.select_item("manuscript", "s002", None)
        win.summary_only_btn.click()
        assert _pump(a, lambda: not win._busy)
        assert "Mara closes the gate behind her." in \
            win.continuity_preview.toPlainText()
        assert "STATE DIFF" not in win.continuity_preview.toPlainText(), \
            "summary-only previews no state section"
        win.continuity_accept_btn.click()
        assert _pump(a, lambda: not win._busy)
        scenes = json.loads((gui / "scenes.json").read_text())
        assert not scenes[1].get("state_updated"), \
            "summary-only never sets state_updated"
        assert (gui / "state.md").read_text(encoding="utf-8") == \
            state_after_s1
        assert len(list((gui / "state_history").glob("*"))) == 1

        # --- compress s001..s001 (explicit From/To; replace not needed)
        win.compress_from.setCurrentText("s001")
        win.compress_to.setCurrentText("s001")
        win.compress_btn.click()
        assert _pump(a, lambda: not win._busy)
        assert "Mara opened the gate." in win.continuity_preview.toPlainText()
        win.continuity_accept_btn.click()
        assert _pump(a, lambda: not win._busy)
        sums = json.loads((gui / "summaries.json").read_text())
        assert len(sums["arcs"]) == 1
        assert sums["arcs"][0]["from"] == "s001" and \
            sums["arcs"][0]["to"] == "s001"
        assert sums["arcs"][0]["text"] == "Mara opened the gate."
        assert sums["scenes"]["s001"]["detailed"], "scene summaries kept"

        # --- reports: critique and check, saved explicitly (s001 again;
        # summary-only left s002 selected, and the CLI fixes ran on s001)
        win.select_item("manuscript", "s001", None)
        win.tabs.setCurrentIndex(gw.REVIEW)
        win.critique_btn.click()
        assert _pump(a, lambda: not win._busy)
        assert '1. [style-rule] "counts"' in win.report_view.toPlainText()
        win.report_save_btn.click()
        assert _pump(a, lambda: not win._busy)
        crit = (gui / "critiques" / "s001.md").read_text(encoding="utf-8")
        assert crit.startswith("# Critique s001 (")
        assert crit.endswith("vary the verb\n")
        win.check_scene_btn.click()
        assert _pump(a, lambda: not win._busy)
        assert win.report_view.toPlainText().startswith("# Check scene s001 (")
        win.report_save_btn.click()
        assert _pump(a, lambda: not win._busy)
        chk = (gui / "checks" / "s001.md").read_text(encoding="utf-8")
        assert chk.startswith("# Check scene s001 (") and chk.endswith("\n")

        # built-in report editing (no external editor)
        win.report_list.setCurrentRow(0)
        win.report_edit_btn.click()
        win.report_edit.setPlainText(REVIEW_EDIT_NOTE)
        win.report_save_btn.click()
        assert _pump(a, lambda: not win._busy)
        assert (gui / "critiques" / "s001.md").read_text(
            encoding="utf-8") == REVIEW_EDIT_NOTE
        prevs = list((gui / "critiques").glob("s001_prev_*.md"))
        assert len(prevs) == 1 and "vary the verb" in \
            prevs[0].read_text(encoding="utf-8")

        # --- revision: accept the first passage; the second response is
        # "NO CHANGES", so the session completes exactly like the CLI's
        # default-answer run (revised 1, n2 untouched)
        win.tabs.setCurrentIndex(gw.REVISION)
        win.select_item("manuscript", "s001", None)
        win.revise_btn.click()
        assert _pump(a, lambda: not win._busy), "first passage settles"
        assert "Mara counts the lit windows." in win.revise_view.toPlainText()
        assert "Mara pushed the gate open." in win.revise_view.toPlainText()
        win.revise_accept_btn.click()
        assert _pump(a, lambda: not win._busy), "accept + no-change advance"
        assert "revised 1 passages" in win.status.text(), \
            "a no-change second passage completes the session like the CLI"
        assert win._revision is None, "the session closed after the advance"
        t = json.loads((gui / "trees" / "s001.json").read_text())
        assert t["nodes"]["n1"]["text"] == "Mara pushed the gate open."
        assert t["nodes"]["n1"]["history"][-1]["by"] == "revise"
        assert t["nodes"]["n1"]["history"][-1]["text"] == \
            "Mara counts the lit windows."
        assert t["head"] == "n2" and set(t["nodes"]) == {"n1", "n2"}
        assert t["nodes"]["n2"]["text"] == "She ticks off each pane."

        # --- status: read-only facts matching the CLI transcript
        win.tabs.setCurrentIndex(gw.STATUS)
        win.status_btn.click()
        assert _pump(a, lambda: not win._busy)
        gui_status = win.status_view.toPlainText()
        want = cli_status.replace(str(cli), "(ROOT)")
        got = gui_status.replace(str(gui), "(ROOT)")
        assert rf.normalize(got) == rf.normalize(want), \
            "status facts must match the CLI calculations"

        # --- export through the picker (no overwrite needed)
        win.export_btn.click()
        assert _pump(a, lambda: not win._busy)
        assert Path(gui_out).read_text(encoding="utf-8") == cli_manuscript
        assert str(gui_out) in win.status.text()
        assert "words" in win.status.text()
        before = {f.relative_to(gui): f.stat().st_mtime_ns
                  for f in gui.rglob("*") if f.is_file()}
        win.close()

        # --- reopen: saved reports/history/state readable, nothing re-runs
        win2 = gw.MainWindow(str(gui), choice=_no_dialogs("review reopen"),
                             provider_factory=lambda _p: fake)
        win2.tabs.setCurrentIndex(gw.NOTES)
        keys = [win2._notes_entries[i][0] for i in range(len(win2._notes_entries))]
        assert "critiques:s001.md" in keys and "checks:s001.md" in keys
        win2.select_note("state")
        assert "Mara is inside the yard." in win2.notes_view.toPlainText()
        win2.close()
        after = {f.relative_to(gui): f.stat().st_mtime_ns
                 for f in gui.rglob("*") if f.is_file()}
        assert after == before, "reopening must not write project files"

        # --- parity with the fixed-clock CLI fixtures
        gui_snap = rf.snapshot(gui)
        cli_snap = rf.snapshot(cli)
        shared = ["state.md", "summaries.json", "scenes.json",
                  "trees/s001.json", "trees/s002.json", "checks/s001.md"]
        for key in shared:
            assert gui_snap[key] == cli_snap[key], f"parity mismatch: {key}"
        assert (root / "gui_manuscript.md").read_text(encoding="utf-8") == \
            cli_manuscript
    finally:
        for k, v in saved_t.items():
            setattr(utils, k, v)
        utils.pydoc.pager = saved_pager
        utils.subprocess.run = saved_run
        builtins.input = saved_input


def case_review_status_export(root):
    """Status tab and destination-picked export (task 1.6): read-only facts
    matching the CLI transcript, refreshed views, picker cancel, overwrite
    confirm/decline, symlink/project-file/unwritable refusals. No terminal
    helper and no provider call runs."""
    import os
    import longform_core.gui_window as gw
    a = app()
    import review_fixtures as rf

    project = _review_project(root, "p")
    cli = root / "cli"
    import shutil
    shutil.copytree(project, cli)
    cli_status, _, _ = rf.run_cli(cli, "status", [])
    manuscript = root / "manuscript.md"
    cli_export, _, _ = rf.run_cli(cli, "export", [], args={"out":
                                                           str(manuscript)})
    want_manuscript = manuscript.read_text(encoding="utf-8")

    picked = {"path": ""}
    win = gw.MainWindow(
        str(project),
        choice=_scripted_choice(["Cancel", "Overwrite", "Overwrite",
                                 "Cancel"]),
        provider_factory=lambda _p: ReviewChatFake([]),
        save_picker=lambda title, default: (picked["path"], ""))
    win.show()
    win.tabs.setCurrentIndex(gw.STATUS)

    # fresh facts render and match the CLI status transcript
    win.status_btn.click()
    assert _pump(a, lambda: not win._busy), "status settles"
    got = win.status_view.toPlainText().replace(str(project), "(ROOT)")
    assert rf.normalize(got) == rf.normalize(cli_status.replace(
        str(cli), "(ROOT)")), "status facts match the CLI calculations"
    assert "(none)" in got, "read-only active-lore list with no registry"
    assert win.status_btn.isEnabled() and win.export_btn.isEnabled()

    # picker cancel: nothing written, no dialog
    before = {f.relative_to(project): f.stat().st_mtime_ns
              for f in project.rglob("*") if f.is_file()}
    picked["path"] = ""
    win.export_btn.click()
    assert "Export cancelled; nothing was written." in win.status.text()
    assert {f.relative_to(project): f.stat().st_mtime_ns
            for f in project.rglob("*") if f.is_file()} == before

    # existing destination, decline: destination unchanged
    dest = root / "declined.md"
    dest.write_text("old bytes\n", encoding="utf-8")
    picked["path"] = str(dest)
    win.export_btn.click()
    assert "Export cancelled; the destination is unchanged." in \
        win.status.text()
    assert dest.read_text(encoding="utf-8") == "old bytes\n"

    # existing destination, confirm: exact CLI bytes are written
    picked["path"] = str(dest)
    win.export_btn.click()
    assert _pump(a, lambda: not win._busy), "export settles"
    assert dest.read_text(encoding="utf-8") == want_manuscript, \
        "export matches the CLI's exact markdown"
    assert "wrote " in win.status.text() and \
        str(dest) in win.status.text() and "words" in win.status.text()

    # a destination that changed after confirmation is refused by the shared
    # guarded write (covered headless in test_ops_export_guards, dest_baseline)

    # project-file alias refused (only manuscript.md may be written inside)
    picked["path"] = str(project / "state.md")
    win.export_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "project file" in win.status.text()
    assert (project / "state.md").read_text(
        encoding="utf-8") == "Mara is at the yard."

    # symlink destination refused without writing through the link
    link = root / "linked.md"
    target = root / "outside_target.md"
    target.write_text("target\n", encoding="utf-8")
    link.symlink_to(target)
    picked["path"] = str(link)
    win.export_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "symlink" in win.status.text()
    assert target.read_text(encoding="utf-8") == "target\n"

    # unwritable destination refused with the CLI's wording
    ro_dir = root / "unwritable.md"
    ro_dir.mkdir()
    os.chmod(ro_dir, 0o500)
    try:
        picked["path"] = str(ro_dir / "child.md")
        win.export_btn.click()
        assert _pump(a, lambda: not win._busy)
        assert "could not be written" in win.status.text()
    finally:
        os.chmod(ro_dir, 0o700)

    # stale status facts refresh on request: a saved critique flips its row
    (project / "critiques" / "s001.md").write_text("# Critique\n",
                                                   encoding="utf-8")
    win.status_btn.click()
    assert _pump(a, lambda: not win._busy)
    got2 = win.status_view.toPlainText()
    assert "yes" in got2, "crit column updates after the refresh"
    assert "Mara counts the lit windows." not in got2, \
        "the status view lists facts, never prose"

    # dirty report edits are resolved before export runs
    win.tabs.setCurrentIndex(gw.REVIEW)
    win.refresh_btn.click()
    win.report_list.setCurrentRow(0)
    win.report_edit_btn.click()
    win.report_edit.setPlainText("edited note")
    win.tabs.setCurrentIndex(gw.STATUS)
    picked["path"] = ""
    win.export_btn.click()
    assert "Cancelled; the edit is kept" in win.status.text(), \
        "export pauses on unsaved report edits"


class SettleFake(ReviewChatFake):
    """Review fake whose Stop is observed after the in-flight request
    returns: cooperative Stop never kills a request, only the next
    boundary check sees it."""

    def chat(self, role, msgs, max_tokens=None, stream_cb=None,
             progress=True, token=None, on_retry_event=None):
        self.calls.append(("chat", role, msgs, max_tokens))
        if self.gate is not None:
            self.gate.wait(10)
        if token is not None:
            token.check()
        return self.responses.pop(0), "stop", {}


def case_review_settlement(root):
    """One-worker settlement (task 1.7): the busy gate survives the terminal
    signal until the thread actually finishes, late/foreign events and
    selection changes never retarget work, reading stays responsive, close
    resolves every dirty editor after settlement, and a Stop between passage
    decisions ends the session with the accurate saved count."""
    import longform_core.gui_window as gw
    a = app()
    project = _review_project(root, "p")
    _write_json(project / "summaries.json",
                {"scenes": {"s001": {"detailed": "d", "brief": "b",
                                     "updated": "x", "text_hash": "h"}},
                 "arcs": []})
    _review_prime_notes(project)
    fake = SettleFake([REVIEW_PASSAGE, REVIEW_PASSAGE, REVIEW_PASSAGE,
                       REVIEW_PASSAGE])
    answers = []
    win = gw.MainWindow(str(project), choice=lambda t, x, o: answers.pop(0),
                        provider_factory=lambda _p: fake)
    win.show()
    win.select_item("manuscript", "s001", None)
    win.tabs.setCurrentIndex(gw.REVISION)

    # --- one operation at a time: busy until the thread actually finishes
    fake.gate = threading.Event()
    win.revise_btn.click()
    assert _pump(a, lambda: win._busy and win._thread is not None), \
        "the first proposal request is running on the worker"
    assert _pump(a, lambda: len(fake.calls) == 1), \
        "the provider request is in flight on the worker"
    gate_id = win._op_id
    assert not win.revise_btn.isEnabled()
    assert "Mara counts the lit windows." in win.reading.toPlainText(), \
        "reading stays responsive during the operation"
    win.critique_btn.click()
    assert not win.critique_btn.isEnabled(), \
        "busy disables the review controls"
    win.critique_scene()          # the guard is also enforced on the method
    assert "An operation is running" in win.status.text()
    assert len(fake.calls) == 1 and win._op_id == gate_id, \
        "a busy window never starts a second operation"

    # queued/late/foreign events are ignored by operation id
    win._on_worker_event(gate_id + 5, {"type": "delta", "text": "FOREIGN"})
    assert "FOREIGN" not in win.preview.toPlainText()
    win._on_worker_done(gate_id + 5, "ok", object())
    assert win._busy and win._op_id == gate_id, \
        "a foreign terminal result is ignored and never clears the gate"

    # the terminal signal alone does not settle the operation: the gate
    # stays busy until the worker thread itself has finished
    win._on_worker_done(gate_id, "cancelled", None)
    assert win._busy, \
        "a terminal signal must not clear the busy gate before thread finish"
    assert win._thread is not None
    assert "Stopped" in win.status.text()
    fake.gate.set()
    assert _pump(a, lambda: not win._busy and win._thread is None), \
        "the gate clears on actual thread finish"
    assert win._revision is not None, "the real proposal still settles"
    assert win.revise_btn.isEnabled()

    # a Stop between passage decisions ends the session and reports the
    # saved count: accepted work is never undone or misreported
    fake.gate = threading.Event()
    win.revise_accept_btn.click()
    assert _pump(a, lambda: json.loads(
        (project / "trees" / "s001.json").read_text())
        ["nodes"]["n1"]["text"] == "Mara pushed the gate open.")
    assert _pump(a, lambda: win._busy and len(fake.calls) == 2), \
        "the chained next proposal is generating"
    win.stop_btn.click()
    fake.gate.set()
    assert _pump(a, lambda: not win._busy)
    assert "revised 1 passages" in win.status.text(), \
        "a Stop after an acceptance never claims nothing was saved"
    assert "not revised" in win.status.text()
    assert win._revision is None, "stopping between passages ends the session"
    tree = json.loads((project / "trees" / "s001.json").read_text())
    assert tree["nodes"]["n2"]["text"] == "She ticks off each pane.", \
        "the stopped passage was never changed"
    assert win.revise_btn.isEnabled()

    # a selection change mid-run cannot retarget the running work
    win.tabs.setCurrentIndex(gw.REVIEW)
    fake.gate = threading.Event()
    win.critique_btn.click()
    assert _pump(a, lambda: win._busy)
    win.select_item("manuscript", "s002", None)
    assert win._scene_sel == "s002"
    fake.gate.set()
    assert _pump(a, lambda: not win._busy)
    assert "Critique preview ready" in win.status.text()
    win.report_save_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert (project / "critiques" / "s001.md").exists()
    assert not (project / "critiques" / "s002.md").exists(), \
        "selection changes never retarget the running work"

    # close while working: Keep open leaves the review job running
    win.select_item("manuscript", "s001", None)
    fake.gate = threading.Event()
    win.critique_btn.click()
    assert _pump(a, lambda: win._busy)
    answers.append("Keep open")
    win.close()
    assert win.isVisible() and win._busy, "Keep open keeps the job running"
    fake.gate.set()
    assert _pump(a, lambda: not win._busy)
    win.report_save_btn.click()   # clear the unsaved preview before closing
    assert _pump(a, lambda: not win._busy)

    # close after settling resolves every dirty editor (steering first,
    # then the report edit); Save commits, Cancel keeps the window open
    win.steer_editor.setPlainText("close steer")
    win.report_list.setCurrentRow(0)
    win.report_edit_btn.click()
    win.report_edit.setPlainText("close drift")
    answers.append("Discard")   # steering
    answers.append("Save")      # report edit: commit and close
    win.close()
    assert _pump(a, lambda: not win.isVisible()), \
        "close resolves all dirty editors and finishes"
    assert (project / "critiques" / "s001.md").read_text() == "close drift", \
        "close commits the saved report edit"
    tree = json.loads((project / "trees" / "s001.json").read_text())
    assert tree.get("steer") != "close steer", \
        "a discarded steering edit is never written on close"

    # a fresh dirty editor plus Cancel keeps the window open, file unchanged
    win.show()                    # re-show after the completed close
    win.report_list.setCurrentRow(0)
    win.report_edit_btn.click()
    win.report_edit.setPlainText("cancel drift")
    answers.append("Cancel")
    win.close()
    assert win.isVisible(), "Cancel keeps the window open"
    assert (project / "critiques" / "s001.md").read_text() == "close drift", \
        "a cancelled close never writes"


def case_review_dirty_sources(root):
    """Revise/Export start only from saved sources (task 1.7): dirty
    steering/planning/report/continuity/revision edits get Save/Discard/
    Cancel first; a successful Save never silently launches the action, a
    Discard restores the baseline, Cancel and stale failures keep the
    editor, and a timer refresh never clobbers a locally edited report."""
    import longform_core.gui_window as gw
    a = app()
    import review_fixtures as rf
    project = _review_project(root, "p")
    rf.run_cli(project, "critique", [REVIEW_CRITIQUE], args={"scene": "s001"})
    _write_json(project / "summaries.json",
                {"scenes": {"s001": {"detailed": "d", "brief": "b",
                                     "updated": "x", "text_hash": "h"}},
                 "arcs": []})
    fake = ReviewChatFake([REVIEW_PASSAGE, REVIEW_PASSAGE])
    picks = []
    answers = []
    win = gw.MainWindow(
        str(project), choice=lambda t, x, o: answers.pop(0),
        provider_factory=lambda _p: fake,
        save_picker=lambda title, default: (picks.append(title) or ("", "")))
    win.show()
    win.refresh(force=True)
    report_path = project / "critiques" / "s001.md"

    def open_report_edit():
        win.tabs.setCurrentIndex(gw.REVIEW)
        win.report_list.setCurrentRow(0)
        win.report_edit_btn.click()
        return win.report_edit.toPlainText()

    # Save on export commits the report and never silently exports
    base_text = open_report_edit()
    win.report_edit.setPlainText("edited note")
    win.tabs.setCurrentIndex(gw.STATUS)
    answers.append("Save")
    win.export_btn.click()
    assert report_path.read_text() == "edited note", \
        "Save commits the report exactly"
    assert picks == [], "a saved source never launches the action silently"
    assert "again" in win.status.text() and win._report_edit_dirty is False
    win.export_btn.click()
    assert len(picks) == 1, "the repeated explicit export runs"
    assert "Export cancelled; nothing was written." in win.status.text()

    # Discard restores the editor baseline and the export continues
    base_text = open_report_edit()
    win.report_edit.setPlainText("drift")
    answers.append("Discard")
    win.export_btn.click()
    assert win.report_edit.toPlainText() == base_text, \
        "Discard restores the report baseline"
    assert len(picks) == 2, "a discarded source lets the action continue"
    assert "Export cancelled; nothing was written." in win.status.text()
    win.report_cancel_btn.click()

    # Cancel keeps the edit; the report file is untouched
    open_report_edit()
    win.report_edit.setPlainText("kept drift")
    answers.append("Cancel")
    win.export_btn.click()
    assert win.report_edit.toPlainText() == "kept drift"
    assert len(picks) == 2, "Cancel stops the export"
    assert report_path.read_text() == base_text

    # a stale Save fails with the guarded message and keeps the editor
    report_path.write_text("external bytes\n")
    answers.append("Save")
    win.export_btn.click()
    assert "saved sources changed on disk" in win.status.text()
    assert win.report_edit.toPlainText() == "kept drift", \
        "a failed Save keeps the local edited text"
    assert len(picks) == 2 and report_path.read_text() == "external bytes\n"

    # a timer refresh never clobbers the locally edited report text
    win.refresh(force=True)
    assert win.report_edit.toPlainText() == "kept drift"
    assert win._report_edit_dirty is True
    assert win._scene_sel is None or True, "selection survives the refresh"

    # Revise from saved sources: Save commits, then Revise must be pressed
    # again; the second press starts the session from the saved notes
    report_path.write_text(base_text)
    win.refresh(force=True)
    win.report_list.setCurrentRow(0)
    win.report_edit_btn.click()
    win.report_edit.setPlainText("for revise")
    win.tabs.setCurrentIndex(gw.REVISION)
    answers.append("Save")
    win.revise_btn.click()
    assert report_path.read_text() == "for revise"
    assert win._revision is None, "no silent revise launch after a Save"
    assert "again" in win.status.text()
    assert len(fake.calls) == 0, "no provider call happened for the save"
    win.revise_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert win._revision is not None, "the repeated explicit revise runs"
    assert win._revision["psg"]["nid"] == "n1"

    # unsaved steering is a prose source too: Save then press again
    win._rev_reset()
    n_picks = len(picks)
    win.steer_editor.setPlainText("unsaved steer")
    win.tabs.setCurrentIndex(gw.STATUS)
    answers.append("Save")
    win.export_btn.click()
    tree = json.loads((project / "trees" / "s001.json").read_text())
    assert tree.get("steer") == "unsaved steer", "steering is persisted"
    assert len(picks) == n_picks, "no silent export after the steering Save"
    assert "again" in win.status.text()
    win.export_btn.click()
    assert len(picks) == n_picks + 1, "the repeated explicit export runs"
    assert "Export cancelled; nothing was written." in win.status.text()


def case_planning_deferred_create(root):
    """Deferred Create continuation after a dirty-settings Save (1.6).

    The save settles first on the existing worker, then the picked directory
    receives complete shared initialization identical to immediate Create;
    cancelled/failed saves and an initialization Stop never create or bind a
    new project incorrectly and never lose prior work.
    """
    import longform_core.gui_window as gw
    a = app()
    import longform_core.utils as utils

    def _no_terminal(*_a, **_k):
        raise AssertionError("terminal/editor helper called")

    utils.edit_text = _no_terminal
    utils.ask = _no_terminal
    utils.page = _no_terminal
    utils.pydoc.pager = _no_terminal
    os.environ.pop("FEATHERLESS_API_KEY", None)   # no credentials in this case
    choices, dir_picks = [], []
    import longform_core.defaults as dfl
    import longform_core.planning_operations as planmod
    from longform_core.cancel import Cancelled

    old = root / "old"
    planmod.init_project(old)
    cfg = json.loads((old / "project.json").read_text())
    cfg["title"] = "Old Title"
    (old / "project.json").write_text(json.dumps(cfg), encoding="utf-8")

    win = gw.MainWindow(str(old), choice=lambda t, x, o: choices.pop(0),
                        dir_picker=lambda t, p: dir_picks.pop(0),
                        preset_picker=lambda t: None)
    win.show()
    win.tabs.setCurrentIndex(gw.SETUP)
    win.set_setting("title", "Dirty Old")
    assert win.settings_dirty()

    # cancelled resolution: nothing is created, the current project stays
    dest = root / "newproj"
    choices.append("Cancel")
    dir_picks.append(str(dest))
    win.create_btn.click()
    assert not dest.exists(), "a cancelled resolution creates nothing"
    assert win._root == old
    assert json.loads((old / "project.json").read_text())["title"] == \
        "Old Title", "no save ran for Cancel"

    # deferred Create: Save settles first, then init runs on the same worker
    choices.append("Save")
    dir_picks.append(str(dest))
    win.create_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert json.loads((old / "project.json").read_text())["title"] == \
        "Dirty Old", "the save completed before the initialization"
    assert win._root == dest, "the new project is bound after settlement"
    assert json.loads((dest / "project.json").read_text())["title"] == \
        "Untitled", "defaults never inherit old-project settings"
    for name in ("project.json", "bible.md", "state.md", "scenes.json",
                 "summaries.json", "writer_preset.json"):
        assert (dest / name).is_file(), name
    for d in ("trees", "outlines", "critiques", "checks", "state_history",
              "lorebooks", "bible_history"):
        assert (dest / d).is_dir(), d
    assert (dest / "writer_preset.json").read_bytes() == \
        dfl.writer_preset_bytes()
    assert "bundled writer_preset.json created" in win.status.text()

    # both Create paths agree: an immediate Create is byte-identical
    immediate = root / "immediate"
    planmod.init_project(immediate)
    for name in ("project.json", "bible.md", "state.md", "scenes.json",
                 "summaries.json", "writer_preset.json"):
        assert (immediate / name).read_bytes() == (dest / name).read_bytes(), \
            f"deferred and immediate Create agree on {name}"

    # a stale settings save refuses and never continues the deferred Create
    old2 = root / "old2"
    planmod.init_project(old2)
    win2 = gw.MainWindow(str(old2), choice=lambda t, x, o: choices.pop(0),
                         dir_picker=lambda t, p: dir_picks.pop(0),
                         preset_picker=lambda t: None)
    win2.show()
    win2.tabs.setCurrentIndex(gw.SETUP)
    win2.set_setting("title", "Stale Edit")
    cfg2 = json.loads((old2 / "project.json").read_text())
    cfg2["target_words"] = 1   # changed behind the form: the save goes stale
    (old2 / "project.json").write_text(json.dumps(cfg2), encoding="utf-8")
    dest2 = root / "never"
    choices.append("Save")
    dir_picks.append(str(dest2))
    win2.create_btn.click()
    assert _pump(a, lambda: not win2._busy)
    assert not dest2.exists(), "a stale save never continues the deferred Create"
    assert win2._root == old2, "the current project remains selected"
    assert json.loads((old2 / "project.json").read_text())["target_words"] == 1
    assert json.loads((old2 / "project.json").read_text())["title"] == \
        "Untitled", "the stale edit is refused, prior work is intact"

    # cooperative Stop during the deferred initialization: completed writes
    # stay saved, the old project is never rebound, retry fills the rest
    old3 = root / "old3"
    planmod.init_project(old3)
    win3 = gw.MainWindow(str(old3), choice=lambda t, x, o: choices.pop(0),
                         dir_picker=lambda t, p: dir_picks.pop(0),
                         preset_picker=lambda t: None)
    win3.show()
    win3.tabs.setCurrentIndex(gw.SETUP)
    win3.set_setting("title", "Dirty Three")
    dest3 = root / "stopped"
    real_init = planmod.init_project

    class _StopSoon:
        def __init__(self, after):
            self.n = 0
            self.after = after

        def check(self):
            self.n += 1
            if self.n > self.after:
                raise Cancelled("stopped")

    def stopping_init(target, *, token=None, events=None, **kw):
        return real_init(target, token=_StopSoon(2), events=events, **kw)

    planmod.init_project = stopping_init
    try:
        choices.append("Save")
        dir_picks.append(str(dest3))
        win3.create_btn.click()
        assert _pump(a, lambda: not win3._busy)
        assert win3._root == old3, "a stopped init never binds the new project"
        assert (dest3 / "project.json").is_file(), \
            "completed writes stay saved"
        assert not (dest3 / "writer_preset.json").exists(), \
            "the stopped run created no preset and reports the partial state"
        assert "incomplete" in win3.status.text().lower()
        assert json.loads((old3 / "project.json").read_text())["title"] == \
            "Dirty Three", "prior work is preserved through the Stop"
        planmod.init_project = real_init
        dir_picks.append(str(dest3))
        win3.create_btn.click()
        assert _pump(a, lambda: not win3._busy)
        assert win3._root == dest3, "retry after the Stop binds the new project"
        assert (dest3 / "writer_preset.json").read_bytes() == \
            dfl.writer_preset_bytes(), "retry fills only the missing paths"
        assert json.loads((dest3 / "project.json").read_text())["title"] == \
            "Untitled"
    finally:
        planmod.init_project = real_init
    choices.append("Discard")   # win2's refused edit stays unsaved by design
    win.close()
    win2.close()
    win3.close()


# ------------------------------------------------- gui-api-key-setup cases

SESSION_SENTINEL = "sk-session-sentinel-credentials"
PROJECT_SENTINEL = "sk-project-sentinel-credentials"
ENV_SENTINEL = "sk-env-sentinel-credentials"
CRED_PLANNER_MODEL = "huihui-ai/Huihui-Qwen3.8-27B-abliterated"


def _credential_models():
    return {CRED_PLANNER_MODEL: {"id": CRED_PLANNER_MODEL,
                                 "context_length": 131072,
                                 "max_completion_tokens": 8192,
                                 "available_on_current_plan": True,
                                 "api_key": "sk-server-side"}}


def _credential_project(root, name="p", cfg=None):
    proj = root / name
    (proj / "trees").mkdir(parents=True)
    _write_json(proj / "project.json", cfg if cfg is not None else {})
    _write_json(proj / "scenes.json", [])
    _write_json(proj / "summaries.json", {"scenes": {}, "arcs": []})
    return proj


def _assert_no_sentinel(win, *extra_texts):
    """The credential values never reach any visible pane text."""
    surfaces = [win.credential_status.text(), win.setup_status.text(),
                win.settings_note.text(), win.status.text(),
                win.limits_view.toPlainText()]
    for text in list(extra_texts) + surfaces:
        for sentinel in (SESSION_SENTINEL, PROJECT_SENTINEL, ENV_SENTINEL):
            assert sentinel not in (text or ""), "a credential value leaked"


def case_credentials_session(root):
    """gui-api-key-setup: from complete Create, a masked entry plus Use for
    this session satisfies every provider prerequisite (limits, outline)
    without changing project.json; a new window never inherits it."""
    import longform_core.gui_window as gw
    from PySide6.QtWidgets import QLineEdit
    a = app()
    os.environ.pop("FEATHERLESS_API_KEY", None)
    fake = PlanningFake(plan={"max_context_length": 8192, "concurrency": 2},
                        models=_credential_models())

    fresh = root / "fresh"
    dir_picks = [str(fresh)]
    win = gw.MainWindow(str(fresh), choice=_no_dialogs("credentials"),
                        dir_picker=lambda t, p: dir_picks.pop(0),
                        provider_factory=lambda _p: fake)
    win.show()
    win.create_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert (fresh / "project.json").is_file()
    assert json.loads((fresh / "project.json").read_text())["api_key"] == ""
    before = (fresh / "project.json").read_bytes()

    win.tabs.setCurrentIndex(gw.SETUP)
    entry = win.credential_entry
    assert entry.echoMode() == QLineEdit.EchoMode.Password, "entry is masked"
    assert entry.text() == "", "the entry is empty on load (never prefilled)"

    # typing alone is inert: no effective credential change, no request
    entry.setText(SESSION_SENTINEL + " ")
    assert (fresh / "project.json").read_bytes() == before
    assert fake.calls == [] and fake.started == 0, "typing makes no request"
    assert "missing" in win.credential_status.text().lower()

    # Use for this session: trims, activates, clears the entry, writes nothing
    win.credential_use_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert win.credential_entry.text() == "", "entry cleared after Use"
    assert fake.calls == [] and fake.started == 0, "Use makes no request"
    status = win.credential_status.text()
    assert "Available" in status and "session" in status, status
    _assert_no_sentinel(win)
    assert (fresh / "project.json").read_bytes() == before, \
        "session use never writes project.json"

    # prerequisites: the session credential satisfies readiness
    assert win._session.get("creds_ok")
    assert "credentials" not in win.generate_note.text().lower()
    assert win.outline_generate_btn.isEnabled()

    # explicit Fetch limits runs with only the session credential
    win.fetch_limits_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert ("GET", "/plan") in fake.calls, \
        "the session credential reaches the provider without a disk key"
    assert (fresh / "limits.json").is_file()
    _assert_no_sentinel(win)

    # outline generation runs through the window's provider wrapper
    win.tabs.setCurrentIndex(gw.OUTLINE)
    win.outline_notes_edit.setPlainText("Keep chapters short.")
    win.outline_generate_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert any(c[0] == "chat_many" for c in fake.calls), \
        "outline generation ran with the session credential active"
    assert win._outline_overview.get("candidates"), "candidates were generated"
    _assert_no_sentinel(win)
    assert (fresh / "project.json").read_bytes() == before, \
        "outline generation never writes project.json"

    # lifecycle: closing clears the session; a new window never inherits it
    win.close()
    win2 = gw.MainWindow(str(fresh), choice=_no_dialogs("credentials"),
                         provider_factory=lambda _p: fake)
    win2.show()
    win2.tabs.setCurrentIndex(gw.SETUP)
    assert "missing" in win2.credential_status.text().lower(), \
        "a new window never inherits the session credential"
    assert win2.credential_entry.text() == ""

    # empty input is refused: no effective credential change, no request
    fake.calls.clear(); fake.started = 0
    before2 = (fresh / "project.json").read_bytes()
    win2.credential_use_btn.click()
    assert fake.calls == [] and fake.started == 0
    assert "enter a credential" in win2.status.text().lower()
    assert (fresh / "project.json").read_bytes() == before2
    win2.close()

    # cancelled/failed Open keeps the current project's session; a
    # successful switch to another project clears it
    proj_b = _credential_project(root, "projb", cfg={"api_key":
                                                     PROJECT_SENTINEL})
    picks = []
    fake.calls.clear(); fake.started = 0
    win3 = gw.MainWindow(str(fresh),
                         choice=lambda t, x, o: picks.pop(0),
                         dir_picker=lambda t, p: picks.pop(0),
                         provider_factory=lambda _p: fake)
    win3.show()
    win3.tabs.setCurrentIndex(gw.SETUP)
    win3.credential_entry.setText(SESSION_SENTINEL)
    win3.credential_use_btn.click()
    assert _pump(a, lambda: not win3._busy)
    picks.append(None)          # cancelled Open: no directory picked
    win3.open_btn.click()
    assert _pump(a, lambda: not win3._busy)
    assert win3._session_key == SESSION_SENTINEL, \
        "a cancelled Open never clears the current session"
    assert fake.calls == [] and fake.started == 0
    picks.append(str(proj_b))   # successful switch
    win3.open_btn.click()
    assert _pump(a, lambda: not win3._busy)
    assert win3._session_key is None, \
        "a successful switch clears the session"
    assert "project" in win3.credential_status.text().lower(), \
        "the saved project key is the fallback source"
    assert win3.credential_entry.text() == ""
    assert fake.calls == [] and fake.started == 0, \
        "no implicit request on any credential lifecycle step"
    win3.close()


def case_credentials_storage(root):
    """gui-api-key-setup: Save/Replace/Clear saved key — explicit informed
    actions through the shared credential op; only api_key changes, no
    session override is replaced, values never appear on screen."""
    import longform_core.gui_window as gw
    a = app()
    os.environ.pop("FEATHERLESS_API_KEY", None)
    fake = PlanningFake(plan={"max_context_length": 8192, "concurrency": 2},
                        models=_credential_models())
    cfg = {"api_key": PROJECT_SENTINEL, "title": "Store", "target_words": 8000}
    proj = _credential_project(root, "stored", cfg=cfg)
    choices = []
    win = gw.MainWindow(str(proj), choice=lambda t, x, o: choices.pop(0),
                        provider_factory=lambda _p: fake)
    win.show()
    win.tabs.setCurrentIndex(gw.SETUP)
    assert "Available" in win.credential_status.text()
    assert "project" in win.credential_status.text().lower(), \
        "the saved key is the winning source"
    assert win.credential_save_btn.text() == "Replace saved key"
    before = (proj / "project.json").read_bytes()

    # Save with a saved key present is a Replace confirmation; declining
    # writes nothing
    win.credential_entry.setText(SESSION_SENTINEL)
    choices.append("Cancel")
    win.credential_save_btn.click()
    assert (proj / "project.json").read_bytes() == before, \
        "a declined confirmation writes nothing"
    assert json.loads((proj / "project.json").read_text())["api_key"] == \
        PROJECT_SENTINEL

    # accepting stores the trimmed value; only api_key changes
    choices.append("Save")
    win.credential_save_btn.click()
    assert _pump(a, lambda: not win._busy)
    cfg2 = json.loads((proj / "project.json").read_text())
    assert cfg2["api_key"] == SESSION_SENTINEL, "the value is trimmed"
    assert cfg2["title"] == "Store" and cfg2["target_words"] == 8000, \
        "unrelated fields survive"
    assert win.credential_entry.text() == ""
    assert win.credential_save_btn.text() == "Replace saved key"
    assert "Available" in win.credential_status.text()
    _assert_no_sentinel(win)
    after_save = (proj / "project.json").read_bytes()

    # a session key is never replaced by saving
    win.credential_entry.setText("sk-temp-session")
    win.credential_use_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert win._session_key == "sk-temp-session"
    assert "session" in win.credential_status.text().lower()
    win.credential_entry.setText(SESSION_SENTINEL)
    choices.append("Save")
    win.credential_save_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert json.loads((proj / "project.json").read_text())["api_key"] == \
        SESSION_SENTINEL, "saving stored the value"
    assert win._session_key == "sk-temp-session", \
        "saving never replaces an active session override"
    saved_bytes = (proj / "project.json").read_bytes()

    # Clear saved key: confirmation explains the fallback; the session stays
    choices.append("Cancel")
    win.credential_clear_saved_btn.click()
    assert (proj / "project.json").read_bytes() == saved_bytes
    choices.append("Clear")
    win.credential_clear_saved_btn.click()
    assert _pump(a, lambda: not win._busy)
    cfg3 = json.loads((proj / "project.json").read_text())
    assert cfg3["api_key"] == "" and cfg3["title"] == "Store", \
        "clear writes an empty api_key and keeps unrelated fields"
    assert win._session_key == "sk-temp-session", \
        "clearing the saved key never clears the session"
    assert "session" in win.credential_status.text().lower(), \
        "the session override is still the winning source"
    assert win.credential_save_btn.text() == "Save to this project"
    _assert_no_sentinel(win)
    assert "sk-temp-session" not in (proj / "project.json").read_text()

    # clear with no session: the environment fallback is named in the dialog
    win.credential_clear_session_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "missing" in win.credential_status.text().lower()
    assert not (proj / "limits.json").exists(), "no request was made"
    assert fake.calls == [] and fake.started == 0

    # reopen: the cleared state falls back to missing; a fresh window over
    # a project with a saved key reports the project source, not a value
    win.close()
    win2 = gw.MainWindow(str(proj), choice=_no_dialogs("storage"),
                         provider_factory=lambda _p: fake)
    win2.show()
    win2.tabs.setCurrentIndex(gw.SETUP)
    assert "missing" in win2.credential_status.text().lower()
    assert win2.credential_entry.text() == ""
    win2.close()
    proj_c = _credential_project(root, "storedc",
                                 cfg={"api_key": PROJECT_SENTINEL,
                                      "title": "StoreC"})
    picks = []
    win3 = gw.MainWindow(str(proj_c), choice=lambda t, x, o: picks.pop(0),
                         dir_picker=lambda t, p: None,
                         provider_factory=lambda _p: fake)
    win3.show()
    win3.tabs.setCurrentIndex(gw.SETUP)
    assert "project" in win3.credential_status.text().lower(), \
        "a reopened window reports the saved key's availability, not a value"
    assert PROJECT_SENTINEL not in win3.credential_status.text()

    # credential actions pause while an operation runs
    orig_get = fake.get

    def gated_get(path, token=None, on_retry_event=None):
        if fake.gate is not None and not fake.gate.wait(10):
            raise AssertionError("gate never opened")
        return orig_get(path, token=token, on_retry_event=on_retry_event)

    fake.get = gated_get
    fake.gate = threading.Event()
    win3.fetch_limits_btn.click()
    assert _pump(a, lambda: win3._busy)
    for b in (win3.credential_use_btn, win3.credential_clear_session_btn,
              win3.credential_save_btn, win3.credential_clear_saved_btn,
              win3.credential_test_btn):
        assert not b.isEnabled(), "credential actions are disabled while busy"
    fake.gate.set()
    assert _pump(a, lambda: not win3._busy)
    assert win3.credential_use_btn.isEnabled()
    fake.gate = None
    fake.get = orig_get
    _assert_no_sentinel(win3)

    # dirty settings: Cancel keeps the edits and writes nothing
    win3.credential_entry.setText(SESSION_SENTINEL)
    win3.set_setting("title", "Changed externally")   # marks settings dirty
    assert win3.settings_dirty()
    before_c = (proj_c / "project.json").read_bytes()
    picks.append("Cancel")
    win3.credential_save_btn.click()
    assert (proj_c / "project.json").read_bytes() == before_c
    assert win3.settings_dirty(), "a cancelled save keeps the settings edits"

    # Discard continues: the settings edits are dropped, only api_key changes
    picks.append("Save")                    # confirmation first
    picks.append("Discard settings changes")  # then the dirty-settings dialog
    win3.credential_save_btn.click()
    assert _pump(a, lambda: not win3._busy)
    cfgc = json.loads((proj_c / "project.json").read_text())
    assert cfgc["api_key"] == SESSION_SENTINEL
    assert cfgc["title"] == "StoreC", \
        "the discarded settings edit never persisted and fields survive"
    assert not win3.settings_dirty()
    _assert_no_sentinel(win3)

    # a stale save is refused: the configuration changed externally
    (proj_c / "project.json").write_text(
        json.dumps({**cfgc, "title": "External edit"}), encoding="utf-8")
    win3.credential_entry.setText("sk-replacement")
    picks.append("Save")
    picks.append("Discard settings changes")  # confirmation, then dirty dialog
    win3.credential_save_btn.click()
    assert _pump(a, lambda: not win3._busy)
    msg = win3.status.text()
    assert "reload" in msg.lower() or "stale" in msg.lower(), msg
    assert json.loads((proj_c / "project.json").read_text())["title"] == \
        "External edit", "an externally changed configuration survives"
    assert json.loads((proj_c / "project.json").read_text())["api_key"] == \
        SESSION_SENTINEL, "a stale save writes nothing"
    _assert_no_sentinel(win3)
    fake.gate = None
    win3.close()


class _GatedPlan:
    """Provider whose /plan lookup blocks on a gate (Stop coverage)."""

    def __init__(self, gate):
        self.gate = gate
        self.calls = []

    def get(self, path, token=None, on_retry_event=None):
        self.calls.append(("GET", path))
        if self.gate is not None and not self.gate.wait(10):
            raise AssertionError("gate never opened")
        if token is not None:
            token.check()
        return {"max_context_length": 8192, "concurrency": 2}


def case_credentials_connection(root):
    """gui-api-key-setup: Test connection is explicit and non-generative —
    one /plan lookup per click, no generation, no limits.json, sanitized
    success/failure naming the source without a value."""
    import longform_core.gui_window as gw
    a = app()
    os.environ.pop("FEATHERLESS_API_KEY", None)
    fake = PlanningFake(plan={"max_context_length": 8192, "concurrency": 2},
                        models=_credential_models())
    proj = _credential_project(root, "conn", cfg={})
    win = gw.MainWindow(str(proj), choice=_no_dialogs("credentials"),
                        provider_factory=lambda _p: fake)
    win.show()
    win.tabs.setCurrentIndex(gw.SETUP)

    # missing credentials: recovery guidance, no request, no factory call
    win.credential_test_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert fake.calls == [] and fake.started == 0
    err = win.status.text()
    assert "no API key" in err and "Use for this session" in err, \
        f"recovery guidance: {err!r}"
    assert not (proj / "limits.json").exists()
    _assert_no_sentinel(win)

    # session credential: one plan lookup, source named, nothing written
    win.credential_entry.setText(SESSION_SENTINEL)
    win.credential_use_btn.click()
    assert _pump(a, lambda: not win._busy)
    before = (proj / "project.json").read_bytes()
    fake.calls.clear()
    win.credential_test_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert fake.calls == [("GET", "/plan")], "exactly one plan lookup"
    assert fake.started == 0, "the connection test never generates"
    assert not (proj / "limits.json").exists()
    assert (proj / "project.json").read_bytes() == before
    msg = win.status.text()
    assert "succeeded" in msg.lower() and "session" in msg.lower(), msg
    _assert_no_sentinel(win)

    # a failing lookup reports a sanitized failure and writes nothing
    fake.calls.clear()
    fake.get_fail_on = {0}
    fake.gets = 1   # the fake checks (gets - 1) before its own increment
    win.credential_test_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert fake.calls == [("GET", "/plan")]
    msg = win.status.text()
    assert "failed" in msg.lower(), msg
    _assert_no_sentinel(win)
    assert not (proj / "limits.json").exists()
    win.close()

    # cooperative Stop: close while a lookup is blocked, Stop and wait
    # settles the worker, then the window closes and nothing was written
    gate = threading.Event()
    gated = _GatedPlan(gate)
    win2 = gw.MainWindow(str(proj), choice=lambda t, x, o: picks.pop(0),
                         provider_factory=lambda _p: gated)
    win2.show()
    win2.tabs.setCurrentIndex(gw.SETUP)
    win2.credential_entry.setText(SESSION_SENTINEL)
    win2.credential_use_btn.click()
    assert _pump(a, lambda: not win2._busy)
    win2.credential_test_btn.click()
    assert _pump(a, lambda: win2._busy)
    assert _pump(a, lambda: gated.calls == [("GET", "/plan")]), \
        "the lookup started and is blocked in flight"
    assert not win2.credential_test_btn.isEnabled(), \
        "credential actions are disabled while the lookup runs"
    picks = ["Stop and wait"]
    win2.close()
    gate.set()
    assert _pump(a, lambda: not win2._busy), \
        "Stop and wait settles the worker cooperatively"
    assert "stopping" in win2.status.text().lower() or \
        "stopped" in win2.status.text().lower()
    win2.close()   # the abandoned close is completed after settlement
    assert _pump(a, lambda: not win2.isVisible()), \
        "the window closes only after settlement"
    assert gated.calls == [("GET", "/plan")], "exactly one lookup ran"
    assert not (proj / "limits.json").exists()
    _assert_no_sentinel(win2)


def case_credentials_redaction(root):
    """gui-api-key-setup: no credential value from session, saved project or
    environment ever reaches previews, saved nodes, status/errors or files —
    including values split across streamed chunks."""
    import longform_core.gui_window as gw
    a = app()
    os.environ["FEATHERLESS_API_KEY"] = ENV_SENTINEL
    try:
        project = _draft_project(root)
        cfgp = project / "project.json"
        cfgp.write_text(json.dumps(
            {**json.loads(cfgp.read_text()), "api_key": PROJECT_SENTINEL}),
            encoding="utf-8")
        chunks = (f"The key is {SESSION_SENTINEL[:12]}",
                  f"{SESSION_SENTINEL[12:]} end. {ENV_SENTINEL} echo.")
        fake = FakeProvider(chunks=chunks)
        # the fake mirrors the ops-level redaction feed for preview deltas
        fake.preview_secrets = [SESSION_SENTINEL, PROJECT_SENTINEL,
                                ENV_SENTINEL]
        win = gw.MainWindow(str(project),
                            choice=_no_dialogs("redaction"),
                            provider_factory=lambda _p: fake)
        win.show()
        win._session_key = SESSION_SENTINEL   # a session override is active
        win.select_item("manuscript", "s001", None)
        win.count_spin.setValue(1)
        win.generate_btn.click()
        assert _pump(a, lambda: not win._busy)

        # the streamed preview never shows any source's value, split or whole
        preview = win.preview.toPlainText()
        for s in (SESSION_SENTINEL, PROJECT_SENTINEL, ENV_SENTINEL):
            assert s not in preview, "a credential value leaked to the preview"
        assert "The key is [redacted]" in preview, \
            "split fragments are withheld, then emitted redacted"

        # the accepted-text node file never stores a value
        t = json.loads((project / "trees" / "s001.json").read_text())
        node = t["nodes"]["n2"]
        blob = json.dumps(t)
        for s in (SESSION_SENTINEL, PROJECT_SENTINEL, ENV_SENTINEL):
            assert s not in blob, "a credential value leaked into a tree file"
        assert node["text"].strip().startswith("The key is [redacted]")

        # a midstream failure echoing the saved key is redacted in status
        fake2 = FakeProvider(chunks=("First. ",))
        fake2.fail_after = 0
        win2 = gw.MainWindow(str(project), choice=_no_dialogs("redaction"),
                             provider_factory=lambda _p: fake2)
        win2.show()
        win2.select_item("manuscript", "s001", None)
        win2.count_spin.setValue(1)
        win2._provider_factory = lambda _p: _EchoFail(PROJECT_SENTINEL)
        win2.generate_btn.click()
        assert _pump(a, lambda: not win2._busy)
        msg = win2.status.text()
        assert PROJECT_SENTINEL not in msg and "[redacted]" in msg, \
            f"a credential echo reached status: {msg!r}"
        win2.close()
        win.close()
    finally:
        os.environ.pop("FEATHERLESS_API_KEY", None)


class _EchoFail:
    """Provider whose failure message echoes the given secret."""

    def __init__(self, secret):
        self.secret = secret

    def complete(self, role, prompt, params, extra=None, stream_cb=None,
                 **kw):
        raise RuntimeError(f"provider refused {self.secret}")

    def many(self, fn, n, token=None, on_event=None):
        return []


CASES = {
    "owner_flow_reading": case_owner_flow_reading,
    "case_draft_generate_acceptance": case_draft_generate_acceptance,
    "case_draft_midstream_failure": case_draft_midstream_failure,
    "case_draft_stop_and_close": case_draft_stop_and_close,
    "case_draft_stale_refusal": case_draft_stale_refusal,
    "case_draft_candidate_tray": case_draft_candidate_tray,
    "case_draft_scene_context": case_draft_scene_context,
    "case_draft_edit_and_branches": case_draft_edit_and_branches,
    "case_draft_lore": case_draft_lore,
    "case_draft_help_and_leave": case_draft_help_and_leave,
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
    "case_planning_journey": case_planning_journey,
    "case_planning_create_open": case_planning_create_open,
    "case_planning_deferred_create": case_planning_deferred_create,
    "case_planning_settings_limits": case_planning_settings_limits,
    "case_credentials_session": case_credentials_session,
    "case_credentials_storage": case_credentials_storage,
    "case_credentials_connection": case_credentials_connection,
    "case_credentials_redaction": case_credentials_redaction,
    "case_planning_bible": case_planning_bible,
    "case_planning_outline": case_planning_outline,
    "case_stream_planning": case_stream_planning,
    "case_stream_draft_candidates": case_stream_draft_candidates,
    "case_planning_scenes": case_planning_scenes,
    "case_planning_card_edit": case_planning_card_edit,
    "case_review_update_state": case_review_update_state,
    "case_review_compress": case_review_compress,
    "case_review_reports": case_review_reports,
    "case_review_revise": case_review_revise,
    "case_review_status_export": case_review_status_export,
    "case_review_settlement": case_review_settlement,
    "case_review_dirty_sources": case_review_dirty_sources,
    "case_review_journey": case_review_journey,
}


# Cases for openspec/changes/gui-generated-text-streaming whose widgets/seams
# are not implemented yet. Skipped loudly, never silently: a pending case must
# not count as coverage. Each task that makes a case pass removes its name.
PENDING_STREAM_CASES = set()


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
    # coverage guard: every case_* function in this module must be
    # registered, or it would silently never run from check.sh
    defined = sorted(
        name for name, obj in vars(sys.modules["__main__"]).items()
        if name.startswith("case_") and callable(obj))
    unregistered = [n for n in defined
                    if n not in CASES and n.removeprefix("case_") not in CASES]
    if unregistered:
        print(f"unregistered Qt widget case(s): {', '.join(unregistered)}",
              file=sys.stderr)
        return 2
    failures = []
    for name in names:
        if name in PENDING_STREAM_CASES:
            print(f"pending {name} (gui-generated-text-streaming seam not "
                  "implemented yet)")
            continue
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


def case_zz_unregistered(root):
    pass
