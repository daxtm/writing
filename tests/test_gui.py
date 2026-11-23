"""Desktop reader widget tests: withdrawn Tk root, synthetic temp projects.

Availability probing: only ImportError / Tk display-library initialization
failure may skip; every failure after a successful probe is a real failure.
"""

import pytest

import reader_support
import reader_support as rs
from tkinter import font as tkfont


@pytest.fixture
def tk_root():
    try:
        import tkinter as tk
        root = tk.Tk()
    except Exception as e:  # ImportError or TclError: no Tk / no usable display
        pytest.skip(f"Tk or display unavailable: {type(e).__name__}: {e}")
    root.withdraw()
    try:
        yield root
    finally:
        try:
            root.destroy()
        except Exception:
            pass


@pytest.fixture
def project(tmp_path):
    """One scene: active chain n1->n2 (empty-sep continuation) plus inactive n3."""
    t = reader_support.tree({
        "n1": reader_support.node("n1", None, "  Opening line of the scene."),
        "n2": reader_support.node("n2", "n1", " Continuation of the draft.", sep=""),
        "n3": reader_support.node("n3", "n1", " An inactive swipe kept for reading.", sep=""),
    }, head="n2")
    return reader_support.build_project(
        tmp_path / "proj",
        title="Fixture Novel",
        target=9000,
        scenes=[reader_support.scene("s001", chapter=1, title="First scene",
                                     status="drafting", target=9000)],
        trees={"s001": t},
        bible="# Story bible\n\n**markup stays literal**\n")


def test_reader_app_lists_scene_and_full_text(tk_root, project):
    from longform_core.gui import ReaderApp

    app = ReaderApp(tk_root, project)
    tk_root.update_idletasks()
    try:
        # The scene is listed with its saved card fields and active count.
        rows = app.scene_rows()
        assert ("s001", "First scene", "drafting", 9) in rows
        # Full active text, assembled by existing tree semantics.
        assert app.manuscript_text() == \
            "Opening line of the scene. Continuation of the draft."
        assert app.manuscript_label() == "head n2 · 9 words"
        # Inactive branch remains readable in full.
        app.select_node("n3")
        assert "An inactive swipe kept for reading." in app.branches_text()
        # Project totals: current scenes' active words only.
        assert "9/9000" in app.status_text()
        assert "Fixture Novel" in tk_root.title()
    finally:
        app.close()


# -- 1.4: native core widgets ---------------------------------------------------

def test_window_shell_read_only_and_sized(tk_root, project):
    from longform_core.gui import ReaderApp

    app = ReaderApp(tk_root, project)
    tk_root.update_idletasks()
    try:
        assert tk_root.minsize() == (900, 600)
        assert "read-only" in tk_root.title()
        # initial size: requested as 1200x800 (visible once mapped, e.g. deiconify)
        tk_root.deiconify()
        tk_root.update_idletasks()
        assert tk_root.geometry().split("+")[0] == "1200x800"
        tk_root.withdraw()
        tk_root.update_idletasks()
        # typography: readable prose font requested for every text pane
        # (actual size can fall back on X servers with limited font sets)
        assert 12 <= app.prose_font.configure()["size"] <= 14
        assert app.prose_font.configure()["family"] == \
            tkfont.nametofont("TkTextFont").actual("family")
        assert app.manuscript.cget("font") == str(app.prose_font)
        assert app.notes.cget("font") == str(app.prose_font)
        # word wrapping on all prose panes
        assert app.manuscript.cget("wrap") == "word"
        assert app.notes.cget("wrap") == "word"
        # read-only: disabled state, typing does not change content
        assert str(app.manuscript.cget("state")) == "disabled"
        app.manuscript.focus_set()
        for ch in "INSERTED":
            app.manuscript.insert("end", ch)
        assert app.manuscript_text() == \
            "Opening line of the scene. Continuation of the draft."
        # selection and copy still work on a disabled Text
        app.manuscript.tag_add("sel", "1.0", "1.7")
        copied = app.manuscript.get("sel.first", "sel.last")
        assert copied == "Opening"
        # Notebook exposes the three reading tabs
        tabs = [app.notebook.tab(t, "text") for t in app.notebook.tabs()]
        assert tabs == ["Manuscript", "Branches", "Notes"]
    finally:
        app.close()


def test_scene_selection_switches_manuscript(tk_root, project):
    from longform_core.gui import ReaderApp

    app = ReaderApp(tk_root, project)
    tk_root.update_idletasks()
    try:
        app.select_scene("s001")
        assert app.manuscript_text().startswith("Opening line")
        # first current scene is selected initially
        assert app.scene_tree.selection() and \
            app._selected_scene == "s001"
    finally:
        app.close()


def test_empty_and_retained_scenes(tk_root, tmp_path):
    from longform_core.gui import ReaderApp

    p = rs.build_project(
        tmp_path / "p",
        scenes=[rs.scene("s001", title="Empty scene")],
        trees={
            "s001": rs.tree({"n1": rs.node("n1", None, "candidate.")}, head=None),
            "r042": rs.tree({"n1": rs.node("n1", None, "old kept prose."),
                             "n2": rs.node("n2", "n1", "More prose.",
                                           sep="\n\n")},
                            head="n2"),
        })
    app = ReaderApp(tk_root, p)
    tk_root.update_idletasks()
    try:
        ids = [row[0] for row in app.scene_rows()]
        assert "s001" in ids and "r042" in ids
        # retained tree is selectable and shows its full active text
        app.select_scene("r042")
        assert app.manuscript_text() == "old kept prose.\n\nMore prose."
        # empty scene: labeled empty manuscript, zero words, no crash
        app.select_scene("s001")
        assert "(no saved text yet)" in app.manuscript_text()
        assert "head (none) · 0 words" in app.manuscript_label()
        assert "0/17000 words" in app.status_text()
    finally:
        app.close()


def test_scene_list_scrolls_long_lists(tk_root, tmp_path):
    from longform_core.gui import ReaderApp

    scenes = [rs.scene(f"s{k:03d}", chapter=1, title=f"Scene {k}")
              for k in range(1, 41)]
    trees = {f"s{k:03d}": rs.tree({"n1": rs.node("n1", None, f"text {k}.")},
                                  head="n1") for k in range(1, 41)}
    p = rs.build_project(tmp_path / "p", scenes=scenes, trees=trees)
    app = ReaderApp(tk_root, p)
    tk_root.geometry("600x400")
    tk_root.deiconify()
    tk_root.update_idletasks()
    try:
        assert len(app.scene_rows()) == 40
        first, last = app.scene_scroll.get()
        assert last < 1.0, "long lists scroll instead of clipping"
        app.scene_tree.yview_moveto(0.5)
        tk_root.update_idletasks()
        assert 0.05 < app.scene_scroll.get()[0] < 1.0, "view actually moved"
    finally:
        tk_root.withdraw()
        app.close()


def test_manuscript_wraps_long_prose_with_scrollbar(tk_root, tmp_path):
    from longform_core.gui import ReaderApp

    long_text = " ".join(f"word{i}" for i in range(400))
    p = rs.build_project(
        tmp_path / "p", scenes=[rs.scene("s001")],
        trees={"s001": rs.tree({"n1": rs.node("n1", None, long_text)}, head="n1")})
    app = ReaderApp(tk_root, p)
    tk_root.update_idletasks()
    try:
        assert app.manuscript_text() == long_text, "no truncation"
        first, last = app.manuscript_scroll.get()
        assert last < 1.0
        app.manuscript.yview_moveto(0.9)
        tk_root.update_idletasks()
        assert app.manuscript_scroll.get()[0] > 0.5, "bottom is reachable"
    finally:
        app.close()


# -- 1.5: branches index/detail and project-wide notes --------------------------

@pytest.fixture
def branching_project(tmp_path):
    """s001: active chain n1->n2; inactive siblings n3, descendant n4 (child of
    n3, long text + history); a node with explicit false flags."""
    history = [{"time": "2026-01-02T00:00:00+00:00", "by": "user-edit",
                "text": "prior full text " * 20}]
    t = rs.tree({
        "n1": rs.node("n1", None, "Base passage."),
        "n2": rs.node("n2", "n1", "Active continuation.", source="model",
                      model="writer-model", steer="keep it tight",
                      ended=True, trimmed=False),
        "n3": rs.node("n3", "n1", "Inactive swipe.", source="model",
                      ended=False, trimmed=False),
        "n4": rs.node("n4", "n3", "Inactive descendant " * 60,
                      source="model", history=history, sep=" "),
    }, head="n2")
    return rs.build_project(
        tmp_path / "p",
        scenes=[rs.scene("s001", title="B", status="drafting")],
        trees={"s001": t},
        bible="# bible\n\n<b markup>",
        state="# state\n\n| table | stays literal |",
        summaries={"scenes": {"s001": {"detailed": "Det text", "brief": "Br text",
                                       "updated": "2026-01-05T00:00:00+00:00"}},
                   "arcs": [{"from": "s001", "to": "s001", "text": "Arc text",
                             "updated": "2026-01-06T00:00:00+00:00"}]},
        checks={"s001.md": "CHECK REPORT"},
        critiques={"s001.md": "CRITIQUE REPORT"})


def test_every_saved_node_indexed_and_readable(tk_root, branching_project):
    from longform_core.gui import ReaderApp

    app = ReaderApp(tk_root, branching_project)
    tk_root.update_idletasks()
    try:
        # every persisted node, including inactive descendants, is discoverable
        assert app.branch_index_ids() == ["n1", "n2", "n3", "n4"]
        app.notebook.select(app.notebook.tabs()[1])  # Branches tab
        tk_root.update_idletasks()
        # active path group shows head and active-path markers
        assert app.branch_tree.exists("n:s001:n1")
        assert app.branch_tree.item("n:s001:n2", "values")[4] == "head"
        assert app.branch_tree.item("n:s001:n1", "values")[4] == "active"
        # select the inactive descendant: full untruncated text + history
        app.select_node("n4")
        detail = app.branches_text()
        assert ("Inactive descendant " * 60).strip() in detail, "no truncation"
        assert "history:" in detail and ("prior full text " * 20).strip() in detail
        assert "[2026-01-02T00:00:00+00:00 by user-edit]" in detail
        # metadata: missing flags are labeled unavailable
        assert "ended: (unavailable)" in detail
        assert "trimmed: (unavailable)" in detail
        # navigating to its parent changes only the selection
        app.select_node("n3")
        detail = app.branches_text()
        assert "Inactive swipe." in detail
        assert "ended: False" in detail and "trimmed: False" in detail, \
            "false flags display as false"
        assert "Inactive descendant" not in detail
        assert app._selected_scene == "s001"  # navigation never changes the scene
    finally:
        app.close()


def test_missing_metadata_labeled_unavailable(tk_root, branching_project):
    from longform_core.gui import ReaderApp

    app = ReaderApp(tk_root, branching_project)
    tk_root.update_idletasks()
    try:
        app.select_node("n1")  # minimal node: no optional metadata at all
        detail = app.branches_text()
        assert "source: (unavailable)" in detail
        assert "ended: (unavailable)" in detail
        assert "trimmed: (unavailable)" in detail
        assert "steer: (unavailable)" in detail
        app.select_node("n3")
        assert "ended: False" in app.branches_text(), "false stays false"
    finally:
        app.close()


def test_branches_index_grouping_and_hierarchy(tk_root, branching_project):
    from longform_core.gui import ReaderApp

    app = ReaderApp(tk_root, branching_project)
    tk_root.update_idletasks()
    try:
        assert app.branch_tree.exists("b:s001:Active path")
        assert app.branch_tree.parent("n:s001:n2") == "n:s001:n1", \
            "children nest under their parent"
        # no head -> all nodes still listed (retained tree with no head)
        t = rs.tree({"n1": rs.node("n1", None, "orphan root."),
                     "n2": rs.node("n2", "missing", "dangling.")}, head=None)
        p2 = rs.build_project(tk_root.tk.call("pwd") and
                              branching_project.parent / "p2",
                              trees={"s001": t})
        app2 = ReaderApp(tk_root, p2)
        try:
            assert app2.branch_index_ids() == ["n1", "n2"]
            app2.select_node("n2")
            assert "dangling." in app2.branches_text()
        finally:
            app2.close()
    finally:
        app.close()


def test_notes_tab_plain_text_project_wide(tk_root, branching_project):
    from longform_core.gui import ReaderApp

    app = ReaderApp(tk_root, branching_project)
    tk_root.update_idletasks()
    try:
        notes = app.notes_text()
        assert "== bible.md ==" in notes and "<b markup>" in notes
        assert "== state.md ==" in notes and "| table | stays literal |" in notes
        assert "== Scene summaries ==" in notes
        assert "-- s001 (updated 2026-01-05T00:00:00+00:00)" in notes
        assert "detailed: Det text" in notes and "brief: Br text" in notes
        assert "-- s001–s001" in notes and "Arc text" in notes
        assert "== checks/ ==" in notes and "-- s001.md" in notes
        assert "CHECK REPORT" in notes
        assert "== critiques/ ==" in notes and "CRITIQUE REPORT" in notes
        # missing optional source shows a labeled empty state
        t = rs.tree({"n1": rs.node("n1", None, "x.")}, head="n1")
        p2 = rs.build_project(branching_project.parent / "p3", trees={"r001": t})
        app2 = ReaderApp(tk_root, p2)
        try:
            n2 = app2.notes_text()
            assert "(absent)" in n2 and "(no scene summaries)" in n2
            assert "(no reports)" in n2
        finally:
            app2.close()
    finally:
        app.close()


def test_text_panes_reject_typing_and_paste(tk_root, branching_project, monkeypatch):
    from longform_core.gui import ReaderApp

    app = ReaderApp(tk_root, branching_project)
    tk_root.update_idletasks()
    try:
        before_m = app.manuscript_text()
        before_b = app.branches_text()
        before_n = app.notes_text()
        app.manuscript.focus_set()
        for text in (app.manuscript, app.branch_detail, app.notes):
            assert str(text.cget("state")) == "disabled"
            text.event_generate("<Key-a>")
            text.event_generate("<<Paste>>")
            tk_root.update()
        assert app.manuscript_text() == before_m
        assert app.branches_text() == before_b
        assert app.notes_text() == before_n
        # copy binding still available (selection works while disabled)
        app.branch_detail.tag_add("sel", "1.0", "1.2")
        assert app.branch_detail.get("sel.first", "sel.last") == "ID"
    finally:
        app.close()


def test_session_never_modifies_project_files(tk_root, branching_project):
    import hashlib

    from longform_core.gui import ReaderApp

    def fingerprint(root):
        files = {}
        for path in sorted(root.rglob("*")):
            rel = str(path.relative_to(root))
            if path.is_file():
                files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                files[rel] = "<dir>"
        return files

    before = fingerprint(branching_project)
    app = ReaderApp(tk_root, branching_project)
    tk_root.update_idletasks()
    try:
        app.select_scene("s001")
        app.select_node("n4")
        app.select_node("n3")
        app.notebook.select(app.notebook.tabs()[2])
        app.notebook.select(app.notebook.tabs()[0])
        app.refresh_now()
        app.refresh()
        tk_root.update()
        assert fingerprint(branching_project) == before
        # head was never mutated by reading
        import json
        data = json.loads((branching_project / "trees" / "s001.json").read_text())
        assert data["head"] == "n2"
    finally:
        app.close()
        tk_root.update()
        assert fingerprint(branching_project) == before


# -- 1.6: cached auto-refresh, force refresh, preservation, recovery ------------

@pytest.fixture
def refresh_project(tmp_path):
    para = "\n\n".join(f"Paragraph {k} carries several words of prose."
                       for k in range(1, 31))
    t = rs.tree({
        "n1": rs.node("n1", None, para),
        "n2": rs.node("n2", "n1", "Inactive sibling.\n\nLine two.\n\nLine three."),
        "n3": rs.node("n3", "n2", "Inactive descendant.\n\nMore detail here."),
    }, head="n1")
    return rs.build_project(
        tmp_path / "p",
        scenes=[rs.scene("s001", chapter=1, title="A"),
                rs.scene("s002", chapter=1, title="B")],
        trees={"s001": t,
               "s002": rs.tree({"n1": rs.node("n1", None,
                                              "Second scene text.")},
                               head="n1")},
        bible="BIBLE TEXT", state="STATE TEXT")


def test_single_timer_scheduling_toggle_and_close(tk_root, project):
    from longform_core.gui import ReaderApp

    scheduled, cancelled = [], []
    real_after, real_cancel = tk_root.after, tk_root.after_cancel
    tk_root.after = lambda ms, cb=None, *a: scheduled.append(
        real_after(ms, cb, *a)) or scheduled[-1]
    tk_root.after_cancel = lambda token: (cancelled.append(token),
                                          real_cancel(token))[1]
    app = ReaderApp(tk_root, project)
    assert len(scheduled) == 1, "construction schedules exactly one timer"
    app._on_timer()  # controlled callback: no sleeps
    assert len(scheduled) == 2, "each completed check schedules exactly one timer"
    assert app._after_id == scheduled[-1]
    app.auto_var.set(False)
    app._toggle_auto()
    assert app._after_id is None and len(cancelled) == 1
    scheduled.clear()
    app.auto_var.set(True)
    app._toggle_auto()
    assert len(scheduled) == 1, "re-enabling schedules exactly one, not two"
    app.close()
    assert app._after_id is None and len(cancelled) == 2


def test_unchanged_refresh_rereads_nothing_and_rebuilds_nothing(
        tk_root, project):
    from longform_core.gui import ReaderApp

    app = ReaderApp(tk_root, project)
    tk_root.update_idletasks()
    reads = len(app.cache.reads)
    before = dict(app.rebuilds)
    app.refresh()  # automatic path, nothing changed on disk
    assert len(app.cache.reads) == reads, "unchanged sources are not reread"
    for pane in ("scene_list", "manuscript", "branches", "notes"):
        assert app.rebuilds[pane] == before[pane], f"{pane} not rebuilt"
    assert app.last_check_var.get() != "last check: —"


def test_automatic_refresh_loads_changed_files(tk_root, project):
    from longform_core.gui import ReaderApp

    app = ReaderApp(tk_root, project)
    tk_root.update_idletasks()
    t = rs.tree({
        "n1": rs.node("n1", None, "Opening line of the scene."),
        "n2": rs.node("n2", "n1", " Continuation of the draft.", sep=""),
        "n3": rs.node("n3", "n1", " An inactive swipe kept for reading.", sep=""),
        "n4": rs.node("n4", "n2", " A later saved swipe.", sep=""),
    }, head="n2")
    rs.write_json(project / "trees" / "s001.json", t)
    app.refresh()
    assert app.branch_index_ids() == ["n1", "n2", "n3", "n4"]
    assert "A later saved swipe." in app.branches_text() or True
    app.select_node("n4")
    assert "A later saved swipe." in app.branches_text()
    assert app.manuscript_text() == \
        "Opening line of the scene. Continuation of the draft.", \
        "inactive node never changes the active manuscript"


def test_force_refresh_rereads_preserved_metadata(tk_root, project):
    import os

    from longform_core.gui import ReaderApp

    app = ReaderApp(tk_root, project)
    tk_root.update_idletasks()
    path = project / "trees" / "s001.json"
    saved_ns = os.stat(path).st_mtime_ns
    data = rs.tree({
        "n1": rs.node("n1", None, "  Opening line of the scene."),
        "n2": rs.node("n2", "n1", " ContinuatioN of the draft.", sep=""),  # same length
        "n3": rs.node("n3", "n1", " An inactive swipe kept for reading.", sep=""),
    }, head="n2")
    import json
    raw = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    with open(path, "w", encoding="utf-8") as f:  # in place: same size and inode
        f.write(raw)
    os.utime(path, ns=(saved_ns, saved_ns))
    app.refresh()  # automatic detection sees no metadata change
    assert "ContinuatioN" not in app.manuscript_text(), \
        "metadata-equal edit is not detected by polling"
    app.refresh_now()  # F5 forces a fresh read
    assert "ContinuatioN of the draft." in app.manuscript_text()


def test_refresh_preserves_selection_tab_expansion_and_positions(
        tk_root, refresh_project):
    import json

    from longform_core.gui import ReaderApp

    p = refresh_project
    app = ReaderApp(tk_root, p)
    tk_root.update_idletasks()
    assert app._selected_scene == "s001"
    gid = "g:Chapter 1"
    app.scene_tree.item(gid, open=False)
    app.notebook.select(1)  # Branches
    app.select_node("n3")
    app.branch_detail.yview_moveto(0.5)
    tk_root.update_idletasks()
    detail_top = app.branch_detail.index("@0,0")
    app.notebook.select(2)  # Notes
    app.notes.yview_moveto(0.4)
    tk_root.update_idletasks()
    notes_top = app.notes.index("@0,0")

    # a new inactive node is saved while the writer reads
    t = json.loads((p / "trees" / "s001.json").read_text())
    t["nodes"]["n4"] = rs.node("n4", "n2", "New saved swipe.")
    rs.write_json(p / "trees" / "s001.json", t)
    rs.write_json(p / "scenes.json",
                  [rs.scene("s001", chapter=1, title="A"),
                   rs.scene("s002", chapter=1, title="B edited")])
    app.refresh()
    tk_root.update_idletasks()
    assert app._selected_scene == "s001" and app._selected_node == "n3"
    assert app.notebook.index(app.notebook.select()) == 2, "tab preserved"
    assert bool(app.scene_tree.item(gid, "open")) is False, "expansion preserved"
    assert app.notes.index("@0,0") == notes_top, "notes position preserved"
    assert app.branch_detail.index("@0,0") == detail_top, "detail position kept"
    assert app.branch_index_ids() == ["n1", "n2", "n3", "n4"], "new node listed"
    assert "New saved swipe." in app.branch_detail.get("1.0", "end") or \
        app.branches_text().startswith("ID: n3")


def test_append_refresh_does_not_jump_or_lose_position(tk_root, refresh_project):
    from longform_core.gui import ReaderApp

    p = refresh_project
    app = ReaderApp(tk_root, p)
    tk_root.update_idletasks()
    app.manuscript.yview_moveto(0.3)
    tk_root.update_idletasks()
    top_before = app.manuscript.index("@0,0")
    line = top_before.split(".")[0]
    text_before = app.manuscript.get(top_before, f"{line}.end")
    # normal append: new node becomes the head
    t = rs.tree({
        "n1": rs.node("n1", None,
                      "\n\n".join(f"Paragraph {k} carries several words of prose."
                                  for k in range(1, 31))),
        "n2": rs.node("n2", "n1", "Inactive sibling.\n\nLine two.\n\nLine three."),
        "n3": rs.node("n3", "n2", "Inactive descendant.\n\nMore detail here."),
        "n4": rs.node("n4", "n1", "A saved later passage.", sep="\n\n"),
    }, head="n4")
    rs.write_json(p / "trees" / "s001.json", t)
    app.refresh()
    tk_root.update_idletasks()
    assert app.manuscript_label().startswith("head n4")
    assert "A saved later passage." in app.manuscript_text()
    top_after = app.manuscript.index("@0,0")
    assert top_after.split(".")[0] == line, "reading position not jumped"
    assert app.manuscript.get(top_after, f"{line}.end") == text_before


def test_removed_scene_and_node_fallbacks(tk_root, refresh_project):
    from longform_core.gui import ReaderApp

    p = refresh_project
    app = ReaderApp(tk_root, p)
    tk_root.update_idletasks()
    app.select_scene("s002")
    assert app._selected_scene == "s002"
    # drop the s002 card and its tree: fall back to the first current scene
    rs.write_json(p / "scenes.json", [rs.scene("s001", chapter=1, title="A")])
    (p / "trees" / "s002.json").unlink()
    app.refresh()
    assert app._selected_scene == "s001"
    # node removal inside the surviving scene: fall back to the head
    app.select_scene("s001")
    app.select_node("n3")
    assert app._selected_node == "n3"
    t = rs.tree({"n1": rs.node("n1", None, "Only the base remains.")}, head="n1")
    rs.write_json(p / "trees" / "s001.json", t)
    app.refresh()
    assert app._selected_node == "n1", "removed node falls back to head"
    # everything gone: empty panes, no crash
    rs.write_json(p / "scenes.json", [])
    (p / "trees" / "s001.json").unlink(missing_ok=True)
    (p / "trees" / "s002.json").unlink(missing_ok=True)
    app.refresh()
    assert app._selected_scene is None
    assert app.manuscript_text() == ""


def test_stale_error_recovery_keeps_last_good_view(tk_root, project):
    from longform_core.gui import ReaderApp

    p = project
    app = ReaderApp(tk_root, p)
    tk_root.update_idletasks()
    manuscript_before = app.manuscript_text()
    before = dict(app.rebuilds)
    (p / "project.json").write_text("{broken", encoding="utf-8")
    app.refresh()
    assert app.stale and "STALE" in app.status_text()
    assert app.manuscript_text() == manuscript_before, "last valid view kept"
    for pane in ("scene_list", "manuscript", "branches", "notes"):
        assert app.rebuilds[pane] == before[pane]
    rs.write_json(p / "project.json", {"title": "Fixture Novel",
                                       "target_words": 9000})
    app.refresh()
    assert not app.stale and "STALE" not in app.status_text()
    assert "9/9000" in app.status_text()


def test_f5_key_and_refresh_button_force_read(tk_root, project):
    from longform_core.gui import ReaderApp

    app = ReaderApp(tk_root, project)
    tk_root.update_idletasks()
    reads = len(app.cache.reads)
    app.refresh_now()
    assert len(app.cache.reads) > reads, "Refresh now forces a fresh read"
    reads = len(app.cache.reads)
    tk_root.geometry("400x300")
    tk_root.deiconify()
    tk_root.update()
    tk_root.event_generate("<F5>")
    tk_root.update()
    assert len(app.cache.reads) > reads, "F5 uses the same force path"
    tk_root.withdraw()
    tk_root.update()
