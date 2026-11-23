"""Native read-only Tkinter/ttk desktop reader.

`ReaderApp` builds one withdrawn-capable root's UI and reads only through
`reader_model` sanitized snapshots. It never writes project files, never
starts servers/browsers, and never touches provider APIs.

The tkinter import is guarded so importing this module never crashes a
Tk-less interpreter; `launch()` converts that into a concise error.
"""

try:
    import tkinter as tk
    from tkinter import font as tkfont
    from tkinter import ttk
except ImportError as _tk_error:  # missing Tk runtime; launch() reports it
    tk = None
    _TK_IMPORT_ERROR = _tk_error

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

    BRANCH_GROUPS = ("Active path", "Saved branches", "Unlinked/invalid links")

    def __init__(self, root, project_dir):
        self.root = root
        self.project_dir = project_dir
        self.cache = model.SourceCache()
        self.snapshot = None
        self.stale = False
        self._selected_scene = None
        self._selected_node = None
        self._after_id = None
        self._after_cancels = []
        self._content = {}  # per-pane signatures of what is currently shown
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
        self.branches_pane = ttk.PanedWindow(br, orient="vertical")
        self.branches_pane.pack(fill="both", expand=True)
        index_frame = ttk.Frame(self.branches_pane)
        self.branches_pane.add(index_frame, weight=2)
        self.branch_tree = ttk.Treeview(
            index_frame, columns=("parent", "words", "source", "created", "marker"),
            selectmode="browse", show="tree headings")
        self.branch_tree.heading("#0", text="Node")
        self.branch_tree.heading("parent", text="Parent")
        self.branch_tree.heading("words", text="Words")
        self.branch_tree.heading("source", text="Source")
        self.branch_tree.heading("created", text="Created")
        self.branch_tree.heading("marker", text="Marker")
        self.branch_tree.column("#0", width=170, stretch=False)
        self.branch_tree.column("parent", width=90, stretch=False)
        self.branch_tree.column("words", width=70, stretch=False)
        self.branch_tree.column("created", width=170, stretch=False)
        bsb = ttk.Scrollbar(index_frame, orient="vertical",
                            command=self.branch_tree.yview)
        self.branch_tree.configure(yscrollcommand=bsb.set)
        self.branch_tree.pack(side="left", fill="both", expand=True)
        bsb.pack(side="right", fill="y")
        self.branch_tree.bind("<<TreeviewSelect>>", self._on_node_select)
        self.branch_scroll = bsb
        detail_frame = ttk.Frame(self.branches_pane)
        self.branches_pane.add(detail_frame, weight=3)
        self.branch_detail = self._make_text(detail_frame)
        self._text_scrollbar(detail_frame, self.branch_detail)

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
            # keep the whole last valid snapshot visible and mark it stale
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

    def _apply(self, snap, preserve=True):
        state = self._capture_state() if preserve and self.snapshot is not None \
            else None
        old_scene = state["scene"] if state else self._selected_scene
        old_node = state["node"] if state else self._selected_node
        old_content = self._content
        self.snapshot = snap
        self.root.title(f"{snap.project.title} — Longform Reader (read-only)")

        scene, node = self._resolve_selection(old_scene, old_node)
        self._selected_scene, self._selected_node = scene, node

        rows = self._scene_list_rows(snap)
        if rows != old_content.get("scene_list"):
            self.rebuilds["scene_list"] += 1
            self._populate_scene_list(rows)
        self._content["scene_list"] = rows
        self._sync_scene_tree_selection()

        view = snap.trees.get(scene) if scene else None
        head, words, m_text, label = self._manuscript_parts(view)
        m_sig = (scene, head, words, m_text)
        if m_sig != old_content.get("manuscript"):
            self.rebuilds["manuscript"] += 1
            self.manuscript_label_var.set(label)
            self._set_text(self.manuscript, m_text)
        self._content["manuscript"] = m_sig

        branch_rows, detail = self._branch_parts(snap, scene, node)
        b_sig = (scene, node, branch_rows, detail)
        if b_sig != old_content.get("branches"):
            self.rebuilds["branches"] += 1
            self._populate_branches(branch_rows)
            self._set_text(self.branch_detail, detail)
        else:
            self._sync_branch_tree_selection()
        self._content["branches"] = b_sig

        notes_text = self._notes_text(snap)
        if notes_text != old_content.get("notes"):
            self.rebuilds["notes"] += 1
            self._set_text(self.notes, notes_text)
        self._content["notes"] = notes_text

        self._set_status()
        self._restore_state(state)

    # ------------------------------------------------------------ scene list

    def _scene_list_rows(self, snap):
        """(group, id, title, status, words) in display order."""
        rows = []
        for r in snap.scenes:
            view = snap.trees.get(r.id)
            w = view.active_words if view and view.active_words is not None else 0
            rows.append((r.group, r.id, r.title, r.status, w))
        for sid in sorted(t for t in snap.trees if t not in
                          {r.id for r in snap.scenes}):
            view = snap.trees[sid]
            w = view.active_words if view.active_words is not None else None
            rows.append(("Retained trees", sid, "(retained)", "retained", w))
        return rows

    def _populate_scene_list(self, rows):
        tree = self.scene_tree
        tree.delete(*tree.get_children())
        self._scene_by_iid = {}
        self._iid_by_scene = {}
        groups = []
        for row in rows:
            if row[0] not in groups:
                groups.append(row[0])
        for group in groups:
            tree.insert("", "end", iid=GROUP + group, text=group, open=True,
                        values=("", "", ""))
        for group, sid, title, status, w in rows:
            iid = SCENE + sid
            self._scene_by_iid[iid] = sid
            self._iid_by_scene[sid] = iid
            tree.insert(GROUP + group, "end", iid=iid, text=sid,
                        values=(title, status, "" if w is None else w))

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
        self._selected_node = None  # a scene switch resets its node
        self._apply(self.snapshot)

    # ------------------------------------------------------------ manuscript

    def _manuscript_parts(self, view):
        if view is None:
            return None, None, "", "no scene selected"
        text = view.active_text if view.active_text is not None else ""
        head = view.head if view.head else "(none)"
        w = view.active_words if view.active_words is not None else 0
        label = f"head {head} · {w} words"
        shown = text if text else "(no saved text yet)"
        return view.head, w, shown, label

    def manuscript_text(self):
        return self.manuscript.get("1.0", "end-1c")

    def manuscript_label(self):
        return self.manuscript_label_var.get()

    # ------------------------------------------------------------ branches

    def _branch_rows(self, snap, sid):
        """[(kind, group, nid, parent_nid, values)] in insertion order."""
        view = snap.trees.get(sid) if sid else None
        if view is None:
            return []
        rows = []
        for group in self.BRANCH_GROUPS:
            nids = []
            for nid in view.order:
                info = view.nodes.get(nid)
                if info is None:
                    continue
                if group == "Active path" and info.on_active_path:
                    nids.append(nid)
                elif group == "Saved branches" and info.link_ok \
                        and not info.on_active_path:
                    nids.append(nid)
                elif group == "Unlinked/invalid links" and not info.link_ok:
                    nids.append(nid)
            if not nids:
                continue
            rows.append(("group", group, None, None, ()))
            nids_set = set(nids)
            placed = set()
            roots = [n for n in nids if view.nodes[n].parent not in nids_set]
            stack = [nid for nid in reversed(roots)]
            while stack:
                nid = stack.pop()
                if nid in placed:
                    continue
                placed.add(nid)
                info = view.nodes[nid]
                marker = ("head" if nid == view.head else
                          "active" if info.on_active_path else "")
                parent_nid = info.parent if info.parent in nids_set else None
                rows.append(("node", group, nid, parent_nid,
                             (info.parent or "(start)", info.word_count,
                              info.source or "(unavailable)",
                              info.created or "(unavailable)", marker)))
                stack.extend(k for k in reversed(info.children)
                             if k in nids_set)
        return rows

    def _branch_detail_lines(self, view, nid):
        if view is None or nid is None or nid not in view.nodes:
            return ["(no node selected)"]
        info = view.nodes[nid]
        lines = [f"ID: {nid}",
                 f"parent: {info.parent if info.parent is not None else '(scene start)'}",
                 "children: " + (", ".join(info.children) if info.children else "(none)"),
                 f"source: {info.source if info.source is not None else '(unavailable)'}",
                 f"model: {info.model if info.model is not None else '(unavailable)'}",
                 f"created: {info.created if info.created is not None else '(unavailable)'}",
                 f"steer: {info.steer if info.steer is not None else '(unavailable)'}",
                 f"ended: {info.ended if info.ended is not None else '(unavailable)'}",
                 f"trimmed: {info.trimmed if info.trimmed is not None else '(unavailable)'}"]
        if info.history:
            lines.append("")
            lines.append("history:")
            for h in info.history:
                lines.append(f"[{h['time']} by {h['by']}]")
                lines.append(h["text"])
        lines.append("")
        lines.append("text:")
        lines.append(info.text)
        return lines

    def _branch_parts(self, snap, sid, nid):
        view = snap.trees.get(sid) if sid else None
        rows = self._branch_rows(snap, sid)
        detail = "\n".join(self._branch_detail_lines(view, nid))
        return tuple(rows), detail

    def _populate_branches(self, rows):
        tree = self.branch_tree
        tree.delete(*tree.get_children())
        self._node_by_iid = {}
        self._iid_by_node = {}
        sid = self._selected_scene
        for kind, group, nid, parent_nid, values in rows:
            if kind == "group":
                tree.insert("", "end", iid=f"b:{sid}:{group}", text=group,
                            open=True, values=("", "", "", "", ""))
                continue
            parent_iid = (self._iid_by_node.get(parent_nid)
                          if parent_nid else f"b:{sid}:{group}")
            iid = f"n:{sid}:{nid}"
            self._node_by_iid[iid] = nid
            self._iid_by_node[nid] = iid
            tree.insert(parent_iid, "end", iid=iid, text=nid, values=values)

    def branch_index_ids(self):
        """Every node ID listed in the Branches index for the selected scene."""
        return sorted(self._iid_by_node)

    def _on_node_select(self, _event=None):
        sel = self.branch_tree.selection()
        if not sel or not sel[0].startswith("n:"):
            return
        self.select_node(self._node_by_iid[sel[0]])

    def select_node(self, nid):
        view = self._scene_view()
        if view is None or nid not in view.nodes:
            return
        if nid == self._selected_node:
            return
        self._selected_node = nid
        self._apply(self.snapshot)

    def _sync_branch_tree_selection(self):
        view = self._scene_view()
        if view is None or self._selected_node not in view.nodes:
            return
        iid = f"n:{self._selected_scene}:{self._selected_node}"
        if self.branch_tree.exists(iid) and iid not in self.branch_tree.selection():
            self.branch_tree.selection_set(iid)

    def branches_text(self):
        return self.branch_detail.get("1.0", "end-1c")

    def _scene_view(self):
        snap = self.snapshot
        if snap is None or self._selected_scene is None:
            return None
        return snap.trees.get(self._selected_scene)

    # ------------------------------------------------------------ notes

    def _notes_text(self, snap):
        notes = snap.notes
        out = []
        out.append("== bible.md ==")
        out.append(notes.bible if notes.bible is not None else "(absent)")
        out.append("")
        out.append("== state.md ==")
        out.append(notes.state if notes.state is not None else "(absent)")
        out.append("")
        out.append("== Scene summaries ==")
        if notes.summaries and notes.summaries.scenes:
            for sid in sorted(notes.summaries.scenes):
                e = notes.summaries.scenes[sid]
                out.append(f"-- {sid}" +
                           (f" (updated {e.updated})" if e.updated else ""))
                out.append(f"detailed: "
                           f"{e.detailed if e.detailed is not None else '(unavailable)'}")
                out.append(f"brief: {e.brief if e.brief is not None else '(unavailable)'}")
        else:
            out.append("(no scene summaries)")
        out.append("")
        out.append("== Arc summaries ==")
        if notes.summaries and notes.summaries.arcs:
            for a in notes.summaries.arcs:
                out.append(f"-- {a.from_id}–{a.to_id}" +
                           (f" (updated {a.updated})" if a.updated else ""))
                out.append(a.text)
        else:
            out.append("(no arc summaries)")
        for label, files in (("checks/", notes.checks), ("critiques/", notes.critiques)):
            out.append("")
            out.append(f"== {label} ==")
            if files:
                for f in files:
                    out.append(f"-- {f.name}")
                    out.append(f.text)
            else:
                out.append("(no reports)")
        return "\n".join(out)

    def notes_text(self):
        return self.notes.get("1.0", "end-1c")

    # ------------------------------------------------------------ selection

    def _resolve_selection(self, old_scene, old_node):
        """Keep surviving selections; otherwise fall back head-first."""
        snap = self.snapshot
        current = [r.id for r in snap.scenes]
        if old_scene in current or old_scene in snap.trees:
            scene = old_scene
        elif current:
            scene = current[0]
        elif snap.trees:
            scene = sorted(snap.trees)[0]
        else:
            scene = None
        node = None
        if scene is not None:
            view = snap.trees.get(scene)
            if view is not None:
                if scene == old_scene and old_node in view.nodes:
                    node = old_node
                elif view.head in view.nodes:
                    node = view.head
                elif view.order:
                    node = view.order[0]
        return scene, node

    def _ensure_selection(self):
        scene, node = self._resolve_selection(self._selected_scene,
                                              self._selected_node)
        self._selected_scene, self._selected_node = scene, node

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

    # ---------------------------------------------------- state preservation

    def _capture_state(self):
        return {
            "scene": self._selected_scene,
            "node": self._selected_node,
            "tab": self.notebook.index(self.notebook.select())
            if self.notebook.tabs() else 0,
            "scene_open": {iid: self.scene_tree.item(iid, "open")
                           for iid in self.scene_tree.get_children("")
                           if iid.startswith(GROUP)},
            "branch_open": {iid: self.branch_tree.item(iid, "open")
                            for iid in self.branch_tree.get_children("")
                            if iid.startswith("b:")},
            "scene_yview": self.scene_tree.yview()[0],
            "branch_yview": self.branch_tree.yview()[0],
            "tops": {"manuscript": self.manuscript.index("@0,0"),
                     "detail": self.branch_detail.index("@0,0"),
                     "notes": self.notes.index("@0,0")},
        }

    def _restore_state(self, state):
        if state is None:
            return
        tabs = self.notebook.tabs()
        if tabs:
            idx = min(state["tab"], len(tabs) - 1)
            try:
                if self.notebook.index(self.notebook.select()) != idx:
                    self.notebook.select(idx)
            except tk.TclError:
                pass
        for iid, was_open in state["scene_open"].items():
            if self.scene_tree.exists(iid) and \
                    bool(self.scene_tree.item(iid, "open")) != bool(was_open):
                self.scene_tree.item(iid, open=was_open)
        for iid, was_open in state["branch_open"].items():
            if self.branch_tree.exists(iid) and \
                    bool(self.branch_tree.item(iid, "open")) != bool(was_open):
                self.branch_tree.item(iid, open=was_open)
        self.scene_tree.yview_moveto(state["scene_yview"])
        self.branch_tree.yview_moveto(state["branch_yview"])
        self._restore_text_top(self.manuscript, state["tops"]["manuscript"])
        self._restore_text_top(self.branch_detail, state["tops"]["detail"])
        self._restore_text_top(self.notes, state["tops"]["notes"])

    def _restore_text_top(self, widget, index):
        """Put the captured first-visible index back at the top, clamped."""
        if not index or not widget.get("1.0", "end-1c"):
            return
        target = index
        if widget.compare("end-1c", "<=", target):
            widget.yview_moveto(1.0)
            return
        widget.mark_set("reader_top", target)
        widget.see("reader_top")
        for _ in range(10000):
            top = widget.index("@0,0")
            if widget.compare(top, ">=", target):
                break
            widget.yview_scroll(1, "displaylines")
        while True:
            top = widget.index("@0,0")
            if widget.compare(top, "<=", target) or top == "1.0":
                break
            widget.yview_scroll(-1, "displaylines")

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
            self._after_cancels.append(self._after_id)
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
    if tk is None:
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
