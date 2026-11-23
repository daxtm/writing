"""PySide6 Qt Widgets shell: reading all saved branches and per-scene steering.

Presentation only (ADR-0006): no provider calls, no manuscript acceptance, no
background worker — ADR-0007 keeps those for the gui-steered-drafting change.
Widgets consume sanitized reader_model snapshots; steering writes go through
the Qt-independent scene_steering adapter only.
"""

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QSplitter,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import reader_model as rm
from . import scene_steering as ss

PRE_START_GUIDANCE = (
    "longform gui: native Wayland is required. If startup fails, check your "
    "Wayland desktop session/socket and the Qt Wayland/system libraries, then "
    "retry: QT_QPA_PLATFORM=wayland uv run --script longform.py gui DIR")

REFRESH_MS = 2000

# Tabs
MANUSCRIPT, BRANCHES, NOTES = 0, 1, 2
# Sidebar item kinds
KIND_MANUSCRIPT = "manuscript"
KIND_NODE = "node"
KIND_RETAINED = "retained"
KIND_RETAINED_NODE = "retained-node"
_ROLE = Qt.ItemDataRole.UserRole


def run(dir_path):
    """Create, show, and run one project window; blocks until it closes."""
    # Flushed before QApplication construction: a platform-plugin abort below
    # ordinary Python error handling still leaves recovery advice on stderr.
    print(PRE_START_GUIDANCE, file=sys.stderr, flush=True)
    app = QApplication(sys.argv or ["longform gui"])
    from PySide6.QtCore import qVersion
    import PySide6
    print(f"longform gui: Qt platform '{app.platformName()}', "
          f"PySide6 {PySide6.__version__}, Qt {qVersion()}", flush=True)
    if app.platformName() != "wayland":
        print(f"gui: Qt initialized platform '{app.platformName()}' instead of "
              f"'wayland'; native Wayland is required (no fallback window). "
              "Check the Wayland session/socket and Qt Wayland libraries, "
              "then retry: QT_QPA_PLATFORM=wayland uv run --script longform.py "
              "gui DIR", file=sys.stderr, flush=True)
        return 1
    window = MainWindow(dir_path)
    window.show()
    return app.exec()


def _ask_choice(title, text, options):
    """Default chooser over QMessageBox; returns the option label or None."""
    box = QMessageBox()
    box.setWindowTitle(title)
    box.setText(text)
    default = None
    for i, opt in enumerate(options):
        b = box.addButton(opt, QMessageBox.ButtonRole.ActionRole)
        if i == 0:
            default = b
    box.setDefaultButton(default)
    box.exec()
    clicked = box.clickedButton()
    if clicked is None:
        return None
    label = clicked.text()
    return label if label in options else options[-1]


class MainWindow(QMainWindow):
    """One window: sidebar navigation, read-only panes, per-scene steering."""

    def __init__(self, dir_path, *, load=None, timer_factory=None, choice=None):
        super().__init__()
        self._root = Path(dir_path)
        self._load = load or rm.load_snapshot
        self._cache = rm.SourceCache()
        self._choice = choice or _ask_choice
        self._timer_factory = timer_factory

        self.snap = None              # last valid Snapshot
        self._stale_config = False    # required configuration currently invalid
        self._sel_data = None         # (kind, tree_id, node_id) of selection
        self._missing_node = None     # selected node removed from the project
        self._scene_sel = None        # scene id the steering editor is bound to
        self._steer = None            # scene_steering.SteeringState
        self._notes_entries = []      # [(key, label, text)]
        self._notes_key = None

        self.setWindowTitle("longform — reading and steering")
        self.resize(1150, 760)
        self._build_ui()
        self._wire_tab_order()
        self.refresh(force=True)
        self._autoselect()
        self._start_timer()

    # ------------------------------------------------------------------ UI

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(6)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setToolTip("Re-read saved sources; keeps selection, "
                                    "scroll, and unsaved steering")
        self.refresh_btn.clicked.connect(lambda: self.refresh(force=True))
        top.addWidget(self.refresh_btn)
        top.addWidget(QLabel("Prose size"))
        self.prose_size = QSpinBox()
        self.prose_size.setRange(8, 28)
        self.prose_size.setValue(11)
        self.prose_size.setSuffix(" pt")
        self.prose_size.valueChanged.connect(self._apply_prose_size)
        top.addWidget(self.prose_size)
        top.addStretch(1)
        root.addLayout(top)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.sidebar = QTreeWidget()
        self.sidebar.setHeaderLabel("Scenes / branches")
        self.sidebar.setMinimumWidth(220)
        self.sidebar.itemSelectionChanged.connect(self._on_selection_changed)
        split.addWidget(self.sidebar)

        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.reading = QPlainTextEdit()
        self.reading.setReadOnly(True)
        self.metadata = QPlainTextEdit()
        self.metadata.setReadOnly(True)
        self.tabs.addTab(self.reading, "Manuscript")
        self.tabs.addTab(self.metadata, "Branches")
        self.tabs.addTab(self._build_notes_tab(), "Notes")
        right_l.addWidget(self.tabs, 1)

        steer_box = QGroupBox("Steering")
        steer_l = QVBoxLayout(steer_box)
        self.steer_label = QLabel("Steering")
        steer_l.addWidget(self.steer_label)
        self.steer_editor = QPlainTextEdit()
        self.steer_editor.setPlaceholderText(
            "Direction for this scene — persists with the scene's draft tree "
            "(Enter inserts a newline)")
        self.steer_editor.textChanged.connect(self._steer_edited)
        steer_l.addWidget(self.steer_editor, 1)
        btns = QHBoxLayout()
        self.save_btn = QPushButton("Save steering")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self.save_steering)
        self.clear_btn = QPushButton("Clear saved")
        self.clear_btn.clicked.connect(self.clear_steering)
        self.generate_btn = QPushButton("Generate")
        self.generate_btn.setEnabled(False)
        self.generate_btn.setToolTip(
            "Drafting is not available yet: generation, preview, and acceptance "
            "come with the gui-steered-drafting change")
        self.generate_note = QLabel(
            "Generate is disabled: drafting is not available in this reading "
            "shell yet.")
        btns.addWidget(self.save_btn)
        btns.addWidget(self.clear_btn)
        btns.addStretch(1)
        btns.addWidget(self.generate_btn)
        steer_l.addLayout(btns)
        steer_l.addWidget(self.generate_note)
        right_l.addWidget(steer_box)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        root.addWidget(split, 1)

        self.status = QLabel("")
        self.statusBar().addWidget(self.status, 1)

    def _build_notes_tab(self):
        notes_split = QSplitter(Qt.Orientation.Horizontal)
        self.notes_list = QListWidget()
        self.notes_list.currentRowChanged.connect(self._on_note_selected)
        self.notes_view = QPlainTextEdit()
        self.notes_view.setReadOnly(True)
        notes_split.addWidget(self.notes_list)
        notes_split.addWidget(self.notes_view)
        notes_split.setStretchFactor(0, 1)
        notes_split.setStretchFactor(1, 2)
        return notes_split

    def _wire_tab_order(self):
        """Visible, predictable keyboard order: sidebar → reading → editor →
        actions → refresh/size."""
        w = QWidget.setTabOrder
        w(self.sidebar, self.tabs)
        w(self.tabs, self.reading)
        w(self.reading, self.metadata)
        w(self.metadata, self.notes_list)
        w(self.notes_list, self.notes_view)
        w(self.notes_view, self.steer_editor)
        w(self.steer_editor, self.save_btn)
        w(self.save_btn, self.clear_btn)
        w(self.clear_btn, self.generate_btn)
        w(self.generate_btn, self.refresh_btn)
        w(self.refresh_btn, self.prose_size)

    def _start_timer(self):
        timer = (self._timer_factory or (lambda: QTimer(self)))()
        self._timer = timer
        timer.timeout.connect(self._auto_refresh)
        timer.start(REFRESH_MS)

    def _autoselect(self):
        """Open on the first current scene that has saved text to read."""
        if self._sel_data is not None or self.snap is None:
            return
        for row in self.snap.scenes:
            item = self._find_item((KIND_MANUSCRIPT, row.id, None))
            if item is not None:
                self.sidebar.setCurrentItem(item)
                return

    def _auto_refresh(self):
        self.refresh(force=False)

    # ------------------------------------------------------------- helpers

    def _status(self, text, error=False):
        self.status.setText(("error: " + text) if error else text)

    def _apply_prose_size(self, size):
        for pane in (self.reading, self.metadata, self.notes_view,
                     self.steer_editor):
            font = QFont(pane.font())
            font.setPointSize(size)
            pane.setFont(font)

    def _card_ids(self):
        return {r.id for r in self.snap.scenes} if self.snap else set()

    def select_item(self, kind, tree_id, node_id=None):
        """Test/keyboard helper: select a sidebar item by its data triple."""
        item = self._find_item((kind, tree_id, node_id))
        if item is not None:
            self.sidebar.setCurrentItem(item)

    def _find_item(self, data):
        stack = [self.sidebar.invisibleRootItem()]
        while stack:
            it = stack.pop()
            for i in range(it.childCount()):
                child = it.child(i)
                if child.data(0, _ROLE) == data:
                    return child
                stack.append(child)
        return None

    def select_note(self, key):
        for i, (k, _label, _text) in enumerate(self._notes_entries):
            if k == key:
                self.notes_list.setCurrentRow(i)
                return

    def dirty(self):
        """True when the steering editor differs from its saved steering."""
        if self._steer is None or not self._steer.editable:
            return False
        return self.steer_editor.toPlainText() != (self._steer.text or "")

    # ----------------------------------------------------------- snapshots

    def refresh(self, force=False):
        """Reload the snapshot; preserve selection, tab, scroll, focus, dirty."""
        try:
            res = self._load(self._root, cache=self._cache, force=force)
        except OSError as e:
            self._stale_config = True
            self._update_steering_ui()
            self._status(f"sources could not be read; showing the last saved "
                         f"view (stale) ({type(e).__name__})", error=True)
            return
        if res.snapshot is None:
            self._stale_config = True
            self._update_steering_ui()
            self._status("project.json is missing or invalid; showing the last "
                         "saved view (stale). Fix it, then wait for refresh or "
                         "press Refresh: " + "; ".join(res.warnings), error=True)
            return
        if self._stale_config:
            self._stale_config = False
            self._status("Project configuration recovered; steering is "
                         "available again")
        self.snap = res.snapshot
        self._rebuild_sidebar()
        self._update_panes()
        if res.warnings:
            self._status("Warnings: " + "; ".join(res.warnings))

    def _rebuild_sidebar(self):
        self.sidebar.blockSignals(True)
        self.sidebar.clear()
        retained_ids = set(self.snap.trees) - self._card_ids()

        def add_view(parent, view, kind):
            base = KIND_RETAINED if kind == KIND_RETAINED else KIND_MANUSCRIPT
            child_kind = (KIND_RETAINED_NODE if kind == KIND_RETAINED
                          else KIND_NODE)
            active = QTreeWidgetItem(["Active manuscript"])
            active.setData(0, _ROLE, (base, view.id, None))
            parent.addChild(active)
            for nid in view.order:
                info = view.nodes[nid]
                marker = "  [active path]" if info.on_active_path else ""
                item = QTreeWidgetItem([f"{nid}  {info.word_count}w{marker}"])
                item.setData(0, _ROLE, (child_kind, view.id, nid))
                parent.addChild(item)

        groups = {}
        for row in self.snap.scenes:
            g = row.group
            if g not in groups:
                groups[g] = QTreeWidgetItem([g])
                self.sidebar.addTopLevelItem(groups[g])
            item = QTreeWidgetItem([f"{row.id} — {row.title or '(untitled)'}"])
            item.setData(0, _ROLE, ("scene", row.id, None))
            groups[g].addChild(item)
            view = self.snap.trees.get(row.id)
            if view is not None:
                add_view(item, view, KIND_NODE)
            else:
                ms = QTreeWidgetItem(["(no saved tree)"])
                ms.setData(0, _ROLE, (KIND_MANUSCRIPT, row.id, None))
                item.addChild(ms)
        if retained_ids:
            group = QTreeWidgetItem(["Retained trees"])
            self.sidebar.addTopLevelItem(group)
            for stem in sorted(retained_ids):
                view = self.snap.trees[stem]
                item = QTreeWidgetItem([f"{stem} (retained)"])
                item.setData(0, _ROLE, (KIND_RETAINED, stem, None))
                group.addChild(item)
                add_view(item, view, KIND_RETAINED)
        self.sidebar.expandAll()
        # restore selection by identity; never silently pick a different node
        item = self._find_item(self._sel_data) if self._sel_data else None
        if item is not None:
            self.sidebar.setCurrentItem(item)
        self.sidebar.blockSignals(False)

    # ------------------------------------------------------------ display

    def _on_selection_changed(self):
        item = self.sidebar.currentItem()
        if item is None:
            return
        data = item.data(0, _ROLE)
        if data is None or data == self._sel_data:
            return
        kind, tree_id, node_id = data
        scene_id = (tree_id if kind in (KIND_MANUSCRIPT, KIND_NODE)
                    and tree_id in self._card_ids() else None)
        if scene_id != self._scene_sel:
            if self._scene_sel is not None and self.dirty():
                if not self._leave_scene():
                    self.sidebar.blockSignals(True)
                    prev = self._find_item(self._sel_data)
                    if prev is not None:
                        self.sidebar.setCurrentItem(prev)
                    self.sidebar.blockSignals(False)
                    return
            self._bind_steering(scene_id)
        self._sel_data = data
        self._missing_node = None
        self._update_panes()

    def _leave_scene(self):
        """Resolve a dirty scene switch; False keeps the original scene."""
        pick = self._choice(
            "Unsaved steering",
            f"Steering for {self._scene_sel} has unsaved changes.",
            ["Save", "Discard", "Cancel"])
        if pick == "Save":
            return self._persist(self.steer_editor.toPlainText())
        if pick == "Discard":
            return True
        return False

    def _bind_steering(self, scene_id):
        self._scene_sel = scene_id
        if scene_id is None:
            self._steer = ss.SteeringState(
                scene_id=None, text="", baseline=None, editable=False,
                reason="no current scene selected; steering is per scene")
        else:
            self._steer = self._steering_state(scene_id)
        self._set_editor_text(self._steer.text or "")

    def _steering_state(self, scene_id):
        try:
            return ss.load(self._root, scene_id)
        except OSError as e:
            return ss.SteeringState(scene_id=scene_id, text=None, baseline=None,
                                    editable=False,
                                    reason=f"sources could not be read "
                                           f"({type(e).__name__})")

    def _set_editor_text(self, text):
        pos, anchor = self.steer_editor.textCursor().position(), \
            self.steer_editor.textCursor().anchor()
        self.steer_editor.setPlainText(text)
        cur = self.steer_editor.textCursor()
        cur.setPosition(min(pos, len(text)), QTextCursor.MoveMode.MoveAnchor)
        self.steer_editor.setTextCursor(cur)

    def _steer_edited(self):
        self._update_steering_label()

    def _update_steering_label(self):
        if self._steer is None:
            self.steer_label.setText("Steering — no current scene selected")
            return
        scene = self._scene_sel
        if scene is None:
            self.steer_label.setText("Steering — no current scene selected")
            return
        bits = []
        if self.dirty():
            bits.append("unsaved")
        if not self._steer.editable:
            bits.append(f"read-only: {self._steer.reason}")
        elif self._stale_config:
            bits.append("paused: project configuration is invalid")
        elif self.snap is not None and scene not in self._card_ids():
            bits.append("scene no longer present; unsaved text kept")
        self.steer_label.setText(
            "Steering — " + scene + ((" — " + "; ".join(bits)) if bits else ""))

    def _update_steering_ui(self):
        scene_ok = (self._scene_sel is None
                    or self._scene_sel in self._card_ids())
        editable = bool(self._steer and self._steer.editable
                        and self._steer.baseline is not None
                        and not self._stale_config
                        and self._missing_node is None
                        and scene_ok)
        self.save_btn.setEnabled(editable)
        self.clear_btn.setEnabled(editable)
        self._update_steering_label()

    def _reading_text(self):
        kind, tree_id, node_id = self._sel_data or (None, None, None)
        if self.snap is None:
            return ""
        if self._missing_node is not None:
            return (f"[node {self._missing_node} is no longer present in the "
                    "saved project. Select another item.]")
        if kind in (KIND_MANUSCRIPT, KIND_RETAINED):
            view = self.snap.trees.get(tree_id)
            if view is None:
                return (f"[{tree_id} has no saved tree yet.]\n" if
                        kind == KIND_MANUSCRIPT else "")
            if view.active_text is None:
                return ("[active text unavailable: the active chain is "
                        "broken. Saved nodes remain readable in the sidebar.]")
            return view.active_text
        if kind in (KIND_NODE, KIND_RETAINED_NODE):
            view = self.snap.trees.get(tree_id)
            info = view.nodes.get(node_id) if view is not None else None
            if info is None:
                return ""
            return info.text
        return ""

    def _metadata_text(self):
        kind, tree_id, node_id = self._sel_data or (None, None, None)
        if self.snap is None:
            return ""
        lines = []
        row = next((r for r in self.snap.scenes if r.id == tree_id), None)
        view = self.snap.trees.get(tree_id)
        if row is not None:
            lines += [f"scene: {row.id}", f"title: {row.title or '(none)'}",
                      f"chapter: {row.chapter or '(none)'}",
                      f"status: {row.status or '(none)'}",
                      f"target words: {row.target_words}",
                      f"tree: trees/{tree_id}.json"]
        elif kind == KIND_RETAINED:
            lines += [f"retained tree: {tree_id}", "scene card: (none)"]
        if view is not None:
            lines.append(f"head: {view.head if view.head is not None else '(none)'}")
            lines.append(f"saved nodes: {len(view.nodes)}")
            if view.active_text is None:
                lines.append("active text: unavailable (broken active chain); "
                             "saved nodes remain readable")
            elif view.active_words is not None:
                total = ", partial totals" if not self.snap.words_complete else ""
                lines.append(f"active words: {view.active_words}{total}")
            info = view.nodes.get(node_id) if node_id else None
            if info is not None:
                lines += [
                    f"id: {info.id}",
                    f"parent: {info.parent if info.parent is not None else '(none)'}",
                    f"children: {', '.join(info.children) if info.children else '(none)'}",
                    f"word count: {info.word_count}",
                    f"source: {info.source if info.source is not None else '(absent)'}",
                    f"model: {info.model if info.model is not None else '(absent)'}",
                    f"created: {info.created if info.created is not None else '(absent)'}",
                    f"steer used: {info.steer if info.steer is not None else '(absent)'}",
                    f"ended: {info.ended if info.ended is not None else '(absent)'}",
                    f"trimmed: {info.trimmed if info.trimmed is not None else '(absent)'}",
                ]
                if info.history:
                    lines.append("history:")
                    for h in info.history:
                        lines.append(f"  {h['time']} by {h['by']}: "
                                     f"{h['text'][:120]}")
                else:
                    lines.append("history: (none)")
        if self._missing_node is not None:
            lines.append(f"node {self._missing_node}: (no longer present)")
        return "\n".join(lines)

    def _notes_entries_from(self, snap):
        out = []
        n = snap.notes
        if n.bible is not None:
            out.append(("bible", "Story bible — bible.md", n.bible))
        if n.state is not None:
            out.append(("state", "Continuity state — state.md", n.state))
        if n.summaries is not None:
            for sid, e in n.summaries.scenes.items():
                if e.detailed is not None:
                    out.append((f"sum:{sid}:detailed",
                                f"Scene summary {sid} — detailed", e.detailed))
                if e.brief is not None:
                    out.append((f"sum:{sid}:brief",
                                f"Scene summary {sid} — brief", e.brief))
            for i, a in enumerate(n.summaries.arcs):
                out.append((f"arc:{i}", f"Arc summary {a.from_id} → {a.to_id}",
                            a.text))
        for f_ in n.checks:
            out.append((f"checks:{f_.name}", f"Check report — checks/{f_.name}",
                        f_.text))
        for f_ in n.critiques:
            out.append((f"critiques:{f_.name}",
                        f"Critique — critiques/{f_.name}", f_.text))
        return out

    def _on_note_selected(self, row):
        if 0 <= row < len(self._notes_entries):
            self._notes_key = self._notes_entries[row][0]
            self.notes_view.setPlainText(self._notes_entries[row][2])

    # ------------------------------------------------------------ steering

    def save_steering(self):
        self._persist(self.steer_editor.toPlainText())

    def clear_steering(self):
        self._persist("")

    def _persist(self, text):
        """Save (or clear) steering through the narrow adapter only."""
        if self._steer is None or not self._steer.editable:
            reason = self._steer.reason if self._steer else "no scene selected"
            self._status(f"Steering is read-only: {reason}", error=True)
            return False
        scene = self._scene_sel
        outcome = ss.save(self._root, scene, text, self._steer.baseline)
        if outcome.ok:
            self._steer.text = text
            self._steer.baseline = outcome.baseline
            self._set_editor_text(text)
            self._status(f"Steering saved for {scene}")
            self.refresh(force=True)
            return True
        if outcome.stale:
            pick = self._choice(
                "Saved steering changed",
                (f"{outcome.reason}\n\nReload the saved steering (discarding "
                 "your unsaved text) or keep editing?"),
                ["Reload saved steering", "Keep editing"])
            if pick == "Reload saved steering":
                state = self._steering_state(scene)
                self._steer = state
                self._set_editor_text(state.text or "")
                self._status(f"Reloaded saved steering for {scene}")
            else:
                self._status("Kept your edits; saved steering changed on disk. "
                             "Saving again will ask to reload or keep editing.",
                             error=True)
            return False
        self._status(f"Steering was not saved: {outcome.reason}", error=True)
        return False

    # ------------------------------------------------------------- panes

    def _update_panes(self):
        """Refresh displayed content while preserving view state."""
        if self.snap is None:
            return
        self._reconcile_selection()
        self._update_pane(self.reading, self._reading_text())
        self._update_pane(self.metadata, self._metadata_text())
        self._update_notes()
        self._update_steering_pane()
        self._update_steering_ui()

    def _reconcile_selection(self):
        """Mark removed selections explicitly instead of switching selection."""
        kind, tree_id, node_id = self._sel_data or (None, None, None)
        self._missing_node = None
        if kind in (KIND_NODE, KIND_RETAINED_NODE):
            view = self.snap.trees.get(tree_id)
            if view is None or node_id not in view.nodes:
                self._missing_node = node_id

    def _update_pane(self, pane, text):
        if pane.toPlainText() == text:
            return  # unchanged: scroll/cursor/focus stay untouched
        bar = pane.verticalScrollBar()
        pos = bar.value()
        pane.setPlainText(text)
        bar.setValue(min(pos, bar.maximum()))

    def _update_notes(self):
        entries = self._notes_entries_from(self.snap)
        if entries == self._notes_entries:
            return
        self._notes_entries = entries
        row = self.notes_list.currentRow()
        wanted = self._notes_key
        self.notes_list.blockSignals(True)
        self.notes_list.clear()
        for _key, label, _text in entries:
            self.notes_list.addItem(QListWidgetItem(label))
        if not entries:
            self.notes_view.setPlainText("(no supporting notes found)")
            self._notes_key = None
        else:
            idx = next((i for i, (k, _l, _t) in enumerate(entries)
                        if k == wanted), 0)
            self.notes_list.setCurrentRow(idx)
            self._notes_key = entries[idx][0]
            self._update_pane(self.notes_view, entries[idx][2])
        self.notes_list.blockSignals(False)

    def _update_steering_pane(self):
        """Clean steering may follow external updates; dirty text never moves."""
        if self._steer is None or not self._steer.editable:
            return
        view = (self.snap.trees.get(self._scene_sel)
                if self._scene_sel is not None else None)
        if view is None:
            return  # scene gone: dirty text is kept, writes disabled
        disk = view.steer if view.steer_valid else ""
        if self.dirty():
            if disk != (self._steer.text or ""):
                self._status("Saved steering changed on disk while you have "
                             "unsaved edits; Save will offer Reload or Keep "
                             f"editing ({self._scene_sel})")
            return
        if disk != self.steer_editor.toPlainText():
            state = self._steering_state(self._scene_sel)
            if state.editable:
                self._steer = state
                self._set_editor_text(state.text or "")

    # --------------------------------------------------------------- close

    def closeEvent(self, ev):
        if self._scene_sel is not None and self.dirty():
            pick = self._choice(
                "Unsaved steering",
                f"Steering for {self._scene_sel} has unsaved changes. Save "
                "before closing?", ["Save", "Discard", "Cancel"])
            if pick == "Save":
                if not self._persist(self.steer_editor.toPlainText()):
                    ev.ignore()
                    return
            elif pick != "Discard":  # Cancel or dismissed
                ev.ignore()
                return
        ev.accept()
