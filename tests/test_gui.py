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
