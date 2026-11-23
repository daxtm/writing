"""Desktop reader widget tests: withdrawn Tk root, synthetic temp projects.

Availability probing: only ImportError / Tk display-library initialization
failure may skip; every failure after a successful probe is a real failure.
"""

import pytest

import reader_support


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
