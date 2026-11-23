"""Native read-only Tkinter/ttk desktop reader.

`ReaderApp` builds one withdrawn-capable root's UI and reads only through
`reader_model` sanitized snapshots. It never writes project files, never
starts servers/browsers, and never touches provider APIs.
"""

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from . import reader_model as model

REFRESH_MS = 2000
MIN_SIZE = (900, 600)
INIT_SIZE = "1200x800"
PROSE_SIZE = 13

GROUP = "g:"
SCENE = "s:"

MANUSCRIPT_TAB = "Manuscript"
BRANCHES_TAB = "Branches"
NOTES_TAB = "Notes"


class ReaderApp:
    """Read-only desktop reader for one project directory."""

    def __init__(self, root, project_dir):
        self.root = root
        self.project_dir = project_dir
        self.cache = model.SourceCache()
        self.snapshot = None
        self.stale = False
        self._selected_scene = None
        self._selected_node = None
        self._after_id = None
        # rebuild spies for tests: unchanged panes must not be rebuilt
        self.rebuilds = {"scene_list": 0, "manuscript": 0, "branches": 0,
                         "notes": 0, "status": 0}
        base = tkfont.nametofont("TkTextFont")
        self.prose_font = tkfont.Font(root=root, family=base.actual("family"),
                                      size=PROSE_SIZE)
        self._build()
        self.refresh()

    # ------------------------------------------------------------ construction

    def _build(self):
        self.root.title("Longform Reader (read-only)")
        self.root.geometry(INIT_SIZE)
        self.root.minsize(*MIN_SIZE)

        bar = ttk.Frame(self.root, padding=(8, 6))
        bar.pack(side="top", fill="x")
        ttk.Button(bar, text="Refresh now", command=self.refresh_now).pack(side="left")
        self.auto_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Auto-refresh", variable=self.auto_var,
                        command=self._toggle_auto).pack(side="left", padx=(12, 0))
        self.last_check_var = tk.StringVar(value="last check: —")
        ttk.Label(bar, textvariable=self.last_check_var).pack(side="left", padx=(16, 0))

        self.status_var = tk.StringVar(value="")
        status = ttk.Label(self.root, textvariable=self.status_var,
                           padding=(8, 4), relief="sunken")
        status.pack(side="bottom", fill="x")

        self.pane = ttk.PanedWindow(self.root, orient="horizontal")
        self.pane.pack(fill="both", expand=True)

        left = ttk.Frame(self.pane)
        self.pane.add(left, weight=1)
        self.scene_tree = ttk.Treeview(
            left, columns=("title", "status", "words"),
            selectmode="browse", show="tree headings")
        self.scene_tree.heading("#0", text="ID")
        self.scene_tree.heading("title", text="Title")
        self.scene_tree.heading("status", text="Status")
        self.scene_tree.heading("words", text="Words")
        self.scene_tree.column("#0", width=140, stretch=False)
        ysb = ttk.Scrollbar(left, orient="vertical", command=self.scene_tree.yview)
        self.scene_tree.configure(yscrollcommand=ysb.set)
        self.scene_tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.scene_tree.bind("<<TreeviewSelect>>", self._on_scene_select)
        self.scene_scroll = ysb

        right = ttk.Frame(self.pane)
        self.pane.add(right, weight=3)
        self.notebook = ttk.Notebook(right)
        self.notebook.pack(fill="both", expand=True)

        man = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(man, text=MANUSCRIPT_TAB)
        self.manuscript_label_var = tk.StringVar(value="")
        ttk.Label(man, textvariable=self.manuscript_label_var).pack(anchor="w")
        man_body = ttk.Frame(man)
        man_body.pack(fill="both", expand=True)
        self.manuscript = self._make_text(man_body)
        self.manuscript_scroll = self._text_scrollbar(man_body, self.manuscript)

        br = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(br, text=BRANCHES_TAB)
        self.branches_placeholder = ttk.Label(
            br, text="(branch index appears when a scene is selected)")
        self.branches_placeholder.pack(fill="both", expand=True)

        notes = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(notes, text=NOTES_TAB)
        notes_body = ttk.Frame(notes)
        notes_body.pack(fill="both", expand=True)
        self.notes = self._make_text(notes_body)
        self._text_scrollbar(notes_body, self.notes)

        self.root.bind("<F5>", lambda _e: self.refresh_now())
        self.root.bind("<Control-q>", lambda _e: self.close())
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _make_text(self, parent):
        text = tk.Text(parent, wrap="word", font=self.prose_font,
                       state="disabled", padx=10, pady=8, spacing3=3)
        text.pack(side="left", fill="both", expand=True)
        return text

    def _text_scrollbar(self, parent, text):
        sb = ttk.Scrollbar(parent, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        return sb

    def _set_text(self, widget, content):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    # ---------------------------------------------------------------- refresh
    def refresh(self, force=False):
        result = model.load_snapshot(self.project_dir, cache=self.cache, force=force)
        if result.snapshot is None:
            self.stale = True
            self._set_status(warnings=result.warnings)
            self.last_check_var.set("last check: failed")
        else:
            self.stale = False
            self._apply(result.snapshot)
            self.last_check_var.set("last check: just now")
        self._reschedule()

    def refresh_now(self):
        """Manual refresh always forces a fresh disk read."""
        self.refresh(force=True)

    def _apply(self, snap):
        self.snapshot = snap
        self.root.title(f"{snap.project.title} — Longform Reader (read-only)")
        self._populate_scene_list()
        self._ensure_selection()
        self._populate_manuscript()
        self._populate_branches()
        self._populate_notes()
        self._set_status()

    # ------------------------------------------------------------ scene list

    def _populate_scene_list(self):
        self.rebuilds["scene_list"] += 1
        tree = self.scene_tree
        tree.delete(*tree.get_children())
        self._scene_by_iid = {}
        self._iid_by_scene = {}
        snap = self.snapshot
        if snap is None:
            return
        groups = []
        for row in snap.scenes:
            if row.group not in groups:
                groups.append(row.group)
            iid = SCENE + row.id
            self._scene_by_iid[iid] = row.id
            self._iid_by_scene[row.id] = iid
        for group in groups:
            gid = GROUP + group
            tree.insert("", "end", iid=gid, text=group, open=True,
                        values=("", "", ""))
        retained = sorted(sid for sid in snap.trees
                          if sid not in {r.id for r in snap.scenes})
        if retained:
            gid = GROUP + "Retained trees"
            tree.insert("", "end", iid=gid, text="Retained trees", open=True,
                        values=("", "", ""))
            groups.append("Retained trees")
        for row in snap.scenes:
            view = snap.trees.get(row.id)
            words = view.active_words if view else 0
            words = "" if words is None else words
            tree.insert(GROUP + row.group, "end", iid=self._iid_by_scene[row.id],
                        text=row.id, values=(row.title, row.status, words))
        for sid in retained:
            view = snap.trees[sid]
            words = "" if view.active_words is None else view.active_words
            iid = SCENE + sid
            self._scene_by_iid[iid] = sid
            self._iid_by_scene[sid] = iid
            tree.insert(GROUP + "Retained trees", "end", iid=iid, text=sid,
                        values=("(retained)", "retained", words))

    def scene_rows(self):
        """(id, title, status, active words) for every listed scene row."""
        out = []
        for iid in self._scene_by_iid:
            vals = self.scene_tree.item(iid, "values")
            try:
                words = int(vals[2]) if vals[2] != "" else None
            except ValueError:
                words = vals[2]
            out.append((self._scene_by_iid[iid], vals[0], vals[1], words))
        return out

    def _on_scene_select(self, _event=None):
        sel = self.scene_tree.selection()
        if not sel or sel[0].startswith(GROUP):
            return
        self.select_scene(self._scene_by_iid[sel[0]])

    def select_scene(self, sid):
        if sid == self._selected_scene:
            return
        self._selected_scene = sid
        self._selected_node = None
        self._populate_manuscript()
        self._populate_branches()

    # ------------------------------------------------------------ manuscript

    def _scene_view(self):
        snap = self.snapshot
        if snap is None or self._selected_scene is None:
            return None
        return snap.trees.get(self._selected_scene)

    def _populate_manuscript(self):
        view = self._scene_view()
        if view is None:
            self.manuscript_label_var.set("no scene selected")
            self._set_text(self.manuscript, "")
            return
        text = view.active_text if view.active_text is not None else ""
        self.rebuilds["manuscript"] += 1
        head = view.head if view.head else "(none)"
        w = view.active_words if view.active_words is not None else 0
        self.manuscript_label_var.set(f"head {head} · {w} words")
        if not text:
            text = "(no saved text yet)"
        self._set_text(self.manuscript, text)

    def manuscript_text(self):
        return self.manuscript.get("1.0", "end-1c")

    def manuscript_label(self):
        return self.manuscript_label_var.get()

    # ------------------------------------------------------------ branches/notes

    def _populate_branches(self):
        pass

    def branches_text(self):
        return ""

    def select_node(self, nid):
        pass

    def _populate_notes(self):
        self.rebuilds["notes"] += 1
        self._set_text(self.notes, "")

    def notes_text(self):
        return self.notes.get("1.0", "end-1c")

    # ------------------------------------------------------------ selection

    def _ensure_selection(self):
        snap = self.snapshot
        if snap is None:
            self._selected_scene = None
            return
        current = [r.id for r in snap.scenes]
        if self._selected_scene in current or self._selected_scene in snap.trees:
            self._sync_scene_tree_selection()
            return
        self._selected_scene = current[0] if current else \
            (sorted(snap.trees)[0] if snap.trees else None)
        self._selected_node = None
        self._sync_scene_tree_selection()

    def _sync_scene_tree_selection(self):
        iid = self._iid_by_scene.get(self._selected_scene)
        if iid and iid not in self.scene_tree.selection():
            self.scene_tree.selection_set(iid)
            self.scene_tree.see(iid)

    # ------------------------------------------------------------ status

    def _set_status(self, warnings=None):
        self.rebuilds["status"] += 1
        snap = self.snapshot
        if snap is None:
            self.status_var.set("project data unavailable")
            return
        count = len(snap.scenes)
        noun = "scene" if count == 1 else "scenes"
        total = f"{snap.actual_words}/{snap.project.target_words} words"
        if not snap.words_complete:
            total += " (partial)"
        parts = [f"{count} {noun}", total]
        problems = warnings if warnings is not None else snap.warnings
        if self.stale:
            parts.append("STALE — keeping last good view")
        elif problems:
            parts.append(f"warnings: {len(problems)}")
        self.status_var.set(" · ".join(parts))

    def status_text(self):
        return self.status_var.get()

    # ------------------------------------------------------------ timer

    def _on_timer(self):
        self._after_id = None
        if self.auto_var.get():
            self.refresh()

    def _reschedule(self):
        self._cancel_timer()
        if self.auto_var.get():
            self._after_id = self.root.after(REFRESH_MS, self._on_timer)

    def _cancel_timer(self):
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _toggle_auto(self):
        if self.auto_var.get():
            self._reschedule()
        else:
            self._cancel_timer()

    # ------------------------------------------------------------ lifecycle

    def close(self):
        self._cancel_timer()
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def launch(project_dir):
    """CLI entry: build one root/app and block until the window closes."""
    import sys

    result = model.load_snapshot(project_dir)
    if result.snapshot is None:
        print("gui: not a readable longform project (missing or invalid "
              "project.json): " + str(project_dir), file=sys.stderr)
        sys.exit(2)
    try:
        import tkinter as tk
    except ImportError:
        print("gui: this Python has no Tk runtime; use the project's uv runtime: "
              "uv run --script longform.py gui DIR (and check a desktop display "
              "is available)", file=sys.stderr)
        sys.exit(2)
    try:
        root = tk.Tk()
    except tk.TclError as e:
        print("gui: could not open a desktop display (" + str(e) + "); run on a "
              "machine with a display: uv run --script longform.py gui DIR",
              file=sys.stderr)
        sys.exit(2)
    root.withdraw()
    ReaderApp(root, project_dir)
    root.deiconify()
    root.mainloop()
