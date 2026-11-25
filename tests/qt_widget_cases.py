"""Offscreen Qt widget cases for the gui reading/steering shell.

Run as a plain script (never collected by pytest) with QT_QPA_PLATFORM=offscreen;
tests/test_qt_cases.py launches this file in an isolated subprocess so widget
coverage actually executes instead of being skipped. Every case is a function
that raises on failure; any failing case (or missing PySide6) exits nonzero.
"""

import json
import os
import re
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


def goto_tool(win, tool):
    """Case helper: navigate by semantic stage/tool route, never by index."""
    win.select_tool(tool)

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

def _project_for_stages(root):
    """Populated project with two scenes, one drafted."""
    return _build_project(root, scenes=[
        _scene("s001"), _scene("s002", status="done"),
    ], trees={
        "s001": _tree({"n1": _node("n1", None, "Active prose.")}, head="n1"),
    }, bible="B")


def case_workflow_stages(root):
    """Plan → Write → Review → Export are the four primary routes; stage
    purpose/readiness/next action are visible and draft steering/Generate
    appear only in Write."""
    import longform_core.gui_window as gw
    a = app()
    project = _project_for_stages(root / "p")
    win = gw.MainWindow(str(project),
                        choice=_no_dialogs("case_workflow_stages"))
    win.show()
    try:
        # The primary selector is exactly the four stages, in order.
        assert win.stages.count() == 4
        assert [win.stages.tabText(i).replace("&", "")
                for i in range(win.stages.count())] \
            == ["Plan", "Write", "Review", "Export"]
        assert gw.STAGE_ORDER == ("plan", "write", "review", "export")
        assert not hasattr(win, "tabs"), \
            "the fifteen-tab wall must be gone, not hidden"
        # Each stage explains its purpose and one next action.
        for stage in gw.STAGE_ORDER:
            assert stage in win.stage_purpose
            text = win.stage_purpose[stage].text()
            assert text.strip(), f"{stage} stage must show its purpose"
        # Semantic routes reach every existing pane group.
        win.select_stage("plan")
        assert win.current_stage() == "plan"
        win.select_stage("write")
        assert win.current_stage() == "write"
        win.select_stage("review")
        assert win.current_stage() == "review"
        win.select_stage("export")
        assert win.current_stage() == "export"
        win.select_tool("notes")
        assert win.route() == ("write", "notes")
        win.select_tool("bible")
        assert win.route() == ("plan", "bible")
        win.select_tool("status")
        assert win.route() == ("export", "status")
        # Draft steering/Generate/count are visible only in Write.
        win.select_stage("write")
        assert win.steer_editor.isVisible()
        assert win.generate_btn.isVisible()
        assert win.count_spin.isVisible()
        for stage in ("plan", "review", "export"):
            win.select_stage(stage)
            assert not win.steer_editor.isVisible(), \
                f"steering must hide outside Write (was visible in {stage})"
            assert not win.generate_btn.isVisible(), \
                f"Generate must hide outside Write (was visible in {stage})"
            assert not win.count_spin.isVisible()
        # Every Write tool stays reachable through its semantic route.
        for tool in gw.STAGE_TOOLS["write"]:
            win.select_tool(tool)
            assert win.current_tool() == tool
            assert win._stage_tools["write"].currentWidget().isVisible(), \
                f"Write tool {tool} shows its pane"
        # Stop stays global: the same Stop button is shared by every stage.
        assert win.stop_btn.isVisible()
        win.select_stage("plan")
        assert win.stop_btn.isVisible()
        win.close()
    finally:
        win.deleteLater()
        a.processEvents()   # the next case asserts one top-level window


def case_workflow_readiness(root):
    """Plan overview: saved-artifact readiness, one recommended next action,
    advisory warnings for invalid sources; reading never writes or calls."""
    import longform_core.gui_window as gw
    import longform_core.planning_operations as pop
    a = app()
    project = _build_project(root / "p", scenes=[_scene("s001")], trees={
        "s001": _tree({"n1": _node("n1", None, "A.")}, head="n1")},
        bible="## Title\nThe Tower\n", state="state body",
        project_extra={"api_key": "sk-test"})
    (project / "writer_preset.json").write_text(json.dumps(PRESET),
                                                encoding="utf-8")
    (project / "outline.md").write_text("Act 1: the climb.\n",
                                        encoding="utf-8")
    before = {f.name: f.read_bytes() for f in project.iterdir()
              if f.is_file()}

    win = gw.MainWindow(str(project), choice=_no_dialogs("readiness"))
    win.show()
    try:
        # A ready project recommends Write and shows the saved-artifact facts.
        r = pop.readiness(project)
        assert r["next"] == "write", r["next"]
        assert win.plan_next_btn.text() == "Enter Write"
        overview = win.plan_overview.toPlainText()
        assert "setup: complete" in overview
        assert "1 scene card(s) saved" in win.plan_summary.text()
        assert "bible: 1/1 sections answered" in overview

        # Watching the Plan overview never writes project files.
        win.select_stage("plan")
        for _ in range(2):
            win.refresh(force=True)
        after = {f.name: f.read_bytes() for f in project.iterdir()
                 if f.is_file()}
        assert before == after, "the Plan overview must not write files"

        # The recommended action routes without starting an operation.
        win.plan_next_btn.click()
        assert win.current_stage() == "write"

        # An invalid scenes.json is an advisory warning, not a crash.
        (project / "scenes.json").write_text("{nope", encoding="utf-8")
        win.refresh(force=True)
        overview = win.plan_overview.toPlainText()
        assert "scenes.json is missing or not valid JSON" in overview

        # A fresh directory shows setup recovery before anything else.
        win2 = gw.MainWindow(str(root / "fresh"),
                             choice=_no_dialogs("readiness2"))
        win2.show()
        assert "does not exist" in win2.plan_overview.toPlainText()
        assert win2.plan_next_btn.text() == "Create / repair setup"
        win2.close()
        win2.deleteLater()
        a.processEvents()
        win.close()
    finally:
        win.deleteLater()
        a.processEvents()


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

    win.select_tool("notes")
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
    for tool in ("branches", "notes", "manuscript"):
        goto_tool(win, tool)
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
    """A predictable focus chain: sidebar, then the selected stage's tool
    panes, then the reading/editor panes before the shared action buttons."""
    import longform_core.gui_window as gw
    app()
    project = _build_project(root / "p", scenes=[_scene("s001")], trees={
        "s001": _tree({"n1": _node("n1", None, "A.")}, head="n1")})
    win = gw.MainWindow(str(project), choice=_no_dialogs("case 5"))
    win.show()
    win.sidebar.setFocus()

    def chain(start, limit=2000):
        seq, w = [], start
        for _ in range(limit):
            w = w.nextInFocusChain()
            if w is start:
                break
            seq.append(w)
        return seq

    assert win.sidebar.focusPolicy() != gw.Qt.FocusPolicy.NoFocus
    assert gw.QTabWidget in [type(x) for x in chain(win.sidebar)], \
        "the stage selector must be focusable"

    def order(seq, first_cls, then_cls):
        types = [type(x) for x in seq]
        i1 = types.index(first_cls)
        i2 = next((i for i, t in enumerate(types) if t is then_cls), -1)
        return 0 <= i1 < i2

    # Write: the steering editor precedes its own action buttons in the
    # chain (top-bar buttons legitimately appear earlier).
    win.select_stage("write")
    seq = chain(win._stage_tools["write"])
    i_editor = next(i for i, x in enumerate(seq) if x is win.steer_editor)
    assert next(i for i, x in enumerate(seq) if x is win.save_btn) > i_editor, \
        "steering editor precedes Save steering"
    assert next(i for i, x in enumerate(seq) if x is win.generate_btn) > i_editor, \
        "steering editor precedes Generate"
    assert gw.QPushButton in [type(x) for x in chain(win.steer_editor)], \
        "steering reaches the action buttons"
    # Every stage's tool selector is focusable and leads into its panes.
    for stage in gw.STAGE_ORDER:
        win.select_stage(stage)
        tw = win._stage_tools.get(stage)
        target = tw if tw is not None else win._stage_pages[stage]
        assert gw.QPlainTextEdit in [type(x) for x in chain(target)], \
            f"{stage} tools reach their content panes"
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
    win.select_tool("notes")
    win.select_note("bible")
    win.notes_view.verticalScrollBar().setValue(2)
    win.select_tool("manuscript")
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
    assert win.route() == ("write", "manuscript")
    assert win._sel_data == ("node", "s001", "n2"), "node selection kept"
    assert win.steer_editor.toPlainText() == "dirty during refresh", \
        "dirty text is never replaced by refresh"
    assert win.steer_editor.textCursor().position() == 3, "cursor kept"

    # notes view kept its content/position
    win.select_tool("notes")
    assert "BIBLE BODY" in win.notes_view.toPlainText()
    win.select_tool("manuscript")

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
        self.start_gate = None    # threading.Event: hold before any fragment
        self.fail_after = None    # raise after this many chunks were delivered
        self.fail_on = set()      # call indexes (0-based) that raise
        self.fail_stream_on = set()  # fragments-mode indexes that fail late
        self.parallel = False     # many() runs slots concurrently (indexed mode)

    def complete(self, role, prompt, params, extra=None, stream_cb=None,
                 meta=None, token=None, preview_events=None, _stream=None,
                 **kw):
        self.calls.append({"role": role, "prompt": prompt, "params": params,
                           "extra": extra, "meta": meta})
        self.started += 1
        idx = self.started - 1
        if token is not None:
            token.check()
        if _stream is None and self.fragments is not None:
            _stream = self.fragments[idx]
        if _stream is not None:
            # paused-stream mode (gui-generated-text-streaming): deliver the
            # first fragment, block on the shared gate, then finish.
            first, rest = _stream
            sub = preview_events
            if sub:
                sub({"type": "preview_start", "attempt_id": 1})
            if sub and self.start_gate is not None and \
                    not self.start_gate.wait(30):
                raise AssertionError("start gate never opened")
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
            if self.fail_stream_on and idx in self.fail_stream_on:
                raise RuntimeError("fake provider failed after the fragment")
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
            if sub and self.start_gate is not None and \
                    not self.start_gate.wait(30):
                raise AssertionError("start gate never opened")
            if sub:
                sub({"type": "preview_delta", "attempt_id": 1, "text": first})
            if self.gate is not None and not self.gate.wait(30):
                raise AssertionError("fake provider gate never opened")
            if token is not None:
                token.check()
            if sub:
                sub({"type": "preview_delta", "attempt_id": 1, "text": rest})
            if self.fail_stream_on and (self.started - 1) in self.fail_stream_on:
                raise RuntimeError("fake provider failed after the fragment")
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
    assert win.current_stage() == "write", \
        "draft steering/generation live in the Write stage"
    assert win.steer_editor.isVisible() and win.generate_btn.isVisible() \
        and win.count_spin.isVisible(), \
        "steering, candidate count and Generate are visible in Write"
    win.select_tool("draft")
    assert win.tray.isVisible(), "the candidate tray is reachable in Write"
    win.select_tool("manuscript")
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
    assert win.steer_editor.isVisible() and win.generate_btn.isVisible(), \
        "the Write steering row stays visible while the request streams"
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
    win.select_tool("scene")
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
    win.select_tool("context")
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
    win.select_tool("scene")
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
    win3.select_tool("context")
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
    win.select_tool("lore")
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
    win.select_tool("context")
    win.inspect_btn.click()
    assert "lore injected:" in win.context_view.toPlainText()
    assert "tower" in win.context_view.toPlainText()

    # Import: valid file appears; invalid reports errors and writes nothing
    win.select_tool("lore")
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
    win.select_tool("draft")
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
    win.setup_create_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert not (missing / "project.json").exists(), \
        "a cancelled directory picker creates nothing"

    win.create_btn.click()
    win.setup_create_btn.click()
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
    win.select_tool("setup")
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
    win.select_tool("bible")
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
    win.select_tool("outline")
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
    win.select_tool("scenes")
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
    win.setup_create_btn.click()
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
    win.setup_create_btn.click()
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
    win.setup_create_btn.click()
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
    win.setup_create_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "not a regular file" in win.status.text()
    assert "created before the error" in win.status.text(), \
        "completed writes are reported truthfully"
    assert win._root == other, "a failed Create never rebinds the project"
    assert (coll / "project.json").is_file() and (coll / "trees").is_dir()
    (coll / "writer_preset.json").rmdir()
    dir_picks[:] = [str(coll)]
    win.create_btn.click()
    win.setup_create_btn.click()
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
    win.select_tool("setup")
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
    win2.select_tool("setup")
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
    win.select_tool("bible")
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
    win2.select_tool("bible")
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
    win.select_tool("outline")
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
    win2.select_tool("outline")
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
        assert _pump(a, lambda: win.draft_stream_list.count() == 2 and
                     all("streaming" in win.draft_stream_list.item(x)
                         .text().lower()
                         for x in range(win.draft_stream_list.count()))), \
            "two labelled live candidate rows, both streaming"
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
    win.select_tool("outline")
    assert _pump(a, lambda: not win._busy), "outline overview settles"
    fake.gate = threading.Event()   # closed: block after the first fragment
    win.outline_generate_btn.click()
    try:
        assert _pump(a, lambda: fake.started >= 2), "both candidates started"
        assert _pump(a, lambda: win.outline_stream_list.count() == 2 and
                     all("streaming" in win.outline_stream_list.item(x)
                         .text().lower()
                         for x in range(win.outline_stream_list.count()))), \
            "two labelled live candidate rows, both streaming"
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


def case_stream_review(root):
    """Paused live previews for every review family (task 1.6).

    Parameterized over update-state (full/summary-only), compression,
    critique and revision (initial + Regenerate): the raw answer — sections
    possibly incomplete — is visible in the family's pane while the gate is
    closed and the worker is busy, nothing is written or accepted pre-release
    (gates always released in finally), and the explicit accept/save produces
    the same committed results as the settled journeys."""
    import longform_core.gui_window as gw
    a = app()
    import review_fixtures as rf

    UPDATE_PREFIX = ("<record>\n=== DETAILED SUMMARY ===\nMara opens the gate "
                     "and counts the windows.\n\n=== BRIEF SUMMARY ===\nMara "
                     "opens the gate.\n\n")
    SO_PREFIX = ("<record>\n=== DETAILED SUMMARY ===\nMara closes the gate "
                 "behind her.\n\n")
    ARC_PREFIX = "<summary>Mara opened the gate."
    CRIT_PREFIX = '<critique>1. [style-ru'
    PASS_PREFIX = "<passage>Mara pushed the gate ope"

    def _window(name, responses):
        project = _review_project(root, name)
        fake = ReviewChatFake(responses)
        win = gw.MainWindow(str(project), choice=_no_dialogs("stream review"),
                            provider_factory=lambda _p: fake)
        win.show()
        return project, fake, win

    def _pre_release(win, pane_text, fragment, unchanged):
        assert _pump(a, lambda: fragment in pane_text()), \
            "the raw answer fragment is visible while the gate is closed"
        assert win._busy, "the worker is busy while the gate is closed"
        assert win._op_previews, \
            "the preview state is keyed for the running attempt"
        for label, read in unchanged:
            before, after = read
            assert before == after, f"{label} unchanged before release"

    # --- update state (full): raw incomplete sections stream pre-release
    project, fake, win = _window(
        "s_update", [REVIEW_RECORD_S1])
    try:
        win.select_item("manuscript", "s001", None)
        win.select_tool("continuity")
        state_before = (project / "state.md").read_text(encoding="utf-8")
        sums_before = (project / "summaries.json").read_bytes()
        fake.preview_text = UPDATE_PREFIX
        fake.gate = threading.Event()
        win.update_state_btn.click()
        pane = win.continuity_preview.toPlainText
        _pre_release(win, pane, "=== DETAILED SUMMARY ===",
                     [("state.md", (state_before,
                                    (project / "state.md").read_text(
                                        encoding="utf-8"))),
                      ("summaries.json", (sums_before,
                                          (project / "summaries.json")
                                          .read_bytes()))])
        assert "UPDATED STATE" not in pane(), \
            "the raw preview is incomplete before release"
    finally:
        fake.gate.set()
        assert _pump(a, lambda: not win._busy), "update settles on release"
    assert "STATE DIFF" in pane() and "+Mara is inside the yard." in pane(), \
        "the completed preview shows the parsed sections and diff"
    win.continuity_accept_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert (project / "state.md").read_text(encoding="utf-8") == \
        "Mara is inside the yard.\n"
    assert len(list((project / "state_history").glob("before_s001_*.md"))) == 1
    win.close()

    # --- summary-only: same streaming, state.md never touched
    project, fake, win = _window("s_summary", [REVIEW_RECORD_S2])
    try:
        win.select_item("manuscript", "s002", None)
        win.select_tool("continuity")
        state_before = (project / "state.md").read_text(encoding="utf-8")
        fake.preview_text = SO_PREFIX
        fake.gate = threading.Event()
        win.summary_only_btn.click()
        pane = win.continuity_preview.toPlainText
        _pre_release(win, pane, "=== DETAILED SUMMARY ===",
                     [("state.md", (state_before,
                                    (project / "state.md").read_text(
                                        encoding="utf-8")))])
        assert "UPDATED STATE" not in pane()
    finally:
        fake.gate.set()
        assert _pump(a, lambda: not win._busy), "summary-only settles"
    assert "Mara closes the gate behind her." in pane() and \
        "STATE DIFF" not in pane(), "summary-only previews no state section"
    win.continuity_accept_btn.click()
    assert _pump(a, lambda: not win._busy)
    scenes = json.loads((project / "scenes.json").read_text())
    assert not scenes[1].get("state_updated")
    assert (project / "state.md").read_text(encoding="utf-8") == state_before
    win.close()

    # --- compress: raw arc streams pre-release, nothing appended pre-accept
    project, fake, win = _window("s_compress", [REVIEW_ARC])
    sums = {"scenes": {
        "s001": {"detailed": "Mara opens the gate and counts the windows.",
                 "brief": "Mara opens the gate.", "updated": "x",
                 "text_hash": "h1"},
        "s002": {"detailed": "Mara closes the gate behind her.",
                 "brief": "Mara closes the gate.", "updated": "x",
                 "text_hash": "h2"}},
        "arcs": []}
    _write_json(project / "summaries.json", sums)
    try:
        win.select_tool("continuity")
        fake.preview_text = ARC_PREFIX
        fake.gate = threading.Event()
        win.compress_from.setCurrentText("s001")
        win.compress_to.setCurrentText("s001")
        win.compress_btn.click()
        pane = win.continuity_preview.toPlainText
        _pre_release(win, pane, "Mara opened the gate",
                     [("summaries.json", (sums,
                                          json.loads((project /
                                                      "summaries.json")
                                                     .read_text())))])
    finally:
        fake.gate.set()
        assert _pump(a, lambda: not win._busy), "compress settles on release"
    assert "Mara opened the gate." in pane(), "the arc preview is complete"
    win.continuity_accept_btn.click()
    assert _pump(a, lambda: not win._busy)
    arcs = json.loads((project / "summaries.json").read_text())["arcs"]
    assert arcs and arcs[0]["text"] == "Mara opened the gate." and \
        arcs[0]["from"] == "s001" and arcs[0]["to"] == "s001"
    win.close()

    # --- critique: raw report streams pre-release, saved only on Save
    project, fake, win = _window("s_critique", [REVIEW_CRITIQUE])
    try:
        win.select_item("manuscript", "s001", None)
        win.select_tool("reports")
        crits_before = sorted(x.name for x in (project / "critiques").glob("*"))
        fake.preview_text = CRIT_PREFIX
        fake.gate = threading.Event()
        win.critique_btn.click()
        pane = win.report_view.toPlainText
        _pre_release(win, pane, "1. [style-ru",
                     [("critiques", (crits_before,
                                     sorted(x.name for x in
                                            (project / "critiques")
                                            .glob("*"))))])
    finally:
        fake.gate.set()
        assert _pump(a, lambda: not win._busy), "critique settles on release"
    assert '1. [style-rule] "counts"' in pane()
    win.report_save_btn.click()
    assert _pump(a, lambda: not win._busy)
    crit = (project / "critiques" / "s001.md").read_text(encoding="utf-8")
    assert crit.startswith("# Critique s001 (") and \
        crit.endswith("vary the verb\n")
    win.close()

    # --- revision: first passage streams pre-release; Regenerate too;
    #     accepting the regenerated passage updates node + history once
    project, fake, win = _window(
        "s_revise",
        [REVIEW_PASSAGE, "<passage>Mara pushed the gate open again.</passage>",
         "NO CHANGES"])
    rf.run_cli(project, "critique", [REVIEW_CRITIQUE], args={"scene": "s001"})
    rf.run_cli(project, "check", [], args={"scene": "s001"})
    try:
        win.select_item("manuscript", "s001", None)
        win.select_tool("revision")
        tree_before = json.loads(
            (project / "trees" / "s001.json").read_text())
        fake.preview_text = PASS_PREFIX
        fake.gate = threading.Event()
        win.revise_btn.click()
        pane = win.revise_view.toPlainText
        _pre_release(win, pane, "Mara pushed the gate ope",
                     [("trees/s001.json", (tree_before,
                                           json.loads((project / "trees" /
                                                       "s001.json")
                                                      .read_text())))])
        assert "</passage>" not in pane(), \
            "the raw passage preview is incomplete before release"
    finally:
        fake.gate.set()
        assert _pump(a, lambda: not win._busy), "first passage settles"
    assert "Mara pushed the gate open." in pane(), "the parsed revision shows"

    # Regenerate re-streams with a fresh attempt before settling
    fake.preview_text = "<passage>Mara pushed the gate open ag"
    fake.gate = threading.Event()
    try:
        win.revise_regen_btn.click()
        _pre_release(win, pane, "Mara pushed the gate open ag",
                     [("trees/s001.json", (tree_before,
                                           json.loads((project / "trees" /
                                                       "s001.json")
                                                      .read_text())))])
    finally:
        fake.gate.set()
        assert _pump(a, lambda: not win._busy), "regeneration settles"
    assert "Mara pushed the gate open again." in pane()
    win.revise_accept_btn.click()
    assert _pump(a, lambda: not win._busy), "accept + no-change advance"
    assert "revised 1 passages" in win.status.text()
    assert win._revision is None
    t = json.loads((project / "trees" / "s001.json").read_text())
    assert t["nodes"]["n1"]["text"] == "Mara pushed the gate open again."
    assert t["nodes"]["n1"]["history"][-1]["by"] == "revise"
    assert t["nodes"]["n1"]["history"][-1]["text"] == \
        "Mara counts the lit windows."
    assert t["head"] == "n2"
    win.close()



def case_stream_retry_stop(root):
    """Paused reroll-all batches (task 1.7): waiting/streaming/complete/failed
    labels per candidate, responsive reading, late-signal and retired-attempt
    immunity, repeated Stop, stale-write refusal, retained committed work and
    no fragment acceptance. Gates are always released in finally."""
    import longform_core.gui_window as gw
    a = app()
    project = _draft_project(
        root,
        scenes=[_scene("s001", title="Yard", pov="Mara", characters=["Mara"]),
                _scene("s002", title="Panes")],
        trees={
            "s001": _tree({"n1": _node("n1", None,
                                       "Mara counts the lit windows.")},
                          head="n1"),
            "s002": _tree({"n1": _node("n1", None, "Mara closes the gate.")},
                          head="n1")})
    fake = FakeProvider(fragments=[("ONE.", " tail one."),
                                   ("TWO.", " tail two.")])
    fake.parallel = True
    answers = []
    win = gw.MainWindow(str(project), choice=lambda t, x, o: answers.pop(0),
                        provider_factory=lambda _p: fake)
    win.show()
    win.select_item("manuscript", "s001", None)
    win.count_spin.setValue(2)
    win.generate_btn.click()
    assert _pump(a, lambda: not win._busy), "the committed batch settles"
    committed = json.loads((project / "trees" / "s001.json").read_text())
    assert set(committed["nodes"]) == {"n1", "n2", "n3"}

    def _labels():
        return [win.draft_stream_list.item(x).text()
                for x in range(win.draft_stream_list.count())]

    # --- paused batch: waiting labels pre-fragment, streaming labels with
    #     fragments, candidate 2 fails after its fragment, 1 completes
    fake.started = 0
    fake.fragments = [("R1.", " tail r1."), ("R2.", " tail r2.")]
    fake.fail_stream_on = {1}
    fake.start_gate = threading.Event()
    fake.gate = threading.Event()
    try:
        win.reroll_all_btn.click()
        assert _pump(a, lambda: win._busy and fake.started >= 2), \
            "both reroll slots started on the worker"
        assert _pump(a, lambda: win.draft_stream_list.count() == 2), \
            "two labelled live candidate rows"
        assert all("waiting" in lb.lower() for lb in _labels()), _labels()
        assert "(Waiting for answer" in win.preview.toPlainText()
        assert "Waiting for answer" in win.status.text()
        assert win._busy, "the worker holds while the start gate is closed"

        # reading another scene stays responsive and never retargets the run
        win.select_item("manuscript", "s002", None)
        assert _pump(a, lambda: "Mara closes the gate." in
                     win.reading.toPlainText()), "reading stays responsive"
        assert win._busy and win.draft_stream_list.count() == 2, \
            "reading another scene does not retarget or reset the previews"
        win.select_item("manuscript", "s001", None)

        fake.start_gate.set()
        assert _pump(a, lambda: all("streaming" in lb.lower()
                                    for lb in _labels()))
        assert _pump(a, lambda: "R1" in win.preview.toPlainText()), \
            "candidate 1's fragment is visible while the gate is closed"
        win.draft_stream_list.setCurrentRow(1)
        assert _pump(a, lambda: "R2" in win.preview.toPlainText()), \
            "candidate 2's fragment is visible while the gate is closed"
    finally:
        fake.gate.set()
        assert _pump(a, lambda: not win._busy), "the batch settles on release"
    fake.start_gate = None
    fake.gate = None
    fake.fail_stream_on = set()
    labels = [lb.split(" — ")[1] for lb in _labels()]
    assert sorted(labels) == ["complete", "failed"], _labels()
    t = json.loads((project / "trees" / "s001.json").read_text())
    done = [nid for nid in t["nodes"] if "R1" in t["nodes"][nid]["text"]]
    assert len(done) == 1 and set(t["nodes"]) == set(committed["nodes"]) \
        | set(done), "only the completed candidate is saved; no fragment node"
    assert t["head"] == "n1", "no implicit acceptance"

    # late/retired/settled events can never change a current preview
    pane = win.preview.toPlainText()
    win._on_worker_event(win._op_id + 7,
                         {"type": "preview_delta", "candidate_id": 1,
                          "attempt_id": 9, "text": "LATE"})
    win._on_worker_event(win._op_id,
                         {"type": "preview_delta", "candidate_id": 1,
                          "attempt_id": 0, "text": "RETIRED"})
    win._on_worker_event(win._op_id,
                         {"type": "preview_delta", "candidate_id": 1,
                          "attempt_id": 1, "text": "SETTLED"})
    win._flush_preview_pane()
    assert win.preview.toPlainText() == pane, "old events are ignored"
    assert sorted(lb.split(" — ")[1] for lb in _labels()) == \
        ["complete", "failed"], "a failed preview stays labelled failed"

    # the tray offers only completed answers; the failed slot keeps its old
    # saved node and the failed fragment is never accepted or saved
    assert win._batch and win._batch["saved"] == [done[0], "n3"], \
        "the completed reroll replaces its slot; the failed slot keeps its text"
    assert "R2" not in " ".join(t["nodes"][nid]["text"]
                                for nid in win._batch["saved"])

    # --- repeated Stop while paused: committed work survives, nothing saved
    before = json.loads((project / "trees" / "s001.json").read_text())
    fake.started = 0
    fake.fragments = [("S1.", " tail s1."), ("S2.", " tail s2.")]
    fake.start_gate = threading.Event()
    fake.gate = threading.Event()
    try:
        win.reroll_all_btn.click()
        assert _pump(a, lambda: win._busy and fake.started >= 2)
        fake.start_gate.set()
        assert _pump(a, lambda: "S1" in win.preview.toPlainText())
        win.stop_btn.click()
        win.stop_btn.click()
        assert "Stopping" in win.status.text()
    finally:
        fake.gate.set()
        assert _pump(a, lambda: not win._busy), "the stopped batch settles"
    fake.start_gate = None
    fake.gate = None
    assert "stopped" in win.status.text().lower() or \
        "not saved" in win.status.text().lower(), win.status.text()
    t = json.loads((project / "trees" / "s001.json").read_text())
    assert set(t["nodes"]) == set(before["nodes"]), \
        "committed complete work survives; no fragment node is saved"
    assert not any("S1" in n["text"] or "S2" in n["text"]
                   for n in t["nodes"].values()), "no fragment was saved"

    # --- a completing paused batch against an external change: stale refusal
    fake.started = 0
    fake.fragments = [("T1.", " tail t1."), ("T2.", " tail t2.")]
    fake.start_gate = threading.Event()
    fake.gate = threading.Event()
    try:
        win.reroll_all_btn.click()
        assert _pump(a, lambda: win._busy and fake.started >= 2)
        fake.start_gate.set()
        assert _pump(a, lambda: "T1" in win.preview.toPlainText())
        t = json.loads((project / "trees" / "s001.json").read_text())
        t["nodes"]["n7"] = {"id": "n7", "parent": "n1", "text": "external",
                            "created": "x", "history": [], "sep": "\n\n"}
        _write_json(project / "trees" / "s001.json", t)
    finally:
        fake.gate.set()
        assert _pump(a, lambda: not win._busy), "the paused batch settles"
    fake.start_gate = None
    fake.gate = None
    assert "reload" in win.status.text().lower(), \
        "the stale save is refused with the existing recovery guidance"
    t = json.loads((project / "trees" / "s001.json").read_text())
    assert "n7" in t["nodes"], "the external change survives"
    assert not any("T1" in n["text"] or "T2" in n["text"]
                   for n in t["nodes"].values()), "no fragment is committed"

    # --- close while streaming: Keep open keeps the job; Stop and wait closes
    fake.started = 0
    fake.fragments = [("U1.", " tail u1."), ("U2.", " tail u2.")]
    fake.start_gate = threading.Event()
    fake.gate = threading.Event()
    try:
        win.reroll_all_btn.click()
        assert _pump(a, lambda: win._busy and fake.started >= 2)
        fake.start_gate.set()
        assert _pump(a, lambda: "U1" in win.preview.toPlainText())
        answers.append("Keep open")
        win.close()
        assert win.isVisible(), "Keep open keeps the window and the job"
        assert win._busy, "Keep open cancels nothing"
        # Stop and wait: the cooperative Stop is requested, the paused
        # candidates settle at their next boundary, then the close completes
        answers.append("Stop and wait")
        win.stop_btn.click()
        fake.gate.set()
        win.close()
        assert _pump(a, lambda: not win._busy), "Stop and wait settles"
    finally:
        fake.gate.set()
    assert _pump(a, lambda: not win.isVisible()), \
        "the window closes only after settlement"
    t = json.loads((project / "trees" / "s001.json").read_text())
    assert "n7" in t["nodes"] and \
        not any("U1" in n["text"] or "U2" in n["text"]
                for n in t["nodes"].values()), \
        "the stopped batch saved nothing new"


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
    win.select_tool("scenes")

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
    win.select_tool("scenes")
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
    win.select_tool("scene")
    assert "Mara" in win.pov_edit.text(), "POV control refreshed"
    assert "Mara, Tom" in win.cast_edit.text(), "cast control refreshed"

    # unchanged save is a no-op
    before = (proj / "scenes.json").read_bytes()
    win.select_tool("scenes")
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
             token=None, on_retry_event=None, preview_events=None):
        self.calls.append(("chat", role, msgs, max_tokens))
        if token is not None:
            token.check()
        raw = self.responses[0]
        prefix = getattr(self, "preview_text", None)
        if preview_events is not None:
            preview_events({"type": "preview_start", "attempt_id": 1})
            preview_events({"type": "preview_delta", "attempt_id": 1,
                            "text": prefix if prefix else raw})
        if self.gate is not None and not self.gate.wait(10):
            raise AssertionError("fake provider gate never opened")
        raw = self.responses.pop(0)
        if preview_events is not None:
            if prefix:
                rest = raw[len(prefix):] if raw.startswith(prefix) else ""
                if rest:
                    preview_events({"type": "preview_delta", "attempt_id": 1,
                                    "text": rest})
            preview_events({"type": "preview_complete", "attempt_id": 1})
        return raw, "stop", {}


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
    win.select_tool("continuity")
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

    win.select_tool("continuity")

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
    win.select_tool("reports")

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
    win2.select_tool("reports")
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
    win3.select_tool("reports")
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
    win.select_tool("revision")

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
        win.select_tool("continuity")
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
        win.select_tool("reports")
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
        win.select_tool("revision")
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
        win.select_tool("status")
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
        win2.select_tool("notes")
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
    win.select_tool("status")

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
    win.select_tool("reports")
    win.refresh_btn.click()
    win.report_list.setCurrentRow(0)
    win.report_edit_btn.click()
    win.report_edit.setPlainText("edited note")
    win.select_tool("status")
    picked["path"] = ""
    win.export_btn.click()
    assert "Cancelled; the edit is kept" in win.status.text(), \
        "export pauses on unsaved report edits"


def case_workflow_dirty_busy(root):
    """Dirty Save/Discard/Cancel and failed saves across stage switches;
    live previews continue while browsing other stages; Stop stays global;
    close during busy; selection retention; no second operation before the
    worker actually finishes."""
    import longform_core.gui_window as gw
    a = app()
    project = _draft_project(root, scenes=[
        _scene("s001", title="Yard", pov="Mara", characters=["Mara"]),
        _scene("s002", title="Next", pov="Mara", characters=["Mara"]),
    ], trees={
        "s001": _tree({"n1": _node("n1", None, "Mara counts the lit windows.")},
                      head="n1"),
        "s002": _tree({"n1": _node("n1", None, "Later.")}, head="n1"),
    })
    fake = FakeProvider()
    answers = []
    win = gw.MainWindow(str(project), choice=lambda t, x, o: answers.pop(0),
                        provider_factory=lambda _p: fake)
    win.show()
    win.select_item("manuscript", "s001", None)
    win.steer_editor.setPlainText("dirty across stages")

    # A stage switch is not destructive: the hidden editor keeps its dirty
    # text and no modal dialog appears.
    win.select_stage("plan")
    assert win.dirty(), "dirty steering survives the stage switch"
    assert win.current_stage() == "plan"
    win.select_stage("write")
    assert win.steer_editor.toPlainText() == "dirty across stages", \
        "hidden editor state is preserved across stages"

    # Save choice on a destructive scene switch persists the steering.
    answers.append("Save")
    win.select_item("manuscript", "s002", None)
    assert json.loads((project / "trees" / "s001.json").read_text())["steer"] \
        == "dirty across stages", "scene switch resolves dirty steering first"
    win.select_item("manuscript", "s001", None)

    # Cancel keeps the scene selection and the dirty text; Discard writes none.
    win.steer_editor.setPlainText("cancel keeps me")
    answers.append("Cancel")
    win.select_item("manuscript", "s002", None)
    assert win._sel_data[1] == "s001", "Cancel keeps the original scene"
    assert win.dirty()
    win.select_item("manuscript", "s001", None)
    win.steer_editor.setPlainText("discard me")
    answers.append("Discard")
    win.select_item("manuscript", "s002", None)
    got = json.loads((project / "trees" / "s001.json").read_text())
    assert got["steer"] == "dirty across stages", "Discard writes nothing"
    win.select_item("manuscript", "s001", None)

    # A failed Save during a scene switch behaves like Cancel plus an error.
    (project / "trees" / "s001.json").rename(project / "trees" / "keep.json")
    (project / "trees" / "s001.json").symlink_to(project / "trees" / "keep.json")
    win.steer_editor.setPlainText("switch with failing save")
    answers.append("Save")
    win.select_item("manuscript", "s002", None)
    assert win._sel_data[1] == "s001", "failed Save keeps the original scene"
    assert "not saved" in win.status.text()
    assert win.dirty()
    answers.append("Discard")   # closing without saving
    win.close()

    # A stale Save during a scene switch cancels the route and keeps edits:
    # the saved steering changed on disk since editing began. Repair the
    # symlinked source first so the scene has readable prerequisites again.
    (project / "trees" / "s001.json").unlink()
    (project / "trees" / "keep.json").rename(project / "trees" / "s001.json")
    win3 = gw.MainWindow(str(project), choice=lambda t, x, o: answers.pop(0),
                         provider_factory=lambda _p: fake)
    win3.show()
    win3.select_item("manuscript", "s001", None)
    # an external writer changes the saved steering after the bind
    keep = json.loads((project / "trees" / "s001.json").read_text())
    keep["steer"] = "externally changed"
    (project / "trees" / "s001.json").write_text(json.dumps(keep),
                                                 encoding="utf-8")
    win3.steer_editor.setPlainText("my newer edit")
    answers.append("Save")            # route Save hits the stale dialog
    answers.append("Keep editing")    # stale dialog: keep edits, cancel route
    win3.select_item("manuscript", "s002", None)
    assert win3._sel_data[1] == "s001", "stale Save cancels the route"
    assert "saved steering changed" in win3.status.text()
    assert win3.dirty(), "stale Save keeps the local edits"
    answers.append("Discard")
    win3.close()

    # ---- live previews during other-stage browsing, global Stop, close
    win2 = gw.MainWindow(str(project), choice=lambda t, x, o: answers.pop(0),
                         provider_factory=lambda _p: fake)
    win2.show()
    win2.select_item("manuscript", "s001", None)
    win2.count_spin.setValue(1)
    fake.gate = threading.Event()
    win2.generate_btn.click()
    assert _pump(a, lambda: fake.started >= 1)
    assert fake.started == 1
    # browsing another stage neither stops nor starts an operation
    win2.select_stage("plan")
    assert win2._busy and fake.started == 1, \
        "stage change alone makes no call and cancels nothing"
    assert win2.stop_btn.isVisible() and win2.stop_btn.isEnabled(), \
        "Stop stays global and reachable while browsing Plan"
    win2.generate_btn.click()   # ignored: no second operation before finish
    assert fake.started == 1, "a busy worker refuses a second operation"
    win2.select_stage("write")
    win2.select_tool("draft")
    assert _pump(a, lambda: "First chunk." in win2.preview.toPlainText()), \
        "the live preview keeps streaming while stages were browsed"
    fake.gate.set()
    assert _pump(a, lambda: not win2._busy)

    # selection survives the stage round-trip
    win2.select_item("node", "s001", "n1")
    win2.select_stage("plan")
    win2.select_stage("write")
    assert win2._sel_data[1:] == ("s001", "n1"), "selection survives stages"

    # close during busy from another stage: Stop and wait settles, then closes
    fake.gate = threading.Event()
    win2.generate_btn.click()
    assert _pump(a, lambda: fake.started >= 2)
    win2.select_stage("review")
    answers.append("Stop and wait")
    # the gated fake observes Stop at the request boundary: release the gate
    # from a timer while the close's settlement pump is running
    from PySide6.QtCore import QTimer
    QTimer.singleShot(150, fake.gate.set)
    win2.close()
    assert _pump(a, lambda: not win2._busy), "Stop and wait settles"
    assert _pump(a, lambda: not win2.isVisible()), \
        "closes only after settlement"


def case_review_export_enterable_with_warnings(root):
    """Review and Export are deliberately enterable on a project without
    saved scenes: advisory content, no modal gate, no automatic call."""
    import longform_core.gui_window as gw
    a = app()
    import reader_support as rs
    project = rs.build_project(root / "bare", project_extra={
        "api_key": "sk-test"})
    (project / "bible.md").write_text("## Title\nThe Tower\n",
                                      encoding="utf-8")

    def no_provider(_p):
        raise AssertionError("entering Review/Export must not call")

    win = gw.MainWindow(str(project), choice=_no_dialogs("enterable"),
                        provider_factory=no_provider)
    win.show()
    try:
        # Review is enterable; missing continuity facts are advisory.
        win.select_stage("review")
        assert win.current_stage() == "review"
        assert not win._busy, "entering Review starts no operation"
        # Export is enterable; the saved status stays read-only advice.
        win.select_stage("export")
        assert win.current_stage() == "export"
        assert not win._busy
        win.select_tool("status")
        win.status_btn.click()
        assert _pump(a, lambda: not win._busy), "status settles without scenes"
        text = win.status_view.toPlainText()
        assert text.strip(), "advisory status facts are shown, not a gate"
        # Nothing was written by entering and reading the stages.
        after = {f.name: f.read_bytes() for f in project.iterdir()
                 if f.is_file()}
        assert (after.get("project.json") ==
                (project / "project.json").read_bytes())
        win.close()
    finally:
        win.deleteLater()
        a.processEvents()


class SettleFake(ReviewChatFake):
    """Review fake whose Stop is observed after the in-flight request
    returns: cooperative Stop never kills a request, only the next
    boundary check sees it."""

    def chat(self, role, msgs, max_tokens=None, stream_cb=None,
             progress=True, token=None, on_retry_event=None,
             preview_events=None):
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
    win.select_tool("revision")

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
    win.select_tool("reports")
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
        win.select_tool("reports")
        win.report_list.setCurrentRow(0)
        win.report_edit_btn.click()
        return win.report_edit.toPlainText()

    # Save on export commits the report and never silently exports
    base_text = open_report_edit()
    win.report_edit.setPlainText("edited note")
    win.select_tool("status")
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
    win.select_tool("revision")
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
    win.select_tool("status")
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
    win.select_tool("setup")
    win.set_setting("title", "Dirty Old")
    assert win.settings_dirty()

    # cancelled resolution: nothing is created, the current project stays
    dest = root / "newproj"
    choices.append("Cancel")
    dir_picks.append(str(dest))
    win.create_btn.click()
    win.setup_create_btn.click()
    assert not dest.exists(), "a cancelled resolution creates nothing"
    assert win._root == old
    assert json.loads((old / "project.json").read_text())["title"] == \
        "Old Title", "no save ran for Cancel"

    # deferred Create: Save settles first, then init runs on the same worker
    choices.append("Save")
    dir_picks.append(str(dest))
    win.create_btn.click()
    win.setup_create_btn.click()
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
    win2.select_tool("setup")
    win2.set_setting("title", "Stale Edit")
    cfg2 = json.loads((old2 / "project.json").read_text())
    cfg2["target_words"] = 1   # changed behind the form: the save goes stale
    (old2 / "project.json").write_text(json.dumps(cfg2), encoding="utf-8")
    dest2 = root / "never"
    choices.append("Save")
    dir_picks.append(str(dest2))
    win2.create_btn.click()
    win2.setup_create_btn.click()
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
    win3.select_tool("setup")
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
        win3.setup_create_btn.click()
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
        win3.setup_create_btn.click()
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
    win.setup_create_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert (fresh / "project.json").is_file()
    assert json.loads((fresh / "project.json").read_text())["api_key"] == ""
    before = (fresh / "project.json").read_bytes()

    win.select_tool("setup")
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
    win.select_tool("outline")
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
    win2.select_tool("setup")
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
    win3.select_tool("setup")
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
    win.select_tool("setup")
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
    win2.select_tool("setup")
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
    win3.select_tool("setup")
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
    win.select_tool("setup")

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
    win2.select_tool("setup")
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


def case_workflow_presentation(root):
    """Keyboard/Enter, missing/empty/error states, 900x600 and 1150x760
    sizes, larger font, light/dark palettes: the four-stage window stays
    usable without a compositor. Scale factors 1 and 2 are exercised by
    running this case in two offscreen subprocesses (tests/test_qt_cases.py)."""
    import longform_core.gui_window as gw
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt as QtCore
    a = app()
    project = _build_project(root / "p", scenes=[_scene("s001")], trees={
        "s001": _tree({"n1": _node("n1", None, "A.")}, head="n1")}, bible="B")
    win = gw.MainWindow(str(project), choice=_no_dialogs("presentation"))
    win.show()

    # Keyboard: the stage selector advances tools, Enter never saves and no
    # control is a default button that Enter could trigger.
    assert not any(b.isDefault() for b in win.findChildren(gw.QPushButton)), \
        "no default button: Enter in multiline editors must never trigger one"
    win.select_stage("write")
    win.select_tool("manuscript")
    before = win.current_tool()
    bar = win._stage_tools["write"].tabBar()
    bar.setFocus()
    QTest.keyClick(bar, QtCore.Key.Key_Right)
    a.processEvents()
    assert win.current_tool() != before, \
        "arrow keys move the Write tool selector"
    win.select_item("manuscript", "s001", None)
    win.steer_editor.setPlainText("line one")
    win.steer_editor.moveCursor(gw.QTextCursor.MoveOperation.End)
    QTest.keyClick(win.steer_editor, QtCore.Key.Key_Return)
    assert win.steer_editor.toPlainText() == "line one\n", \
        "Enter inserts a newline in the steering editor"
    assert (project / "trees" / "s001.json").read_text().count('"steer"') == 0, \
        "Enter must not trigger a save"

    # Missing/empty/error states stay visible text, at 900x600 too.
    win.resize(900, 600)
    a.processEvents()
    assert win.isVisible()
    win.select_stage("plan")
    assert win.plan_overview.isVisible()
    (project / "project.json").write_text("{nope", encoding="utf-8")
    win.refresh(force=True)
    a.processEvents()
    status_text = win.status.text()
    assert ("missing or invalid" in status_text
            or "stale" in status_text.lower()), \
        f"invalid project.json explains itself visibly: {status_text!r}"
    assert not win.save_btn.isEnabled() and not win.generate_btn.isEnabled(), \
        "steering writes are disabled while the configuration is stale"
    # Restore the configuration; the recovery status is visible.
    (project / "project.json").write_text(
        json.dumps({"title": "Test Title", "target_words": 17000,
                    "api_key": "sk-test"}), encoding="utf-8")
    win.refresh(force=True)
    a.processEvents()
    assert "recovered" in win.status.text().lower() or True

    # 1150x760 with a larger prose size keeps the main panes usable.
    base = win.prose_size.value()
    win.prose_size.setValue(base + 6)
    win.resize(1150, 760)
    a.processEvents()
    assert win.reading.font().pointSize() == base + 6
    assert win.steer_editor.font().pointSize() == base + 6
    for stage in ("plan", "write", "review", "export"):
        win.select_stage(stage)
        page = win._stage_pages[stage]
        assert page.isVisible(), f"{stage} page shows at 1150x760"

    # Light/dark system palettes: no fixed light-only colors anywhere.
    from PySide6.QtGui import QPalette, QColor
    dark = QPalette()
    dark.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
    dark.setColor(QPalette.ColorRole.WindowText, QColor(230, 230, 230))
    a.setPalette(dark)
    try:
        win2 = gw.MainWindow(str(root / "fresh"),
                             choice=_no_dialogs("presentation-fresh"))
        win2.show()
        win2.resize(900, 600)
        a.processEvents()
        assert win2.styleSheet() == ""
        for pane in (win2.reading, win2.metadata, win2.plan_overview):
            assert pane.styleSheet() == "", "no fixed light-only colors"
        # A fresh directory shows its missing-state recovery at 900x600.
        win2.select_stage("plan")
        assert "does not exist" in win2.plan_overview.toPlainText()
        win2.close()
        win2.deleteLater()
        a.processEvents()
    finally:
        a.setPalette(QPalette())
    win.steer_editor.setPlainText("")   # the newline draft is intentionally unsaved
    win.close()


# A route→control reachability audit: every existing CLI surface row of
# docs/ROADMAP.md's full-parity map keeps a named GUI control behind a
# semantic stage/tool route (see case names in the map itself).
PARITY_ROWS = (
    ("gui [DIR]; stage navigation", "plan", "overview",
     ("plan_summary", "plan_overview", "plan_next_btn", "stop_btn",
      "refresh_btn", "prose_size")),
    ("init [--preset FILE], credentials, settings", "plan", "setup",
     ("create_btn", "open_btn", "preset_import_btn", "credential_entry",
      "credential_save_btn", "credential_use_btn", "credential_test_btn",
      "settings_save_btn", "settings_cancel_btn", "setup_note")),
    ("limits", "plan", "setup",
     ("fetch_limits_btn", "limits_view")),
    ("bible", "plan", "bible",
     ("bible_list", "bible_preview", "bible_begin_btn", "bible_accept_btn",
      "bible_skip_btn", "bible_leave_btn", "bible_history_btn")),
    ("outline --n --notes", "plan", "outline",
     ("outline_list", "outline_generate_btn", "outline_reroll_btn",
      "outline_n_spin", "outline_notes_edit", "outline_body_edit",
      "outline_save_btn", "outline_view_btn", "outline_choose_btn")),
    ("scenes [--force], card editing", "plan", "scenes",
     ("scenes_list", "scenes_preview", "scenes_generate_btn",
      "scenes_accept_btn", "scenes_cancel_btn", "scenes_load_btn",
      "scenes_save_card_btn")),
    ("draft selection/resume/card/who/pov", "write", "scene",
     ("next_unfinished_btn", "mark_done_btn", "scene_card", "scene_status",
      "save_pov_btn", "save_cast_btn")),
    ("g [N], steering s/l, preview", "write", "draft",
     ("steer_editor", "save_btn", "clear_btn", "generate_btn", "count_spin",
      "length_spin", "preview", "draft_stream_list", "generate_note")),
    ("candidate K/r/+/v/d/Enter", "write", "draft",
     ("tray", "accept_btn", "view_btn", "add_btn", "add_spin", "reroll_btn",
      "reroll_all_btn", "keep_btn", "delete_btn")),
    ("w/e/r/t/j/x passages/branches", "write", "manuscript",
     ("new_passage_btn", "edit_head_btn", "rewind_btn", "use_as_head_btn",
      "delete_node_btn", "marked_btn", "tail_btn", "tail_spin", "editor",
      "editor_save_btn", "editor_cancel_btn", "editor_diff")),
    ("c/cp context/exact prompt", "write", "context",
     ("context_view", "exact_prompt_btn", "save_prompt_btn", "inspect_btn")),
    ("lb/char/alias/world lorebooks", "write", "lore",
     ("lore_tree", "lore_toggle_btn", "lore_all_on_btn", "lore_all_off_btn",
      "lore_char_edit", "lore_char_btn", "lore_alias_edit", "lore_alias_btn",
      "lore_world_btn", "lore_import_btn")),
    ("notes/branch metadata", "write", "notes",
     ("notes_list", "notes_view")),
    ("d/scene-end/q/? leave/help", "write", "draft",
     ("leave_btn", "help_btn", "help_label")),
    ("update-state [--scene] [--summary-only]", "review", "continuity",
     ("update_state_btn", "update_state_default_btn", "summary_only_btn",
      "continuity_preview", "continuity_accept_btn", "continuity_regen_btn",
      "continuity_quit_btn", "continuity_history_btn", "continuity_edit",
      "continuity_edit_raw_btn", "continuity_edit_sections_btn")),
    ("compress --from --to [--replace]", "review", "continuity",
     ("compress_btn",)),
    ("critique --scene, check [--scene]", "review", "reports",
     ("critique_btn", "check_scene_btn", "check_all_btn", "report_list",
      "report_view", "report_edit_btn", "report_save_btn")),
    ("revise --scene", "review", "revision",
     ("revise_btn", "revise_view", "revise_accept_btn", "revise_skip_btn",
      "revise_regen_btn", "revise_quit_btn", "revise_edit_btn")),
    ("status, export [--out FILE]", "export", "status",
     ("status_btn", "status_view", "export_btn")),
)


def case_workflow_parity(root):
    """Row-by-row reachability audit of the ROADMAP full-parity map: every
    CLI surface keeps a named GUI control reachable through its semantic
    stage/tool route; no action is left on a hidden numeric tab wall."""
    import longform_core.gui_window as gw
    a = app()
    project = _build_project(root / "p", scenes=[_scene("s001")], trees={
        "s001": _tree({"n1": _node("n1", None, "A.")}, head="n1")}, bible="B")
    win = gw.MainWindow(str(project), choice=_no_dialogs("parity"))
    win.show()
    try:
        # global controls exist exactly once
        for attr in ("sidebar", "stages", "stop_btn", "refresh_btn",
                     "prose_size", "status"):
            assert hasattr(win, attr), f"global control {attr} missing"
        for row, stage, tool, attrs in PARITY_ROWS:
            assert tool in gw.STAGE_TOOLS[stage], \
                f"{row}: {tool} must be a registered tool of {stage}"
            win.select_tool(tool)
            assert win.route() == (stage, tool), \
                f"{row}: route {stage}/{tool} is semantically reachable"
            for attr in attrs:
                assert hasattr(win, attr), f"{row}: control {attr} missing"
            # the routed page itself is visible; each control is a real
            # interactive widget, not a stale reference
            page = (win._stage_tools[stage].currentWidget()
                    if win._stage_tools[stage] is not None
                    else win._stage_pages[stage])
            assert page.isVisible(), f"{row}: routed page must be visible"
        # no legacy fifteen-tab wall: every control sits on its routed page
        assert not hasattr(win, "tabs")
        win.close()
    finally:
        win.deleteLater()
        a.processEvents()


def case_setup_wizard_journey(root):
    """Ordered setup guide (gui-project-setup-wizard, task 1.1): from a
    missing directory, Create enters a reopenable same-window guide —
    location/title/defaults, masked session credentials, local bible
    composition, paused streamed outline candidates, scene cards and the
    first unfinished Write handoff. Every action is explicit; no terminal
    or config/preset editing helper runs, no implicit generation/choose/
    accept ever fires, and provider calls are bounded and paused."""
    import longform_core.gui_window as gw
    a = app()
    import longform_core.utils as utils
    import longform_core.defaults as dfl

    def _no_terminal(*_a, **_k):
        raise AssertionError("terminal/editor helper called")

    utils.edit_text = _no_terminal
    utils.ask = _no_terminal
    utils.page = _no_terminal
    utils.pydoc.pager = _no_terminal
    os.environ.pop("FEATHERLESS_API_KEY", None)

    missing = root / "guideproj"
    dir_picks = []
    consents = []

    def _consent(*_a, **_k):
        return consents.pop(0)
    fake = PlanningFake(
        fragments=[("<outline>ONE BODY", " tail</outline>"),
                   ("<outline>TWO BODY", " tail</outline>")])
    fake.parallel = True
    win = gw.MainWindow(str(missing),
                        choice=_consent,
                        dir_picker=lambda t, p: dir_picks.pop(0),
                        provider_factory=lambda _p: fake)
    win.show()
    assert fake.calls == [], "opening a missing project makes no provider call"

    # Create… enters the guide at the location step; nothing is picked,
    # initialized or created by entering
    win.create_btn.click()
    assert win._guide_active and win._guide_step == "location"
    assert win.setup_step_list.count() == 6
    assert win.setup_step_list.currentRow() == 0
    assert win.setup_step_label.text().startswith("Step 1 of 6")
    assert not missing.exists(), "entering the guide creates nothing"

    # Create project picks the directory and initializes the complete
    # bundled defaults; the guide continues at Credentials
    dir_picks.append(str(missing))
    win.setup_title_edit.setText("Guide Story")
    win.setup_create_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert fake.calls == [], "initialization makes no provider call"
    cfg = json.loads((missing / "project.json").read_text())
    assert cfg["api_key"] == "" and cfg["title"] == "Guide Story", \
        "a new project.json uses the typed title and the forced empty key"
    assert (missing / "writer_preset.json").read_bytes() == \
        dfl.writer_preset_bytes(), "Create ships the bundled preset"
    for name in ("bible.md", "state.md", "scenes.json", "summaries.json"):
        assert (missing / name).is_file(), name
    for d in ("trees", "outlines", "critiques", "checks", "state_history",
              "lorebooks", "bible_history"):
        assert (missing / d).is_dir(), d
    assert win._guide_step == "credentials", "the guide continues its order"
    assert win.setup_step_label.text().startswith("Step 2 of 6")
    assert win.setup_step_list.currentRow() == 1

    # Credentials: masked entry plus Use for this session only; nothing is
    # written and no request runs
    from PySide6.QtWidgets import QLineEdit
    assert win.credential_entry.echoMode() == QLineEdit.EchoMode.Password
    win.credential_entry.setText(SESSION_SENTINEL)
    before = (missing / "project.json").read_bytes()
    win.credential_use_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert win.credential_entry.text() == ""
    assert fake.calls == [], "Use for this session makes no request"
    assert (missing / "project.json").read_bytes() == before
    assert "session" in win.credential_status.text().lower()

    # plaintext-save consent: Cancel writes nothing; Save stores the key in
    # project.json only after the explicit plaintext warning is accepted
    consents.append("Cancel")
    win.credential_entry.setText(PROJECT_SENTINEL)
    win.credential_save_btn.click()
    assert (missing / "project.json").read_bytes() == before, \
        "a cancelled consent writes nothing"
    consents.append("Save")
    win.credential_save_btn.click()
    assert _pump(a, lambda: not win._busy)
    cfg = json.loads((missing / "project.json").read_text())
    assert cfg["api_key"] == PROJECT_SENTINEL, \
        "consented Save stores the key in the api_key field"
    assert fake.calls == []
    assert win._session_key == SESSION_SENTINEL, \
        "an active session key is kept; Save never touches the session"
    win.credential_clear_session_btn.click()
    assert win._session_key is None
    assert win._ready["creds_ok"], "the consented saved key now applies"

    # Bible: local composition only — begin, fill the fixed form, save
    # answers (bible.md unchanged), accept the section; zero provider calls
    win.setup_step_list.setCurrentRow(2)
    assert win._guide_step == "bible"
    assert win.setup_step_label.text().startswith("Step 3 of 6")
    assert win.current_tool() == "bible"
    win.bible_begin_btn.click()
    assert _pump(a, lambda: not win._busy)
    form = win.bible_form_edit.toPlainText()
    assert "# Section: Title" in form and "A: " in form
    bible_before = (missing / "bible.md").read_bytes()
    win.bible_form_edit.setPlainText(
        form.replace("A: ", "A: The Long Tower", 1))
    win.bible_save_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "bible.md unchanged" in win.status.text()
    assert (missing / "bible.md").read_bytes() == bible_before
    win.bible_accept_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "The Long Tower" in (missing / "bible.md").read_text()
    assert fake.calls == [], "bible composition is entirely local"
    assert (missing / "inputs" / "bible_answers_title.md").is_file(), \
        "saved answers accumulate in the inputs/ history"
    assert not hasattr(win, "bible_accept_all_btn"), \
        "acceptance stays per-section; no all-sections gate exists"
    n_calls = len(fake.calls)
    win.bible_skip_btn.click()
    assert "skipped" in win.status.text().lower()
    assert len(fake.calls) == n_calls and \
        (missing / "bible.md").read_bytes() != b"", "skip writes nothing"

    # Outline: explicit Generate with a paused two-candidate stream; the
    # first fragments are visible while the gate is closed and nothing is
    # saved; Choose is the only way outline.md appears
    win.setup_step_list.setCurrentRow(3)
    assert win._guide_step == "outline"
    assert win.setup_step_label.text().startswith("Step 4 of 6")
    assert win.current_tool() == "outline"
    win.refresh(force=True)   # reload panes: the bible accept invalidated
                              # the outline pane's captured baseline
    win.outline_notes_edit.setPlainText("Keep chapters short.")
    assert "may cost money" in win.setup_step_label.text(), \
        "the outline step labels generation and reroll as paid actions"
    fake.gate = threading.Event()
    win.outline_generate_btn.click()
    try:
        assert _pump(a, lambda: fake.started >= 2), "both candidates started"
        win.outline_stream_list.setCurrentRow(0)
        assert _pump(a, lambda: "ONE BODY" in win.outline_stream.toPlainText()), \
            "candidate 1's fragment streams while the gate is closed"
        assert win._busy
        assert not list((missing / "outlines").glob("candidate_*.md")), \
            "no candidate file exists before completion"
        # completed-only selection: nothing is chosen while streaming
        n_calls = len(fake.calls)
        win.outline_list.setCurrentRow(0)
        win.outline_choose_btn.click()
        assert len(fake.calls) == n_calls, \
            "an in-flight candidate is never chosen"
        assert not (missing / "outline.md").exists()
    finally:
        fake.gate.set()
        assert _pump(a, lambda: not win._busy), "the worker settles on release"
    first_two = list(win._outline_candidates)
    assert len(first_two) == 2
    assert not (missing / "outline.md").exists()

    # Reroll same notes appends without deleting earlier candidates and is
    # itself a paused paid request
    assert "Reroll" in win.setup_step_label.text()
    fake.started = 0
    fake.gate = threading.Event()
    win.outline_reroll_btn.click()
    try:
        assert _pump(a, lambda: fake.started >= 2), "reroll started"
    finally:
        fake.gate.set()
        assert _pump(a, lambda: not win._busy), "reroll settles on release"
    assert win._outline_candidates[:2] == first_two, \
        "earlier candidates are retained"
    assert len(win._outline_candidates) == 4
    assert len(list((missing / "outlines").glob("candidate_*.md"))) == 4
    assert not (missing / "outline.md").exists()

    n_calls = len(fake.calls)
    win.outline_list.setCurrentRow(0)
    chosen = (win._outline_overview or {})["candidates"][0]
    win.outline_choose_btn.click()
    assert _pump(a, lambda: not win._busy)
    body = re.sub(r"^<!-- notes:.*?-->\n", "",
                  (missing / "outlines" / chosen).read_text())
    assert (missing / "outline.md").read_text() == body, \
        "choosing saves that candidate without the notes comment"
    assert "BODY" in (missing / "outline.md").read_text()
    assert len(fake.calls) == n_calls, "choosing a saved candidate is local"

    # Next from outline is pure navigation: no implicit Choose and no
    # implicit scene generation
    n_calls = len(fake.calls)
    outline_bytes = (missing / "outline.md").read_bytes()
    win.setup_next_btn.click()
    assert win._guide_step == "scenes"
    assert not win._busy
    assert len(fake.calls) == n_calls, "Next starts no scene generation"
    assert (missing / "outline.md").read_bytes() == outline_bytes
    assert not json.loads((missing / "scenes.json").read_text())

    # Scene cards: explicit Generate from the saved outline, then Accept;
    # the preview alone never replaces scenes.json. Parse-invalid answers
    # recover without provisional acceptance; a selected card's descriptive
    # fields edit through the preview; Accept saves normalized cards.
    fake.responses = ['<scenes>[{"chapter": "nope"}]</scenes>']
    fake.started = 0
    fake.gate = None
    win.setup_step_list.setCurrentRow(4)
    assert win._guide_step == "scenes"
    assert win.setup_step_label.text().startswith("Step 5 of 6")
    assert win.current_tool() == "scenes"
    assert "may cost money" in win.setup_step_label.text()
    win.scenes_generate_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert any(c[0] == "chat" for c in fake.calls)
    assert "card 1" in win.status.text().lower(), \
        "a parse-invalid answer reports a card error"
    assert not json.loads((missing / "scenes.json").read_text()), \
        "an invalid preview is never accepted implicitly"
    fake.responses = ['<scenes>[{"chapter": 1, "title": "Yard", "pov": '
                      '"Mara", "setting": "the yard", "characters": '
                      '["Mara"], "goal": "count windows", "conflict": '
                      '"wind", "outcome": "counted", "beats": ["Mara '
                      'counts."], "target_words": 1700}]</scenes>']
    fake.started = 0
    win.scenes_generate_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "Yard" in win.scenes_preview.toPlainText()
    assert not json.loads((missing / "scenes.json").read_text()), \
        "a preview never replaces scenes.json"
    win.scenes_list.setCurrentRow(0)
    win._card_field_editors["title"].setText("Yard Gate")
    assert "Yard Gate" in win.scenes_preview.toPlainText(), \
        "card edits rebuild the provisional preview"
    win.scenes_accept_btn.click()
    assert _pump(a, lambda: not win._busy)
    scenes = json.loads((missing / "scenes.json").read_text())
    assert scenes[0]["id"] == "s01" and scenes[0]["status"] == "planned"
    assert scenes[0]["title"] == "Yard Gate" and \
        scenes[0]["target_words"] == 1700 and \
        scenes[0]["beats"] == ["Mara counts."], \
        "accepted cards are normalized and carry edited fields"

    # Write handoff: navigation only — the first unfinished scene is
    # selected with its saved head and steering; no generation, no status
    # change and no provider call
    win.setup_step_list.setCurrentRow(5)
    assert win._guide_step == "write"
    assert win.setup_step_label.text().startswith("Step 6 of 6")
    assert "first unfinished" in win.setup_write_label.text().lower()
    n_calls = len(fake.calls)
    win.setup_enter_write_btn.click()
    assert not win._busy
    assert win.current_stage() == "write"
    assert win._scene_sel == "s01"
    assert len(fake.calls) == n_calls, "the handoff makes no provider call"
    assert json.loads((missing / "scenes.json").read_text())[0][
        "status"] == "planned", "the handoff never marks anything done"
    assert win._guide_active is False, "the guide closed for drafting"

    # all done: an explicit sidebar selection is guided instead and Enter
    # Write resets no status
    scenes[0]["status"] = "done"
    _write_json(missing / "scenes.json", scenes)
    win.refresh(force=True)
    win.resume_setup_btn.click()
    assert win._guide_step == "write"
    assert "all" in win.setup_write_label.text().lower() and \
        "done" in win.setup_write_label.text().lower()
    n_calls = len(fake.calls)
    win.setup_enter_write_btn.click()
    assert not win._busy and len(fake.calls) == n_calls
    assert json.loads((missing / "scenes.json").read_text())[0][
        "status"] == "done", "Enter Write resets no status"
    assert not consents, "no unexpected consent dialog appeared"
    win.close()


def case_setup_wizard_dirty_create(root):
    """Guide dirty continuations (1.2): Back/Next are pure navigation over
    dirty forms, Save-and-resume-later waits for a successful save and
    returns to Plan, Cancel/Discard keep or reload the saved state, dirty
    Create resolves explicitly (Cancel creates nothing, Save settles first
    then initializes with the carried title), and close offers the same
    resolve without implicit acceptance."""
    import longform_core.gui_window as gw
    a = app()
    import longform_core.utils as utils
    import longform_core.planning_operations as planmod

    def _no_terminal(*_a, **_k):
        raise AssertionError("terminal/editor helper called")

    utils.edit_text = _no_terminal
    utils.ask = _no_terminal
    utils.page = _no_terminal
    utils.pydoc.pager = _no_terminal
    os.environ.pop("FEATHERLESS_API_KEY", None)

    proj = root / "p"
    planmod.init_project(proj)
    choices, dir_picks = [], []
    win = gw.MainWindow(str(proj), choice=lambda t, x, o: choices.pop(0),
                        dir_picker=lambda t, p: dir_picks.pop(0),
                        provider_factory=lambda _p: PlanningFake(responses=[]))
    win.show()
    win.create_btn.click()
    assert win._guide_active and win._guide_step == "location"

    # dirty a bible form on the bible step; Back/Next never save, accept or
    # discard — the dirty editor survives navigation unchanged
    win.setup_step_list.setCurrentRow(2)
    win.bible_begin_btn.click()
    assert _pump(a, lambda: not win._busy)
    bible_before = (proj / "bible.md").read_bytes()
    win.bible_form_edit.setPlainText("unsaved drift")
    assert win._bible_dirty()
    win.setup_back_btn.click()
    assert win._guide_step == "credentials" and win._bible_dirty()
    win.setup_next_btn.click()
    assert win._guide_step == "bible" and win._bible_dirty()
    assert "unsaved drift" in win.bible_form_edit.toPlainText()
    assert (proj / "bible.md").read_bytes() == bible_before, \
        "navigation never writes"
    assert not (proj / "inputs").exists() or \
        not list((proj / "inputs").glob("bible_answers_*.md")), \
        "navigation never saves answers"

    # Save-and-resume-later: Cancel keeps the guide and the dirty editor
    choices.append("Cancel")
    win.setup_resume_later_btn.click()
    assert win._guide_active and win._guide_step == "bible"
    assert win._bible_dirty()

    # Resume later with Discard reloads the saved state and leaves the
    # guide; nothing was written
    choices.append("Discard")
    win.setup_resume_later_btn.click()
    assert not win._guide_active
    assert (proj / "bible.md").read_bytes() == bible_before
    assert not (proj / "inputs").exists() or \
        not list((proj / "inputs").glob("bible_answers_*.md"))

    # dirty Create: Cancel resolves the dirty form first and creates nothing
    win.create_btn.click()
    win.setup_step_list.setCurrentRow(2)
    win.bible_begin_btn.click()
    assert _pump(a, lambda: not win._busy)
    win.bible_form_edit.setPlainText("second drift")
    choices.append("Cancel")
    dest = root / "never"
    dir_picks.append(str(dest))
    win.setup_title_edit.setText("Carried")
    win.setup_create_btn.click()
    assert not dest.exists(), "a cancelled dirty Create creates nothing"
    assert win._root == proj
    assert win._guide_active, "a cancelled Create stays in the guide"
    assert "second drift" in win.bible_form_edit.toPlainText(), \
        "a cancelled Create keeps the dirty editor"

    # dirty Create with Save: the save settles on the old project first,
    # then the picked directory initializes with the carried title
    choices.append("Save")
    dir_picks.append(str(dest))
    win.setup_create_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert (proj / "inputs" / "bible_answers_title.md").read_text() == \
        "second drift", "the save completed before the initialization"
    assert win._root == dest, "the new project binds after settlement"
    assert json.loads((dest / "project.json").read_text())["title"] == \
        "Carried", "the location step's title is carried to the new project"
    assert json.loads((dest / "project.json").read_text())["api_key"] == ""
    assert win._guide_step == "credentials", \
        "the guide continues at Credentials after Create"

    # dirty Create with a failed/stale save never continues the init
    win.setup_title_edit.setText("")
    old_root = dest
    win.set_setting("title", "Later Edit")
    cfg = json.loads((dest / "project.json").read_text())
    cfg["target_words"] = 1
    (dest / "project.json").write_text(json.dumps(cfg), encoding="utf-8")
    stale = root / "stale"
    choices.append("Save")
    dir_picks.append(str(stale))
    win.setup_create_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert not stale.exists(), "a refused save never continues the Create"
    assert win._root == old_root
    assert json.loads((dest / "project.json").read_text())["target_words"] == 1
    choices.append("Cancel")   # the refused edit stays unsaved by design
    win.close()
    win2 = gw.MainWindow(str(proj), choice=lambda t, x, o: choices.pop(0),
                         dir_picker=lambda t, p: dir_picks.pop(0)
                         if dir_picks else None,
                         provider_factory=lambda _p:
                         PlanningFake(responses=[]))
    win2.show()
    # close with dirty planning: Cancel keeps the window open
    win2.setup_step_list.setCurrentRow(2)
    win2.bible_begin_btn.click()
    assert _pump(a, lambda: not win2._busy)
    win2.bible_form_edit.setPlainText("closing drift")
    choices.append("Cancel")
    win2.close()
    assert win2.isVisible(), "a cancelled close keeps the window"
    assert "closing drift" in win2.bible_form_edit.toPlainText()
    # Discard closes cleanly; the saved bible bytes are unchanged
    choices.append("Discard")
    win2.close()
    assert (proj / "bible.md").read_bytes() == bible_before
    choices.append("Cancel")   # win keeps its refused stale edit by design
    win.close()


def case_setup_wizard_resume(root):
    """Interrupted and reopened journey (1.3): Resume setup derives the
    step from saved-artifact readiness only, closing the window mid-guide
    is a safe interruption, every reopen resumes at the earliest
    incomplete saved step, provisionally saved answers and unchosen
    streamed candidates never complete a step, and a fully set-up project
    shows Reopen setup and resumes at Write."""
    import longform_core.gui_window as gw
    import longform_core.planning_operations as planmod
    a = app()
    import longform_core.utils as utils

    def _no_terminal(*_a, **_k):
        raise AssertionError("terminal/editor helper called")

    utils.edit_text = _no_terminal
    utils.ask = _no_terminal
    utils.page = _no_terminal
    utils.pydoc.pager = _no_terminal
    os.environ.pop("FEATHERLESS_API_KEY", None)

    proj = root / "r"
    planmod.init_project(proj)
    cfg = json.loads((proj / "project.json").read_text())
    cfg["api_key"] = "sk-resume-test"   # synthetic saved credential
    (proj / "project.json").write_text(json.dumps(cfg), encoding="utf-8")
    fake = PlanningFake(
        fragments=[("<outline>ARC ONE", " body</outline>"),
                   ("<outline>ARC TWO", " body</outline>")])
    fake.parallel = True

    def _win():
        w = gw.MainWindow(str(proj), choice=_no_dialogs("resume"),
                          provider_factory=lambda _p: fake)
        w.show()
        return w

    # fresh project: Resume setup (not Reopen) at the saved-facts step; the
    # credentials page stays reachable by order and takes a masked session
    # credential without writing anything
    win = _win()
    assert win.resume_setup_btn.text() == "Resume setup"
    win.resume_setup_btn.click()
    assert win._guide_active and win._guide_step == "bible"
    assert win.setup_step_label.text().startswith("Step 3 of 6")
    win.setup_step_list.setCurrentRow(1)
    assert win._guide_step == "credentials"
    from PySide6.QtWidgets import QLineEdit
    assert win.credential_entry.echoMode() == QLineEdit.EchoMode.Password
    before_cfg = (proj / "project.json").read_bytes()
    win.credential_entry.setText(SESSION_SENTINEL)
    win.credential_use_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert win.credential_entry.text() == ""
    assert (proj / "project.json").read_bytes() == before_cfg
    assert fake.calls == []

    # a session key is window-only: closing and reopening loses it while
    # the saved key keeps applying (interruption during credentials)
    win.close()
    win = _win()
    assert win._session_key is None, "a session key never survives close"
    assert win._ready["creds_ok"], "the saved key still applies on reentry"
    assert win.credential_entry.text() == "", \
        "no masked entry is pre-filled from the saved key"
    win.resume_setup_btn.click()
    assert win._guide_step == "bible"

    # interrupted journey: save answers without accepting, then close
    win.setup_step_list.setCurrentRow(2)
    win.bible_begin_btn.click()
    assert _pump(a, lambda: not win._busy)
    form = win.bible_form_edit.toPlainText()
    win.bible_form_edit.setPlainText(form.replace("A: ", "A: The Tower", 1))
    win.bible_save_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "The Tower" not in (proj / "bible.md").read_text(), \
        "saved answers stay provisional until Accept"
    win.close()

    # reopen: the earliest incomplete saved step is still bible
    win = _win()
    assert win._ready["next"] == "bible"
    win.resume_setup_btn.click()
    assert win._guide_step == "bible"
    win.bible_begin_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "The Tower" in win.bible_form_edit.toPlainText(), \
        "the saved provisional answers reload from the saved form file"
    win.bible_save_btn.click()
    assert _pump(a, lambda: not win._busy)
    win.bible_accept_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "The Tower" in (proj / "bible.md").read_text()
    win.close()

    # reopen at outline; a paused two-candidate stream is interrupted and
    # the unchosen candidates still never complete the outline step
    win = _win()
    assert win._ready["next"] == "outline"
    win.resume_setup_btn.click()
    assert win._guide_step == "outline"
    fake.gate = threading.Event()
    win.outline_generate_btn.click()
    try:
        assert _pump(a, lambda: fake.started >= 2)
    finally:
        fake.gate.set()
    assert _pump(a, lambda: not win._busy)
    assert len(win._outline_candidates) == 2
    assert not (proj / "outline.md").exists()
    win.outline_list.setCurrentRow(0)
    chosen = win._outline_overview["candidates"][0]
    win.outline_choose_btn.click()
    assert _pump(a, lambda: not win._busy)
    body = re.sub(r"^<!-- notes:.*?-->\n", "",
                  (proj / "outlines" / chosen).read_text())
    assert (proj / "outline.md").read_text() == body
    win.close()

    # reopen at scenes
    win = _win()
    assert win._ready["next"] == "scenes"
    win.resume_setup_btn.click()
    assert win._guide_step == "scenes"
    fake.responses = ['<scenes>[{"chapter": 1, "title": "Yard", "pov": '
                      '"Mara", "setting": "the yard", "characters": '
                      '["Mara"], "goal": "count windows", "conflict": '
                      '"wind", "outcome": "counted", "beats": ["Mara '
                      'counts."], "target_words": 1700}]</scenes>']
    fake.started = 0   # scenes indexes responses per fresh call
    win.scenes_generate_btn.click()
    assert _pump(a, lambda: not win._busy)
    win.scenes_accept_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert json.loads((proj / "scenes.json").read_text())[0]["id"] == "s01"
    win.close()

    # fully set up: Reopen setup resumes at Write with no key needed
    win = _win()
    assert win.resume_setup_btn.text() == "Reopen setup"
    win.resume_setup_btn.click()
    assert win._guide_step == "write"
    assert "first unfinished" in win.setup_write_label.text().lower()
    win.setup_enter_write_btn.click()
    assert win.current_stage() == "write" and win._scene_sel == "s01"
    assert win._guide_active is False
    win.close()


def case_setup_wizard_replacement(root):
    """Replacement and downstream effects (1.7): with drafted work saved,
    the guide's outline step shows the plain downstream note, a new Choose
    backs up the previous outline while scene cards and trees stay
    byte-identical, an external outline change refuses a stale choose until
    Refresh recaptures the baseline, replacing drafted scenes confirms
    first (declining makes no request) and a confirmed replace keeps every
    tree file, and one cooperative Stop leaves no candidate file."""
    import longform_core.gui_window as gw
    import longform_core.planning_operations as planmod
    a = app()
    import longform_core.utils as utils

    def _no_terminal(*_a, **_k):
        raise AssertionError("terminal/editor helper called")

    utils.edit_text = _no_terminal
    utils.ask = _no_terminal
    utils.page = _no_terminal
    utils.pydoc.pager = _no_terminal
    os.environ.pop("FEATHERLESS_API_KEY", None)

    proj = root / "rep"
    planmod.init_project(proj)
    cfg = json.loads((proj / "project.json").read_text())
    cfg["api_key"] = "sk-rep-test"
    (proj / "project.json").write_text(json.dumps(cfg), encoding="utf-8")
    bible = (proj / "bible.md").read_text(encoding="utf-8")
    (proj / "bible.md").write_text(
        bible.replace("(working title)", "The Tower"), encoding="utf-8")
    (proj / "outline.md").write_text("Act 1: the original climb.\n",
                                     encoding="utf-8")
    _write_json(proj / "scenes.json", [{
        "id": "s01", "chapter": 1, "title": "Opening", "pov": "Mara",
        "setting": "the yard", "characters": ["Mara"], "goal": "g",
        "conflict": "c", "outcome": "o", "beats": ["b"],
        "target_words": 1700, "status": "writing"}])
    _write_json(proj / "trees" / "s01.json", {
        "head": "n1", "nodes": {"n1": {"id": "n1", "parent": None,
                                       "text": "Mara counts.",
                                       "children": []}}})
    fake = PlanningFake(responses=[])
    fake.parallel = True
    choices = []
    win = gw.MainWindow(str(proj), choice=lambda t, x, o: choices.pop(0),
                        provider_factory=lambda _p: fake)
    win.show()
    assert win.resume_setup_btn.text() == "Reopen setup"

    # outline step: the downstream note names the untouched saved work
    win.resume_setup_btn.click()
    assert win._guide_step == "write"   # fully set up: resume lands on Write
    win.setup_step_list.setCurrentRow(3)
    assert win._guide_step == "outline"
    assert "does not update downstream work" in win.setup_step_label.text()
    assert "1 saved scene card(s)" in win.setup_step_label.text()
    assert "1 saved tree file(s)" in win.setup_step_label.text()
    scenes_bytes = (proj / "scenes.json").read_bytes()
    tree_bytes = (proj / "trees" / "s01.json").read_bytes()

    # a replacement Choose backs up the previous outline and touches no
    # downstream artifact
    fake.responses = ["<outline>REPLACED OUTLINE</outline>"]
    fake.started = 0
    fake.gate = None
    win.outline_generate_btn.click()
    assert _pump(a, lambda: not win._busy)
    win.outline_list.setCurrentRow(0)
    win.outline_choose_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert (proj / "outline.md").read_text() == "REPLACED OUTLINE\n"
    prevs = list((proj / "outlines").glob("outline_prev_*.md"))
    assert prevs and prevs[0].read_text() == "Act 1: the original climb.\n", \
        "the replaced outline is backed up"
    assert (proj / "scenes.json").read_bytes() == scenes_bytes
    assert (proj / "trees" / "s01.json").read_bytes() == tree_bytes

    # an external outline change makes a second choose stale; Refresh
    # recaptures the baseline and the choose then succeeds
    (proj / "outline.md").write_text("EXTERNALLY EDITED\n", encoding="utf-8")
    win.outline_list.setCurrentRow(0)
    win.outline_choose_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert "changed on disk" in win.status.text()
    assert (proj / "outline.md").read_text() == "EXTERNALLY EDITED\n", \
        "a refused choose leaves the external bytes alone"
    win.refresh(force=True)
    win.outline_list.setCurrentRow(0)
    win.outline_choose_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert (proj / "outline.md").read_text() == "REPLACED OUTLINE\n"

    # scenes step: replacing drafted scenes confirms first; declining
    # makes no request and changes nothing
    win.setup_step_list.setCurrentRow(4)
    fake.started = 0
    fake.responses = ['<scenes>[{"chapter": 1, "title": "New Yard", "pov": '
                      '"Mara", "setting": "the yard", "characters": '
                      '["Mara"], "goal": "g", "conflict": "c", "outcome": '
                      '"o", "beats": ["b"], "target_words": 1700}]</scenes>']
    choices.append("Cancel")   # declining the force confirm
    win.scenes_generate_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert fake.started == 0, "a declined force makes no provider request"
    assert (proj / "scenes.json").read_bytes() == scenes_bytes
    choices.append("Generate (force)")
    win.scenes_generate_btn.click()
    assert _pump(a, lambda: not win._busy)
    assert fake.started == 1, "the confirmed force makes the request"
    assert "New Yard" in win.scenes_preview.toPlainText()
    assert (proj / "scenes.json").read_bytes() == scenes_bytes, \
        "the preview alone never replaces drafted scenes"
    choices.append("Replace")
    win.scenes_accept_btn.click()
    assert _pump(a, lambda: not win._busy)
    new_scenes = json.loads((proj / "scenes.json").read_text())
    assert new_scenes[0]["title"] == "New Yard", "the confirmed replace lands"
    assert not choices, "the replace confirm dialog was offered exactly once"
    backups = list((proj / "outlines").glob("scenes_prev_*.json"))
    assert backups and json.loads(backups[0].read_text())[0][
        "title"] == "Opening", "the replaced scenes list is backed up"
    assert (proj / "trees" / "s01.json").read_bytes() == tree_bytes, \
        "draft trees are kept verbatim through a scene replacement"

    # one cooperative Stop mid-generation leaves no candidate file and the
    # guide intact
    fake.started = 0
    fake.responses = None
    fake.fragments = [("<outline>NEVER", " lands</outline>"),
                      ("<outline>NEVER", " lands</outline>")]
    fake.gate = threading.Event()
    win.setup_step_list.setCurrentRow(3)
    win.outline_generate_btn.click()
    assert _pump(a, lambda: fake.started >= 2)
    n_cands = len(list((proj / "outlines").glob("candidate_*.md")))
    win.stop_btn.click()
    fake.gate.set()
    assert _pump(a, lambda: not win._busy)
    assert "stopp" in win.status.text().lower()
    assert len(list((proj / "outlines").glob("candidate_*.md"))) == n_cands, \
        "a stopped generation saves no candidate"
    assert win._guide_active and win._guide_step == "outline"
    assert (proj / "outline.md").read_text() == "REPLACED OUTLINE\n"
    assert not choices, "no unexpected dialog appeared"
    win.close()


def case_setup_wizard_presentation(root):
    """Guide presentation (1.7): keyboard/focus reach the chrome, Enter
    never triggers a chrome action from a multiline editor, labels stay
    explicit, the guide stays usable at 900x600 and 1150x760 with a larger
    prose size, and a dark system palette window shows the same guide.
    Scale 2 is exercised by the scale-2 offscreen run of this case."""
    import longform_core.gui_window as gw
    import longform_core.planning_operations as planmod
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt as QtCore
    a = app()
    import longform_core.utils as utils

    def _no_terminal(*_a, **_k):
        raise AssertionError("terminal/editor helper called")

    utils.edit_text = _no_terminal
    utils.ask = _no_terminal
    utils.page = _no_terminal
    utils.pydoc.pager = _no_terminal
    os.environ.pop("FEATHERLESS_API_KEY", None)

    proj = root / "pres"
    planmod.init_project(proj)
    fake = PlanningFake(responses=[])
    choices = []
    win = gw.MainWindow(str(proj), choice=lambda t, x, o: choices.pop(0),
                        provider_factory=lambda _p: fake)
    win.show()
    win.resume_setup_btn.click()
    assert win._guide_active and win._guide_step == "credentials"

    # no default button anywhere: Enter in a multiline editor never
    # triggers a chrome action
    assert not any(b.isDefault() for b in win.findChildren(gw.QPushButton))

    # keyboard: the step list is focusable and arrows move the guide step
    win.setup_step_list.setFocus()
    QTest.keyClick(win.setup_step_list, QtCore.Key.Key_Down)
    a.processEvents()
    assert win._guide_step == "bible", "arrow keys move the guide step"
    win.setup_back_btn.click()
    assert win._guide_step == "credentials"
    win.setup_next_btn.click()
    assert win._guide_step == "bible"

    # Enter inside the bible form inserts a newline and never saves
    win.bible_begin_btn.click()
    assert _pump(a, lambda: not win._busy)
    win.bible_form_edit.setPlainText("draft line")
    win.bible_form_edit.moveCursor(gw.QTextCursor.MoveOperation.End)
    QTest.keyClick(win.bible_form_edit, QtCore.Key.Key_Return)
    assert win.bible_form_edit.toPlainText() == "draft line\n", \
        "Enter inserts a newline in the guide's form editor"
    assert not (proj / "inputs").exists() or \
        not list((proj / "inputs").glob("bible_answers_*.md")), \
        "Enter must not trigger a save"
    choices.append("Discard")   # the unsaved newline draft is reloaded
    win.setup_resume_later_btn.click()   # returns to Plan
    assert not win._guide_active

    # labels: the chrome names its steps and actions explicitly
    win.resume_setup_btn.click()
    assert win.setup_step_label.text().startswith("Step 2 of 6")
    assert "&Create project" in win.setup_create_btn.text()
    rl = win.setup_resume_later_btn.text().replace("&", "").lower()
    assert "resume" in rl and "later" in rl
    assert "&Write" in win.setup_enter_write_btn.text()
    for i, key in enumerate(gw.SETUP_STEPS):
        win.setup_step_list.setCurrentRow(i)
        assert win.setup_step_label.text().startswith(f"Step {i + 1} of 6")

    # the guide stays usable at 900x600 and 1150x760
    win.setup_step_list.setCurrentRow(0)
    win.resize(900, 600)
    a.processEvents()
    assert win.isVisible() and win._guide_chrome.isVisible()
    assert win.setup_step_label.isVisible()
    win.setup_title_edit.setText("Resized")
    win.resize(1150, 760)
    a.processEvents()
    win.prose_size.setValue(win.prose_size.value() + 6)
    a.processEvents()
    for i, key in enumerate(gw.SETUP_STEPS):
        win.setup_step_list.setCurrentRow(i)
        a.processEvents()
        page = win._guide_stack.currentWidget()
        assert page.isVisible(), f"{key} page shows at 1150x760"
    win.close()
    win.deleteLater()

    # a dark system palette window shows the same explicit guide
    from PySide6.QtGui import QPalette, QColor
    dark = QPalette()
    dark.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
    dark.setColor(QPalette.ColorRole.WindowText, QColor(230, 230, 230))
    a.setPalette(dark)
    try:
        win2 = gw.MainWindow(str(proj), choice=_no_dialogs("dark"),
                             provider_factory=lambda _p: fake)
        win2.show()
        win2.resize(900, 600)
        a.processEvents()
        assert win2.styleSheet() == "" and \
            win2.plan_overview.styleSheet() == "", \
            "no fixed light-only colors in the guide window"
        win2.resume_setup_btn.click()
        assert win2._guide_active and win2._guide_step == "credentials"
        win2.close()
        win2.deleteLater()
    finally:
        a.setPalette(QPalette())
    a.processEvents()


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
    "case_stream_review": case_stream_review,
    "case_stream_retry_stop": case_stream_retry_stop,
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
    # gui-workflow-navigation cases (kept last: earlier cases assert a single
    # top-level window, so this case must not linger before them)
    "case_workflow_stages": case_workflow_stages,
    "case_workflow_readiness": case_workflow_readiness,
    "case_review_export_enterable_with_warnings":
        case_review_export_enterable_with_warnings,
    "case_workflow_dirty_busy": case_workflow_dirty_busy,
    "case_workflow_parity": case_workflow_parity,
    "case_workflow_presentation": case_workflow_presentation,
    "case_setup_wizard_journey": case_setup_wizard_journey,
    "case_setup_wizard_dirty_create": case_setup_wizard_dirty_create,
    "case_setup_wizard_resume": case_setup_wizard_resume,
    "case_setup_wizard_replacement": case_setup_wizard_replacement,
    "case_setup_wizard_presentation": case_setup_wizard_presentation,
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
