"""PySide6 Qt Widgets shell: reading, steering and the complete draft loop.

Presentation layer (ADR-0006): widgets consume sanitized reader_model
snapshots; steering writes go through the Qt-independent scene_steering
adapter, and every draft action (generation, acceptance, edits, branches,
lore) runs as a shared draft_operations call on one background worker
(ADR-0007) whose queued, operation-tagged signals are the only path that
touches widgets. No terminal helpers, external editors or subprocesses.
"""

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QSpinBox, QSplitter, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from .prompt import tail_trim_chars
from .utils import word_diff
from . import draft_operations as dop
from . import planning_operations as plan
from . import reader_model as rm
from . import scene_steering as ss
from .cancel import CancellationToken
from .draft_worker import OpThread
from .reader_model import SourceCache

PRE_START_GUIDANCE = (
    "longform gui: native Wayland is required. If startup fails, check your "
    "Wayland desktop session/socket and the Qt Wayland/system libraries, then "
    "retry: QT_QPA_PLATFORM=wayland uv run --script longform.py gui DIR")

REFRESH_MS = 2000

# Tabs
MANUSCRIPT, BRANCHES, DRAFT, SCENE, CONTEXT, LORE, NOTES = 0, 1, 2, 3, 4, 5, 6
SETUP, BIBLE = 7, 8
OUTLINE, SCENES = 9, 10
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
    """One window: sidebar navigation, read-only panes, steering and the
    draft loop through shared operations on one background worker."""

    def __init__(self, dir_path, *, load=None, timer_factory=None, choice=None,
                 provider_factory=None, picker=None, dir_picker=None,
                 preset_picker=None):
        super().__init__()
        self._root = Path(dir_path)
        self._load = load or rm.load_snapshot
        self._cache = SourceCache()
        self._choice = choice or _ask_choice
        self._timer_factory = timer_factory
        self._provider_factory = provider_factory
        self._picker = picker or self._default_picker
        self._dir_picker = dir_picker or self._default_dir_picker
        self._preset_picker = preset_picker or self._default_preset_picker
        self._plan = plan.project_overview(self._root)

        self.snap = None              # last valid Snapshot
        self._stale_config = False    # required configuration currently invalid
        self._sel_data = None         # (kind, tree_id, node_id) of selection
        self._missing_node = None     # selected node removed from the project
        self._scene_sel = None        # scene id the steering editor is bound to
        self._steer = None            # scene_steering.SteeringState
        self._notes_entries = []      # [(key, label, text)]
        self._notes_key = None

        # Draft session state (ADR-0007): one worker, one token, one op at a time.
        self._busy = False
        self._op_id = 0
        self._thread = None
        self._token = CancellationToken()
        self._batch = None            # {"scene","parent","saved","streamed"}
        self._preview_text = ""
        self._op_scene = None
        self._op_kind = "generate"
        self._op_rows = None
        self._view_override = None    # (label, text) shown until cleared
        self._draft_left = False
        self._scene_edit_dirty = {}   # scene -> user edited pov/cast fields
        self._editor_target = None
        self._pending_root = None     # project root bound after Create/Open ok
        self._pending_action = None   # ("create"/"open", root) after a dirty save
        self._import_src = None       # picked preset source bytes identity
        self._settings_touched = {}   # field path -> user edited
        self._settings_state = {}     # last loaded shared settings state
        self._bible_overview = None   # cached read-only section list
        self._bible_heading = None
        self._bible_session = False
        self._bible_mode = "form"     # "form" or "text"
        self._bible_form_loaded = None
        self._bible_text_loaded = None
        self._bible_baseline = None   # captured pre/secs + bible.md bytes
        self._bible_preview_section = None
        self._bible_preview_is_current = True
        self._outline_overview = None
        self._outline_candidates = []   # candidate names generated this session
        self._outline_notes_loaded = None
        self._outline_body_loaded = None
        self._scenes_overview = None
        self._scene_cards = None      # working preview card list
        self._scenes_card_row = None
        self._scenes_preview_baseline = None
        self._scenes_force_once = False
        try:
            self._session = dop.session_info(self._root)
        except dop.OpError as e:
            self._session = {"swipes": 1, "passage_words": 220, "model": "",
                             "preset_found": False, "creds_ok": False,
                             "api_key_env": "", "warnings": [str(e)],
                             "scene_ok": False}

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
        self.create_btn = QPushButton("Create…")
        self.create_btn.setToolTip("Initialize a project directory with the "
                                   "CLI init contents (create-missing-only; "
                                   "existing files are never replaced)")
        self.create_btn.clicked.connect(self.create_project)
        top.addWidget(self.create_btn)
        self.open_btn = QPushButton("Open…")
        self.open_btn.setToolTip("Open an existing project directory; "
                                 "reads without initializing or calling "
                                 "the provider")
        self.open_btn.clicked.connect(self.open_project_dialog)
        top.addWidget(self.open_btn)
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
        branch_widget = QWidget()
        branch_l = QVBoxLayout(branch_widget)
        branch_l.setContentsMargins(0, 0, 0, 0)
        branch_l.addLayout(self._build_branches_controls())
        branch_l.addWidget(self.metadata, 1)
        self.tabs.addTab(branch_widget, "Branches")
        self.tabs.addTab(self._build_draft_tab(), "Draft")
        self.tabs.addTab(self._build_scene_tab(), "Scene")
        self.tabs.addTab(self._build_context_tab(), "Context")
        self.tabs.addTab(self._build_lore_tab(), "Lore")
        self.tabs.addTab(self._build_notes_tab(), "Notes")
        self.tabs.addTab(self._build_setup_tab(), "Setup")
        self.tabs.addTab(self._build_bible_tab(), "Bible")
        self.tabs.addTab(self._build_outline_tab(), "Outline")
        self.tabs.addTab(self._build_scenes_tab(), "Scenes")
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
        btns.addWidget(self.save_btn)
        btns.addWidget(self.clear_btn)
        btns.addStretch(1)
        btns.addWidget(QLabel("Candidates"))
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 99)
        self.count_spin.setValue(int(self._session.get("swipes", 1)))
        self.count_spin.setToolTip(
            "Candidate count for Generate (default: writer.swipes)")
        btns.addWidget(self.count_spin)
        self.generate_btn = QPushButton("Generate")
        self.generate_btn.clicked.connect(self.generate)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        btns.addWidget(self.generate_btn)
        btns.addWidget(self.stop_btn)
        steer_l.addLayout(btns)
        self.generate_note = QLabel("")
        steer_l.addWidget(self.generate_note)
        right_l.addWidget(steer_box)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        root.addWidget(split, 1)

        self.status = QLabel("")
        self.statusBar().addWidget(self.status, 1)

    def show_help(self):
        """Draft action help in the reading pane (CLI ?); no terminal."""
        from .commands import DRAFT_HELP
        self._view_override = ("draft help", DRAFT_HELP)
        self._update_panes()

    def leave_draft(self):
        """Leave/re-enter the draft session; saved prose stays readable and
        unsaved editors are resolved explicitly."""
        if self._draft_left:
            self._draft_left = False
            self._update_steering_ui()
            self._status("Draft session active again.")
            return
        if self._scene_sel is not None and self.dirty():
            pick = self._choice(
                "Unsaved steering",
                f"Steering for {self._scene_sel} has unsaved changes. Save "
                "before leaving the draft loop?",
                ["Save", "Discard", "Cancel"])
            if pick == "Save":
                if not self._persist(self.steer_editor.toPlainText()):
                    return
            elif pick != "Discard":
                return
        self._draft_left = True
        self._view_override = None
        self._update_panes()
        self._update_steering_ui()
        self._status("Left the draft loop; saved prose, branches and notes "
                     "stay readable. Leave draft again to re-enter.")

    def _build_scene_tab(self):
        """Scene controls: card, POV/cast, session length, status/warnings,
        Mark done, Next unfinished. Full card editing belongs to planning."""
        box = QWidget()
        l = QVBoxLayout(box)
        l.setContentsMargins(0, 0, 0, 0)
        l.addWidget(QLabel("Scene card (read-only here; editing belongs to setup/planning)"))
        self.scene_card = QPlainTextEdit()
        self.scene_card.setReadOnly(True)
        l.addWidget(self.scene_card, 2)
        form = QHBoxLayout()
        form.addWidget(QLabel("POV"))
        self.pov_edit = self._line()
        self.pov_edit.textEdited.connect(
            lambda: self._scene_edit_dirty.__setitem__(self._scene_sel, True))
        form.addWidget(self.pov_edit)
        self.save_pov_btn = QPushButton("Save POV")
        self.save_pov_btn.clicked.connect(self.save_pov)
        form.addWidget(self.save_pov_btn)
        form.addWidget(QLabel("Cast"))
        self.cast_edit = self._line()
        self.cast_edit.textEdited.connect(
            lambda: self._scene_edit_dirty.__setitem__(self._scene_sel, True))
        form.addWidget(self.cast_edit)
        self.save_cast_btn = QPushButton("Save cast")
        self.save_cast_btn.clicked.connect(self.save_cast)
        form.addWidget(self.save_cast_btn)
        l.addLayout(form)
        lenform = QHBoxLayout()
        lenform.addWidget(QLabel("Passage length (words, this session; also caps max_tokens)"))
        self.length_spin = QSpinBox()
        self.length_spin.setRange(1, 4000)
        self.length_spin.setValue(int(self._session.get("passage_words", 220)))
        self.length_spin.setToolTip(
            "Session-only: the CLI `l` semantics; the stored writer default "
            "is not changed")
        lenform.addWidget(self.length_spin)
        lenform.addStretch(1)
        l.addLayout(lenform)
        self.scene_status = QLabel("")
        l.addWidget(self.scene_status)
        self.scene_warnings = QLabel("")
        self.scene_warnings.setWordWrap(True)
        l.addWidget(self.scene_warnings)
        btns = QHBoxLayout()
        self.mark_done_btn = QPushButton("Mark done")
        self.mark_done_btn.setToolTip("Mark the scene done and exit active "
                                      "drafting controls; continuity update "
                                      "remains an explicit later step")
        self.mark_done_btn.clicked.connect(self.mark_done)
        btns.addWidget(self.mark_done_btn)
        self.next_unfinished_btn = QPushButton("Next unfinished")
        self.next_unfinished_btn.setToolTip(
            "Select the first scene that is not done; done scenes can still "
            "be reopened by selecting them, like CLI --scene")
        self.next_unfinished_btn.clicked.connect(self.next_unfinished)
        btns.addWidget(self.next_unfinished_btn)
        btns.addStretch(1)
        l.addLayout(btns)
        l.addStretch(1)
        return box

    def _build_context_tab(self):
        """Budget/sampler/injected-lore inspection and exact prompt dump; no
        provider calls ever."""
        box = QWidget()
        l = QVBoxLayout(box)
        l.setContentsMargins(0, 0, 0, 0)
        btns = QHBoxLayout()
        self.inspect_btn = QPushButton("Inspect next call")
        self.inspect_btn.setToolTip("Budget parts, ceiling, samplers and "
                                    "injected lore for the current captured "
                                    "inputs — no provider call")
        self.inspect_btn.clicked.connect(self.inspect_context)
        btns.addWidget(self.inspect_btn)
        self.exact_prompt_btn = QPushButton("Exact prompt")
        self.exact_btn = self.exact_prompt_btn
        self.exact_prompt_btn.setToolTip("Show the exact prompt bytes for the "
                                         "next call — no provider call")
        self.exact_prompt_btn.clicked.connect(self.show_exact_prompt)
        btns.addWidget(self.exact_prompt_btn)
        self.save_prompt_btn = QPushButton("Save last_prompt.txt")
        self.save_prompt_btn.setToolTip("Write the exact prompt bytes to "
                                        "last_prompt.txt (CLI cp's dump)")
        self.save_prompt_btn.clicked.connect(self.save_last_prompt)
        btns.addWidget(self.save_prompt_btn)
        btns.addStretch(1)
        l.addLayout(btns)
        self.context_view = QPlainTextEdit()
        self.context_view.setReadOnly(True)
        l.addWidget(self.context_view, 1)
        return box

    def _line(self):
        from PySide6.QtWidgets import QLineEdit
        edit = QLineEdit()
        edit.setPlaceholderText("(unset)")
        return edit

    def _build_draft_tab(self):
        """Provisional preview and completed candidate tray (never accepts)."""
        box = QWidget()
        l = QVBoxLayout(box)
        l.setContentsMargins(0, 0, 0, 0)
        self.preview_label = QLabel("Preview — provisional streaming text (not saved)")
        l.addWidget(self.preview_label)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText(
            "Streaming output appears here while the provider works; it is "
            "never accepted or saved until a complete candidate is saved.")
        l.addWidget(self.preview, 2)
        l.addWidget(QLabel("Saved candidates (branches; nothing is accepted until you press Accept)"))
        self.tray = QListWidget()
        self.tray.setToolTip("Completed candidates for this batch, newest "
                             "siblings of the batch's captured head")
        l.addWidget(self.tray, 3)
        tbtns = QHBoxLayout()
        self.accept_btn = QPushButton("Accept selected")
        self.accept_btn.setToolTip("Make the selected candidate the active "
                                   "head; other candidates stay saved branches")
        self.accept_btn.clicked.connect(self.accept_candidate)
        tbtns.addWidget(self.accept_btn)
        self.view_btn = QPushButton("View")
        self.view_btn.setToolTip("Show the selected saved candidate's full "
                                 "text; nothing is accepted")
        self.view_btn.clicked.connect(self.view_candidate)
        tbtns.addWidget(self.view_btn)
        self.reroll_btn = QPushButton("Reroll selected")
        self.reroll_btn.setToolTip("Regenerate the selected slots as siblings "
                                   "of the batch's captured head; originals "
                                   "stay saved as branches")
        self.reroll_btn.clicked.connect(self.reroll_selected)
        tbtns.addWidget(self.reroll_btn)
        self.reroll_all_btn = QPushButton("Reroll all")
        self.reroll_all_btn.clicked.connect(self.reroll_all)
        tbtns.addWidget(self.reroll_all_btn)
        tbtns.addWidget(QLabel("Add"))
        self.add_spin = QSpinBox()
        self.add_spin.setRange(1, 99)
        self.add_spin.setValue(1)
        tbtns.addWidget(self.add_spin)
        self.add_btn = QPushButton("Add N")
        self.add_btn.setToolTip("Append N more candidates to this batch; they "
                                "share the batch's captured head")
        self.add_btn.clicked.connect(self.add_candidates)
        tbtns.addWidget(self.add_btn)
        self.delete_btn = QPushButton("Delete leaf")
        self.delete_btn.setToolTip("Delete the selected candidate only if it "
                                   "is a leaf; never deletes saved prose with "
                                   "children")
        self.delete_btn.clicked.connect(self.delete_candidate)
        tbtns.addWidget(self.delete_btn)
        tbtns.addStretch(1)
        self.keep_btn = QPushButton("Keep branches (close tray)")
        self.keep_btn.setToolTip("Close the tray; every saved candidate stays "
                                 "in the branch tree and the head is unchanged")
        self.keep_btn.clicked.connect(lambda: self.close_tray("Keep branches"))
        tbtns.addWidget(self.keep_btn)
        self.discard_btn = QPushButton("Discard preview (close tray)")
        self.discard_btn.setToolTip(
            "Non-destructive, like Keep branches: it only closes the tray — "
            "deleting prose requires the separately labelled Delete leaf")
        self.discard_btn.clicked.connect(lambda: self.close_tray("Discard preview"))
        tbtns.addWidget(self.discard_btn)
        l.addLayout(tbtns)
        ebtns = QHBoxLayout()
        self.new_passage_btn = QPushButton("New passage")
        self.new_passage_btn.setToolTip(
            "Open the built-in editor to write a passage yourself; it is "
            "appended after the head as a new paragraph (no external editor)")
        self.new_passage_btn.clicked.connect(self.new_passage)
        ebtns.addWidget(self.new_passage_btn)
        self.edit_head_btn = QPushButton("Edit head")
        self.edit_head_btn.setToolTip(
            "Open the built-in editor on the head passage; history and the "
            "diff are recorded (no external editor)")
        self.edit_head_btn.clicked.connect(self.edit_head)
        ebtns.addWidget(self.edit_head_btn)
        self.editor_save_btn = QPushButton("Save")
        self.editor_save_btn.clicked.connect(self.save_editor)
        ebtns.addWidget(self.editor_save_btn)
        self.editor_cancel_btn = QPushButton("Cancel")
        self.editor_cancel_btn.clicked.connect(self.cancel_editor)
        ebtns.addWidget(self.editor_cancel_btn)
        ebtns.addStretch(1)
        l.addLayout(ebtns)
        hbtns = QHBoxLayout()
        self.help_btn = QPushButton("Draft help")
        self.help_btn.setToolTip("Show the draft and candidate actions in the "
                                 "reading pane (CLI ? help)")
        self.help_btn.clicked.connect(self.show_help)
        hbtns.addWidget(self.help_btn)
        self.leave_btn = QPushButton("Leave draft")
        self.leave_btn.setToolTip(
            "Leave the active draft session without closing the reader; "
            "unsaved editors are resolved explicitly")
        self.leave_btn.clicked.connect(self.leave_draft)
        hbtns.addWidget(self.leave_btn)
        hbtns.addStretch(1)
        l.addLayout(hbtns)
        self.help_label = QLabel(
            "Tray actions: Accept selected / View / Reroll selected / Reroll "
            "all / Add N / Delete leaf / Keep branches or Discard preview — "
            "nothing is accepted or deleted implicitly.")
        self.help_label.setWordWrap(True)
        l.addWidget(self.help_label)
        self.editor_label = QLabel("Editor (no external editor is started)")
        l.addWidget(self.editor_label)
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(
            "Write here; Save applies through the shared operations, Cancel "
            "discards. Empty or unchanged input makes no change.")
        l.addWidget(self.editor, 1)
        self.editor_diff = QLabel("")
        self.editor_diff.setWordWrap(True)
        l.addWidget(self.editor_diff)
        return box

    def _build_branches_controls(self):
        """Branch bar for the Branches tab: rewind/jump/delete/marked/tail."""
        bar = QHBoxLayout()
        self.rewind_btn = QPushButton("Rewind")
        self.rewind_btn.setToolTip("Move head to its parent; the branch is kept")
        self.rewind_btn.clicked.connect(self.rewind)
        bar.addWidget(self.rewind_btn)
        self.use_as_head_btn = QPushButton("Use as head")
        self.use_as_head_btn.setToolTip(
            "Switch the accepted path to the selected saved node (explicit, "
            "like CLI j ID)")
        self.use_as_head_btn.clicked.connect(self.use_as_head)
        bar.addWidget(self.use_as_head_btn)
        self.delete_node_btn = QPushButton("Delete leaf")
        self.delete_node_btn.setToolTip("Delete the selected node only if it "
                                        "has no children")
        self.delete_node_btn.clicked.connect(self.delete_selected_node)
        bar.addWidget(self.delete_node_btn)
        self.marked_btn = QPushButton("Marked manuscript")
        self.marked_btn.setToolTip("Show the active path with node markers "
                                   "(CLI v)")
        self.marked_btn.clicked.connect(self.show_marked)
        bar.addWidget(self.marked_btn)
        bar.addWidget(QLabel("Tail"))
        self.tail_spin = QSpinBox()
        self.tail_spin.setRange(1, 100000)
        self.tail_spin.setValue(600)
        bar.addWidget(self.tail_spin)
        self.tail_btn = QPushButton("Tail N")
        self.tail_btn.setToolTip("Show the last N characters of the current "
                                 "scene (CLI tail, default 600)")
        self.tail_btn.clicked.connect(self.show_tail)
        bar.addWidget(self.tail_btn)
        bar.addStretch(1)
        return bar

    def new_passage(self):
        if self._busy:
            return
        self._editor_target = ("new", None)
        self.editor_label.setText(
            f"New passage for {self._scene_sel} — appended after the head as "
            "a new paragraph (source=user)")
        self.editor.setPlainText("")
        self.editor_diff.setText("")

    def edit_head(self):
        if self._busy or self._scene_sel is None:
            return
        view = self.snap.trees.get(self._scene_sel) if self.snap else None
        if view is None or view.head is None:
            self._status("nothing to edit", error=True)
            return
        self._editor_target = ("edit", view.head)
        self.editor_label.setText(f"Editing head {view.head} — history keeps "
                                  "the old text (by user-edit)")
        self.editor.setPlainText(view.nodes[view.head].text)
        self.editor_diff.setText("")

    def save_editor(self):
        if self._busy or self._scene_sel is None:
            return
        target = getattr(self, "_editor_target", None)
        if target is None:
            self._status("Open New passage or Edit head first.")
            return
        text = self.editor.toPlainText()
        scene = self._scene_sel
        self._op_scene = scene
        if target[0] == "new":
            if not text.strip():
                self._status("Empty input: no passage added.")
                return

            def fn(sink, token):
                return dop.append_manual(self._root, scene, text, token=token)

        else:
            def fn(sink, token):
                return dop.edit_head(self._root, scene, text, token=token)

        self._dispatch(fn, kind="editor", rows=target)

    def cancel_editor(self):
        self._editor_target = None
        self.editor.setPlainText("")
        self.editor_diff.setText("")
        self.editor_label.setText("Editor (no external editor is started)")

    def _branch_node_selected(self):
        kind, tree_id, node_id = self._sel_data or (None, None, None)
        if kind in (KIND_NODE, KIND_RETAINED_NODE) and node_id:
            return tree_id, node_id
        return None

    def rewind(self):
        if self._busy or self._scene_sel is None:
            return
        scene = self._scene_sel
        self._op_scene = scene

        def fn(sink, token):
            return dop.rewind(self._root, scene, token=token)

        self._dispatch(fn, kind="branch")

    def use_as_head(self):
        if self._busy:
            return
        sel = self._branch_node_selected()
        if sel is None:
            self._status("Select a node in the sidebar to use it as head.")
            return
        tree_id, nid = sel
        self._op_scene = tree_id

        def fn(sink, token):
            return dop.jump(self._root, tree_id, nid, token=token)

        self._dispatch(fn, kind="branch")

    def delete_selected_node(self):
        if self._busy:
            return
        sel = self._branch_node_selected()
        if sel is None:
            self._status("Select a node in the sidebar to delete it.")
            return
        tree_id, nid = sel
        self._op_scene = tree_id

        def fn(sink, token):
            return dop.delete_leaf(self._root, tree_id, nid, token=token)

        self._dispatch(fn, kind="branch")

    def show_marked(self):
        """CLI `v`: the active path with node markers (view-only)."""
        if self.snap is None or self._scene_sel is None:
            return
        view = self.snap.trees.get(self._scene_sel)
        if view is None or view.active_ids is None:
            self._status("active text unavailable; saved nodes remain "
                         "readable in the sidebar", error=True)
            return
        text = "\n\n".join(f"--- {i} ---\n{view.nodes[i].text.strip()}"
                           for i in view.active_ids)
        self._view_override = (f"marked manuscript for {self._scene_sel}", text)
        self._update_panes()

    def show_tail(self):
        """CLI `tail [N]`: the last N characters of the active path."""
        if self.snap is None or self._scene_sel is None:
            return
        view = self.snap.trees.get(self._scene_sel)
        if view is None or view.active_text is None:
            self._status("(empty)")
            return
        n = self.tail_spin.value()
        text = tail_trim_chars(n, view.active_text, marker="…")
        self._view_override = ("tail", f"last {n} chars (head "
                                       f"{view.head or '-'}):\n{text}")
        self._update_panes()

    def _build_lore_tab(self):
        """All discovered books with on/kind/character/role/entries; toggles,
        classification and picker imports through the shared operations."""
        box = QWidget()
        l = QVBoxLayout(box)
        l.setContentsMargins(0, 0, 0, 0)
        self.lore_tree = QTreeWidget()
        self.lore_tree.setHeaderLabels(["Book", "Kind", "Character", "Role",
                                        "Entries", "On", "Aliases"])
        self.lore_tree.setRootIsDecorated(False)
        l.addWidget(self.lore_tree, 1)
        r1 = QHBoxLayout()
        self.lore_toggle_btn = QPushButton("Toggle selected")
        self.lore_toggle_btn.setToolTip("Toggle the selected lorebooks on/off "
                                        "(CLI lb N)")
        self.lore_toggle_btn.clicked.connect(self.lore_toggle_selected)
        r1.addWidget(self.lore_toggle_btn)
        self.lore_all_on_btn = QPushButton("All on")
        self.lore_all_on_btn.clicked.connect(lambda: self.lore_set_all(True))
        r1.addWidget(self.lore_all_on_btn)
        self.lore_all_off_btn = QPushButton("All off")
        self.lore_all_off_btn.clicked.connect(lambda: self.lore_set_all(False))
        r1.addWidget(self.lore_all_off_btn)
        r1.addWidget(QLabel("Character name"))
        self.lore_char_edit = self._line()
        r1.addWidget(self.lore_char_edit)
        self.lore_char_btn = QPushButton("Set Character + name")
        self.lore_char_btn.clicked.connect(self.lore_set_char)
        r1.addWidget(self.lore_char_btn)
        r1.addStretch(1)
        l.addLayout(r1)
        r2 = QHBoxLayout()
        r2.addWidget(QLabel("Aliases (comma-separated)"))
        self.lore_alias_edit = self._line()
        r2.addWidget(self.lore_alias_edit)
        self.lore_alias_btn = QPushButton("Set aliases")
        self.lore_alias_btn.clicked.connect(self.lore_set_aliases)
        r2.addWidget(self.lore_alias_btn)
        self.lore_world_btn = QPushButton("Mark World")
        self.lore_world_btn.clicked.connect(self.lore_set_world)
        r2.addWidget(self.lore_world_btn)
        r2.addStretch(1)
        l.addLayout(r2)
        r3 = QHBoxLayout()
        self.lore_import_btn = QPushButton("Import JSON/PNG lorebook or card…")
        self.lore_import_btn.setToolTip("Reads the picked file with the "
                                        "existing card/World Info parsing, "
                                        "copies unchanged bytes into "
                                        "lorebooks/ and runs discovery; "
                                        "cancelling or an invalid file writes "
                                        "nothing")
        self.lore_import_btn.clicked.connect(self.lore_import)
        r3.addWidget(self.lore_import_btn)
        r3.addStretch(1)
        l.addLayout(r3)
        self.lore_note = QLabel("")
        self.lore_note.setWordWrap(True)
        l.addWidget(self.lore_note)
        return box

    def _lore_refresh(self):
        """Rebuild the lore list; classification rows come from the shared op."""
        scene = self._scene_sel
        if scene is None or self.snap is None:
            self.lore_tree.clear()
            self.lore_note.setText("select a scene to classify roles")
            return
        try:
            rows = dop.lore_rows(self._root, scene)
            self.lore_note.setText("")
        except dop.OpError as e:
            self.lore_note.setText(f"(lore unavailable: {e})")
            return
        current = self.lore_tree.currentItem()
        want = current.data(0, _ROLE) if current else None
        self.lore_tree.blockSignals(True)
        self.lore_tree.clear()
        for r in rows:
            item = QTreeWidgetItem([
                f"{r['n']:>2} {r['file']}", r["kind"], r["who"], r["role"],
                str(r["entries"]), "on" if r["on"] else "off",
                ""])
            item.setData(0, _ROLE, r["n"])
            self.lore_tree.addTopLevelItem(item)
        if want is not None:
            for i in range(self.lore_tree.topLevelItemCount()):
                if self.lore_tree.topLevelItem(i).data(0, _ROLE) == want:
                    self.lore_tree.setCurrentItem(self.lore_tree.topLevelItem(i))
                    break
        self.lore_tree.blockSignals(False)

    def _lore_selected(self):
        item = self.lore_tree.currentItem()
        return item.data(0, _ROLE) if item else None

    def _lore_dispatch(self, mkfn, kind="lore"):
        if self._busy or self._scene_sel is None:
            if self._scene_sel is None:
                self._status("Select a scene first (lore roles are per scene).")
            return
        scene = self._scene_sel
        self._op_scene = scene

        def fn(sink, token):
            return mkfn(scene, token)

        self._dispatch(fn, kind=kind)

    def lore_toggle_selected(self):
        k = self._lore_selected()
        if k is None:
            self._status("Select a lorebook row to toggle it.")
            return
        self._lore_dispatch(lambda scene, token:
                            dop.lore_toggle(self._root, scene, [k], token=token))

    def lore_set_all(self, on):
        self._lore_dispatch(lambda scene, token:
                            dop.lore_set_all(self._root, scene, on, token=token))

    def lore_set_char(self):
        k = self._lore_selected()
        if k is None:
            self._status("Select a lorebook row to classify it.")
            return
        name = self.lore_char_edit.text().strip()
        self._lore_dispatch(lambda scene, token:
                            dop.lore_set_char(self._root, scene, k, name,
                                              token=token))

    def lore_set_aliases(self):
        k = self._lore_selected()
        if k is None:
            self._status("Select a lorebook row to set aliases.")
            return
        names = [x.strip() for x in self.lore_alias_edit.text().split(",")]
        self._lore_dispatch(lambda scene, token:
                            dop.lore_set_aliases(self._root, scene, k, names,
                                                 token=token))

    def lore_set_world(self):
        k = self._lore_selected()
        if k is None:
            self._status("Select a lorebook row to classify it.")
            return
        self._lore_dispatch(lambda scene, token:
                            dop.lore_set_world(self._root, scene, k, token=token))

    def lore_import(self):
        """Desktop picker import; no selection means no writes."""
        if self._busy:
            return
        src = self._picker("Pick a World Info JSON or character card (JSON/PNG)")
        if not src:
            self._status("No file picked: nothing was written.")
            return
        self._import_src = src
        scene = self._scene_sel
        self._op_scene = scene

        def fn(sink, token):
            return dop.lore_import(self._root, src, scene, replace=False,
                                   token=token, events=sink)

        self._dispatch(fn, kind="import")

    def _default_picker(self, title):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, title, str(self._root),
                                              "Lorebooks (*.json *.png)")
        return path or None

    def _on_import_collision(self, err):
        """Offer Replace/Cancel naming the destination; re-verify baselines."""
        pick = self._choice(
            "Import destination exists",
            str(err) + "\n\nReplace overwrites the destination bytes "
            "(existing registry metadata for that name is preserved).",
            ["Replace", "Cancel"])
        if pick != "Replace":
            self._status("Import cancelled; destination unchanged.")
            return
        scene = self._scene_sel
        self._op_scene = scene

        def fn(sink, token):
            return dop.lore_import(self._root, self._import_src, scene,
                                   replace=True, token=token, events=sink)

        self._dispatch(fn, kind="import")

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

    def _build_scenes_tab(self):
        """Scenes pane: generate from the saved outline, inspect/edit the
        validated preview, confirmed replacement with backups, then the
        existing draft loop reads the saved cards."""
        box = QWidget()
        l = QVBoxLayout(box)
        l.setContentsMargins(0, 0, 0, 0)
        self.scenes_note = QLabel("")
        self.scenes_note.setWordWrap(True)
        l.addWidget(self.scenes_note)
        sbtns = QHBoxLayout()
        self.scenes_generate_btn = QPushButton("Generate cards")
        self.scenes_generate_btn.setToolTip("Break the saved outline into "
                                            "scene cards on the worker; "
                                            "needs a nonempty outline, a "
                                            "planner model and credentials")
        self.scenes_generate_btn.clicked.connect(self.scenes_generate)
        sbtns.addWidget(self.scenes_generate_btn)
        self.scenes_accept_btn = QPushButton("Accept preview")
        self.scenes_accept_btn.setToolTip("Save the previewed cards as "
                                          "scenes.json (backs up a previous "
                                          "nonempty list; trees are kept; "
                                          "never automatic)")
        self.scenes_accept_btn.clicked.connect(self.scenes_accept)
        sbtns.addWidget(self.scenes_accept_btn)
        self.scenes_cancel_btn = QPushButton("Cancel preview")
        self.scenes_cancel_btn.clicked.connect(self.scenes_cancel)
        sbtns.addWidget(self.scenes_cancel_btn)
        sbtns.addStretch(1)
        l.addLayout(sbtns)
        l.addWidget(QLabel("Previewed cards (select one to edit its fields)"))
        self.scenes_list = QListWidget()
        self.scenes_list.currentRowChanged.connect(self._on_scenes_selected)
        l.addWidget(self.scenes_list, 3)
        self.scenes_preview = QPlainTextEdit()
        self.scenes_preview.setReadOnly(True)
        self.scenes_preview.setPlaceholderText(
            "The generated cards appear here; editing fields below updates "
            "the preview. scenes.json is replaced only on explicit Accept.")
        l.addWidget(self.scenes_preview, 3)
        l.addWidget(QLabel("Selected card fields"))
        grid = QGridLayout()
        grid.setVerticalSpacing(2)
        self._card_field_editors = {}
        fields = (("chapter", "Chapter"), ("title", "Title"), ("pov", "POV"),
                  ("setting", "Setting"), ("characters", "Characters "
                  "(comma)"), ("goal", "Goal"), ("conflict", "Conflict"),
                  ("outcome", "Outcome"), ("target_words", "Target words"),
                  ("beats", "Beats (one per line)"), ("notes", "Notes"))
        for row, (key, label) in enumerate(fields):
            grid.addWidget(QLabel(label), row, 0)
            if key in ("beats", "characters", "notes"):
                w = QPlainTextEdit()
                w.setFixedHeight(40)
            else:
                w = self._line()
            w.textChanged.connect(self._card_field_changed) \
                if hasattr(w, "textChanged") else None
            if key not in ("beats", "characters", "notes"):
                w.textEdited.connect(self._card_field_changed)
            self._card_field_editors[key] = w
            grid.addWidget(w, row, 1)
        grid.setColumnStretch(1, 1)
        holder = QWidget()
        holder.setLayout(grid)
        l.addWidget(holder, 2)
        return box

    # ----------------------------------------------------------------- scenes

    def _refresh_scenes_overview(self):
        try:
            self._scenes_overview = plan.scenes_overview(self._root)
        except dop.OpError as e:
            self._scenes_overview = {"scenes": [], "outline": "", "trees": [],
                                     "target_words": 0, "error": str(e)}
        bits = []
        if self._scenes_overview.get("error"):
            bits.append("scenes unavailable: " + self._scenes_overview["error"])
        else:
            n = len(self._scenes_overview.get("scenes", []))
            bits.append(f"{n} saved scene card(s)")
            if not self._scenes_overview.get("outline"):
                bits.append("scene generation needs a nonempty outline.md "
                            "(generate and choose an outline first)")
        self.scenes_note.setText("; ".join(bits))

    def _update_scenes_tab(self):
        if self._scenes_overview is None:
            self._refresh_scenes_overview()

    def scenes_generate(self):
        """Generate cards from the saved outline (worker); force-equivalent
        confirmation is offered through the worker error path."""
        if self._busy:
            return
        over = self._scenes_overview or {}
        if over.get("error") or not over.get("outline"):
            self._status("Scene generation needs a nonempty outline.md; "
                         "generate and choose an outline first.", error=True)
            return
        root = plan.canonical_root(self._root)
        force = bool(self._scenes_force_once)
        self._scenes_force_once = False

        def fn(sink, token):
            return plan.generate_scene_cards(
                root, force=force,
                provider_factory=self._provider_factory, token=token,
                events=sink)

        self._dispatch(fn, kind="scenes_generate")

    def _on_scenes_selected(self, row):
        cards = self._scene_cards or []
        if not (0 <= row < len(cards)):
            return
        card = cards[row]
        self._scenes_card_row = row
        for key, w in self._card_field_editors.items():
            v = card.get(key, "")
            if key in ("beats", "characters"):
                text = "\n".join(v) if isinstance(v, list) else str(v or "")
            elif key == "notes":
                text = str(v or "")
            else:
                text = "" if v is None else str(v)
            w.blockSignals(True)
            if hasattr(w, "setPlainText"):
                w.setPlainText(text)
            else:
                w.setText(text)
            w.blockSignals(False)

    def _card_field_changed(self):
        row = getattr(self, "_scenes_card_row", None)
        cards = self._scene_cards or []
        if row is None or not (0 <= row < len(cards)):
            return
        card = dict(cards[row])
        for key, w in self._card_field_editors.items():
            if key in ("beats", "characters"):
                card[key] = [x.strip() for x in w.toPlainText().splitlines()
                             if x.strip()] if key == "beats" else \
                    [x.strip() for x in w.toPlainText().replace("\n", ",")
                     .split(",") if x.strip()]
            elif key == "notes":
                card[key] = w.toPlainText()
            else:
                text = w.text().strip() if hasattr(w, "text") else \
                    w.toPlainText().strip()
                card[key] = text
        self._scene_cards[row] = card
        self._rebuild_scenes_preview()

    def _rebuild_scenes_preview(self):
        cards = self._scene_cards or []
        self.scenes_list.blockSignals(True)
        self.scenes_list.clear()
        for k, s in enumerate(cards, 1):
            self.scenes_list.addItem(QListWidgetItem(
                f"[{k}] ch {s.get('chapter', '?')}  {s.get('target_words', 0)}w"
                f"  {s.get('title', '')}"))
        self.scenes_list.blockSignals(False)
        self.scenes_preview.setPlainText(
            plan._scenes_cards_text(cards) if cards else "")
        self._update_scenes_note_counts()

    def _update_scenes_note_counts(self):
        cards = self._scene_cards or []
        if cards:
            total = sum(int(c.get("target_words") or 0) for c in cards)
            tw = (self._scenes_overview or {}).get("target_words", 0)
            self.scenes_note.setText(
                f"preview: {len(cards)} scenes, {total} target words "
                f"(project target {tw}); scenes.json unchanged until Accept")

    def scenes_accept(self):
        """Confirmed replacement through the shared accept operation."""
        if self._busy:
            return
        cards = self._scene_cards
        if not cards:
            self._status("Generate cards first; nothing is saved without an "
                         "explicit preview.", error=True)
            return
        over = self._scenes_overview or {}
        if over.get("scenes"):
            pick = self._choice(
                "Replace saved scenes",
                f"This replaces {len(over['scenes'])} saved scene card(s) "
                "in scenes.json; the previous list is copied to outlines/"
                "scenes_prev_<stamp>.json and every tree is kept. Continue?",
                ["Replace", "Cancel"])
            if pick != "Replace":
                self._status("Replace declined; scenes.json is unchanged.")
                return
        base = self._scenes_preview_baseline
        if not base:
            self._status("Reload (Refresh) and accept again: the acceptance "
                         "needs a captured baseline.", error=True)
            return
        root = plan.canonical_root(self._root)

        def fn(sink, token):
            return plan.accept_scene_cards(root, [dict(c) for c in cards],
                                           dict(base), token=token,
                                           events=sink)

        self._dispatch(fn, kind="scenes_accept")

    def scenes_cancel(self):
        """Cancel: the preview is discarded; scenes.json is unchanged."""
        self._scene_cards = []
        self._scenes_preview_baseline = None
        self._scenes_card_row = None
        self._rebuild_scenes_preview()
        self.scenes_note.setText("; ".join([
            "preview cancelled; scenes.json unchanged"]))

    def set_card_field(self, row, key, text):
        """Test/keyboard helper: edit one previewed card field."""
        cards = self._scene_cards or []
        if not (0 <= row < len(cards)):
            self._status(f"no previewed card {row}", error=True)
            return
        self._on_scenes_selected(row)
        w = self._card_field_editors[key]
        if hasattr(w, "setPlainText"):
            w.setPlainText(str(text))
        else:
            w.setText(str(text))
        self._card_field_changed()

    def _build_outline_tab(self):
        """Outline pane: multiline notes, N competing planner candidates,
        view/reroll/choose/edit with backups — no implicit acceptance."""
        box = QWidget()
        l = QVBoxLayout(box)
        l.setContentsMargins(0, 0, 0, 0)
        self.outline_note = QLabel("")
        self.outline_note.setWordWrap(True)
        l.addWidget(self.outline_note)
        self.outline_editor_label = QLabel(
            "Notes for the planner (multiline; # lines are ignored when the "
            "prompt is built)")
        l.addWidget(self.outline_editor_label)
        self.outline_notes_edit = QPlainTextEdit()
        self.outline_notes_edit.setPlaceholderText(
            "Anything you want the planner to follow; Leave empty for no "
            "notes")
        l.addWidget(self.outline_notes_edit, 2)
        gbtns = QHBoxLayout()
        gbtns.addWidget(QLabel("Candidates (N>=1)"))
        self.outline_n_spin = QSpinBox()
        self.outline_n_spin.setRange(1, 99)
        self.outline_n_spin.setValue(2)
        gbtns.addWidget(self.outline_n_spin)
        self.outline_generate_btn = QPushButton("Generate")
        self.outline_generate_btn.setToolTip("Save the notes and generate N "
                                             "competing candidates on the "
                                             "worker; needs a nonempty saved "
                                             "bible and planner credentials")
        self.outline_generate_btn.clicked.connect(self.outline_generate)
        gbtns.addWidget(self.outline_generate_btn)
        self.outline_reroll_btn = QPushButton("Reroll same notes")
        self.outline_reroll_btn.setToolTip("Append N more candidates with "
                                           "the current notes; earlier "
                                           "candidates are never deleted")
        self.outline_reroll_btn.clicked.connect(
            lambda: self.outline_generate(reroll=True))
        gbtns.addWidget(self.outline_reroll_btn)
        gbtns.addStretch(1)
        l.addLayout(gbtns)
        self.outline_list_label = QLabel("Candidates (newest appended)")
        l.addWidget(self.outline_list_label)
        self.outline_list = QListWidget()
        l.addWidget(self.outline_list, 3)
        vbtns = QHBoxLayout()
        self.outline_view_btn = QPushButton("View candidate")
        self.outline_view_btn.clicked.connect(self.outline_view)
        vbtns.addWidget(self.outline_view_btn)
        self.outline_choose_btn = QPushButton("Choose as outline.md")
        self.outline_choose_btn.setToolTip("Back up any previous outline and "
                                           "save the chosen body without its "
                                           "notes comment; no scene "
                                           "generation follows")
        self.outline_choose_btn.clicked.connect(self.outline_choose)
        vbtns.addWidget(self.outline_choose_btn)
        self.outline_edit_btn = QPushButton("Edit body")
        self.outline_edit_btn.clicked.connect(self.outline_edit_body)
        vbtns.addWidget(self.outline_edit_btn)
        self.outline_save_btn = QPushButton("Save edited outline")
        self.outline_save_btn.setToolTip("Commit the working body through the "
                                         "same backed-up boundary; the "
                                         "candidate file stays unchanged")
        self.outline_save_btn.clicked.connect(self.outline_save_body)
        vbtns.addWidget(self.outline_save_btn)
        self.outline_cancel_btn = QPushButton("Cancel")
        self.outline_cancel_btn.clicked.connect(self.outline_cancel)
        vbtns.addWidget(self.outline_cancel_btn)
        vbtns.addStretch(1)
        l.addLayout(vbtns)
        self.outline_body_label = QLabel(
            "Working outline body (saved outline.md appears here when no "
            "candidate is selected)")
        l.addWidget(self.outline_body_label)
        self.outline_body_edit = QPlainTextEdit()
        self.outline_body_edit.setReadOnly(True)
        l.addWidget(self.outline_body_edit, 4)
        return box

    # ---------------------------------------------------------------- outline

    def _refresh_outline_overview(self):
        try:
            self._outline_overview = plan.outline_overview(self._root)
            self._outline_overview["baseline"] = plan.outline_baseline(
                self._root, self._outline_overview.get("candidates", []))
        except dop.OpError as e:
            self._outline_overview = {"notes_form": "", "notes": "",
                                      "outline": None, "candidates": [],
                                      "bible_present": False, "error": str(e)}
        self._rebuild_outline_list()

    def _rebuild_outline_list(self):
        over = self._outline_overview or {}
        self.outline_list.blockSignals(True)
        self.outline_list.clear()
        for name in over.get("candidates", []):
            self.outline_list.addItem(QListWidgetItem(name))
        self.outline_list.blockSignals(False)
        notes = over.get("notes_form") or ""
        if self._outline_notes_loaded is None or \
                (self.outline_notes_edit.toPlainText() ==
                 (self._outline_notes_loaded or "") and notes !=
                 (self._outline_notes_loaded or "")):
            self.outline_notes_edit.setPlainText(notes)
            self._outline_notes_loaded = notes
        bits = []
        if over.get("outline") is not None:
            bits.append("outline.md saved")
        else:
            bits.append("no outline.md yet")
        if not over.get("bible_present"):
            bits.append("outline generation needs a nonempty bible.md "
                        "(answer and accept a bible section first)")
        self.outline_note.setText("; ".join(bits))

    def _update_outline_tab(self):
        if self._outline_overview is None:
            self._refresh_outline_overview()

    def _outline_notes_dirty(self):
        return self.outline_notes_edit.toPlainText() != \
            (self._outline_notes_loaded or "")

    def outline_generate(self, reroll=False):
        """Save the current notes and generate N candidates (worker)."""
        if self._busy:
            return
        over = self._outline_overview or {}
        if not over.get("bible_present"):
            self._status("Outline generation needs a nonempty bible.md; "
                         "answer and accept a bible section first.",
                         error=True)
            return
        notes_form = self.outline_notes_edit.toPlainText()
        n = self.outline_n_spin.value()
        root = plan.canonical_root(self._root)

        def fn(sink, token):
            return plan.generate_outlines(root, notes_form, n,
                                          provider_factory=self._provider_factory,
                                          token=token, events=sink)

        self._dispatch(fn, kind="outline_generate")

    def _outline_selected(self):
        row = self.outline_list.currentRow()
        names = (self._outline_overview or {}).get("candidates", [])
        return names[row] if 0 <= row < len(names) else None

    def outline_view(self):
        name = self._outline_selected()
        if name is None:
            self._status("Select a candidate to view it.")
            return
        try:
            text = plan.read_outline_candidate(self._root, name)
        except dop.OpError as e:
            self._status(str(e), error=True)
            return
        self._view_override = (f"candidate {name} (view only)", text)
        self._update_panes()

    def outline_choose(self):
        """Explicit choice bound to the current captured inputs."""
        if self._busy:
            return
        name = self._outline_selected()
        if name is None:
            self._status("Select a candidate to choose it.")
            return
        if self._outline_notes_dirty() or self._outline_body_dirty():
            self._status("Unsaved notes or body edits; Save or Cancel them "
                         "before choosing.", error=True)
            return
        root = plan.canonical_root(self._root)
        base = self._outline_overview.get("baseline")
        if not base:
            self._status("Reload the outline pane (Refresh) and try again: "
                         "the choice needs a captured baseline.", error=True)
            return
        history = name not in self._outline_candidates

        def fn(sink, token):
            return plan.choose_outline(root, name, dict(base), token=token,
                                       events=sink)

        self._dispatch(fn, kind="outline_choose")

    def outline_edit_body(self):
        """Edit the currently shown outline body (saved outline.md or chosen
        candidate) in the built-in editor."""
        self._outline_body_loaded = self.outline_body_edit.toPlainText()
        self.outline_body_edit.setReadOnly(False)
        self.outline_body_label.setText(
            "Working outline body (local edits; Save commits through the "
            "backed-up boundary)")

    def _outline_body_dirty(self):
        return self._outline_body_loaded is not None and \
            self.outline_body_edit.toPlainText() != self._outline_body_loaded

    def outline_save_body(self):
        if self._busy or not self._outline_body_dirty():
            if not self._outline_body_dirty():
                self._status("No body changes to save; open Edit body first.")
            return
        body = self.outline_body_edit.toPlainText()
        root = plan.canonical_root(self._root)
        base = (self._outline_overview or {}).get("baseline")
        if not base:
            self._status("Reload the outline pane (Refresh) and try again.",
                         error=True)
            return

        def fn(sink, token):
            return plan.save_outline_body(root, body, dict(base), token=token,
                                          events=sink)

        self._dispatch(fn, kind="outline_save_body")

    def outline_cancel(self):
        """Leave: revert the working body to the saved outline.md."""
        self._outline_body_loaded = None
        self.outline_body_edit.setReadOnly(True)
        over = self._outline_overview or {}
        self.outline_body_edit.setPlainText(over.get("outline") or "")
        self.outline_body_label.setText(
            "Working outline body (saved outline.md appears here when no "
            "candidate is selected)")

    def _build_bible_tab(self):
        """Bible pane: fixed section questions with multiline forms, saved
        answers, preview, Accept/Skip/Leave, direct section editing and
        history — the CLI bible session without a terminal or $EDITOR."""
        box = QWidget()
        l = QVBoxLayout(box)
        l.setContentsMargins(0, 0, 0, 0)
        l.addWidget(QLabel("Sections (## headings of bible.md)"))
        self.bible_list = QListWidget()
        self.bible_list.currentRowChanged.connect(self._on_bible_selected)
        l.addWidget(self.bible_list, 2)
        self.bible_editor_label = QLabel(
            "Answer form (multiline; Enter inserts a newline; lines starting "
            "with # are ignored)")
        l.addWidget(self.bible_editor_label)
        self.bible_form_edit = QPlainTextEdit()
        self.bible_form_edit.setPlaceholderText(
            "The fixed CLI question form appears here once you begin "
            "answering; saved answers are reused on reopen")
        l.addWidget(self.bible_form_edit, 3)
        btns = QHBoxLayout()
        self.bible_begin_btn = QPushButton("Begin answering")
        self.bible_begin_btn.setToolTip("Start a session: backs up the "
                                        "existing bible once "
                                        "(bible_history/bible_<stamp>.md), "
                                        "like the CLI session start")
        self.bible_begin_btn.clicked.connect(self.bible_begin)
        btns.addWidget(self.bible_begin_btn)
        self.bible_save_btn = QPushButton("Save answers")
        self.bible_save_btn.setToolTip("Persist the exact form and input "
                                       "history, then preview the composed "
                                       "section — bible.md is not changed")
        self.bible_save_btn.clicked.connect(self.bible_save)
        btns.addWidget(self.bible_save_btn)
        self.bible_accept_btn = QPushButton("Accept section")
        self.bible_accept_btn.setToolTip("Replace only this section in "
                                         "bible.md (preamble, section order "
                                         "and other sections preserved)")
        self.bible_accept_btn.clicked.connect(self.bible_accept)
        btns.addWidget(self.bible_accept_btn)
        self.bible_edit_btn = QPushButton("Edit answers")
        self.bible_edit_btn.clicked.connect(self.bible_edit_answers)
        btns.addWidget(self.bible_edit_btn)
        self.bible_skip_btn = QPushButton("Skip section")
        self.bible_skip_btn.setToolTip("Leave this section unchanged; saved "
                                       "answers remain")
        self.bible_skip_btn.clicked.connect(self.bible_skip)
        btns.addWidget(self.bible_skip_btn)
        self.bible_leave_btn = QPushButton("Leave session")
        self.bible_leave_btn.setToolTip("End the session; previously saved "
                                        "answers and accepted sections "
                                        "remain")
        self.bible_leave_btn.clicked.connect(self.bible_leave)
        btns.addWidget(self.bible_leave_btn)
        btns.addStretch(1)
        l.addLayout(btns)
        btns2 = QHBoxLayout()
        self.bible_text_edit_btn = QPushButton("Edit section text")
        self.bible_text_edit_btn.setToolTip("Directly edit the section body "
                                            "(freeform text and custom "
                                            "headings; never relabels or "
                                            "drops content)")
        self.bible_text_edit_btn.clicked.connect(self.bible_edit_text)
        btns2.addWidget(self.bible_text_edit_btn)
        self.bible_text_save_btn = QPushButton("Save section text")
        self.bible_text_save_btn.clicked.connect(self.bible_save_text)
        btns2.addWidget(self.bible_text_save_btn)
        self.bible_text_cancel_btn = QPushButton("Cancel text edit")
        self.bible_text_cancel_btn.clicked.connect(self.bible_cancel_text)
        btns2.addWidget(self.bible_text_cancel_btn)
        self.bible_history_btn = QPushButton("History")
        self.bible_history_btn.setToolTip("Read saved bible snapshots and "
                                          "answer-history files; no restore "
                                          "protocol")
        self.bible_history_btn.clicked.connect(self.bible_history_view)
        btns2.addWidget(self.bible_history_btn)
        btns2.addStretch(1)
        l.addLayout(btns2)
        self.bible_preview = QPlainTextEdit()
        self.bible_preview.setReadOnly(True)
        self.bible_preview.setPlaceholderText(
            "The composed section preview appears here after Save answers; "
            "it replaces the section only on explicit Accept")
        l.addWidget(self.bible_preview, 2)
        self.bible_note = QLabel("")
        self.bible_note.setWordWrap(True)
        l.addWidget(self.bible_note)
        return box

    # ----------------------------------------------------------------- bible

    def _refresh_bible_overview(self):
        try:
            self._bible_overview = plan.bible_overview(self._root)
        except dop.OpError as e:
            self._bible_overview = {"has_sections": False, "sections": [],
                                    "error": str(e), "chars": [],
                                    "bible_path": "bible.md"}
        self._rebuild_bible_list()

    def _rebuild_bible_list(self):
        over = self._bible_overview or {}
        current = self._bible_heading
        self.bible_list.blockSignals(True)
        self.bible_list.clear()
        for s in over.get("sections", []):
            mark = " (placeholder)" if s["placeholder"] else ""
            self.bible_list.addItem(QListWidgetItem(s["heading"] + mark))
        if current is not None:
            for i, s in enumerate(over.get("sections", [])):
                if s["heading"] == current:
                    self.bible_list.setCurrentRow(i)
                    break
        self.bible_list.blockSignals(False)
        self._update_bible_note()

    def _update_bible_note(self):
        over = self._bible_overview or {}
        bits = []
        if over.get("error"):
            bits.append("bible unavailable: " + over["error"])
        if over.get("over_budget"):
            bits.append(f"bible is ~{over.get('tokens')} tokens, over its "
                        f"{over.get('budget')} budget: shorten the longest "
                        "sections or move detail into lorebooks")
        elif over.get("sections"):
            bits.append(f"~{over.get('tokens')} tokens (budget "
                        f"{over.get('budget')})")
        if self._bible_session:
            bits.append("session active; the existing bible is backed up")
        self.bible_note.setText("; ".join(bits))

    def _update_bible_tab(self):
        if self._bible_overview is None:
            self._refresh_bible_overview()

    def _on_bible_selected(self, row):
        over = self._bible_overview or {}
        if not (0 <= row < len(over.get("sections", []))):
            return
        heading = over["sections"][row]["heading"]
        if self._bible_dirty() and heading != self._bible_heading:
            pick = self._choice(
                "Unsaved bible form",
                f"The {self._bible_heading or 'section'} form has unsaved "
                "changes. Save before switching?",
                ["Save", "Discard", "Cancel"])
            if pick == "Save":
                if not self.bible_save():
                    return
            elif pick != "Discard":
                return
        self._bible_heading = heading
        self._load_bible_form()

    def _load_bible_form(self):
        try:
            st = plan.bible_form_state(self._root, self._bible_heading)
        except dop.OpError as e:
            self.bible_note.setText(f"(form unavailable: {e})")
            return
        self._bible_form_loaded = st["form"]
        self._bible_mode = "form"
        self.bible_form_edit.setPlainText(st["form"])
        self.bible_editor_label.setText(
            f"Answer form for {self._bible_heading}" +
            (" (saved answers reused)" if st["saved_form"] else "") +
            "; current section text is in the preview pane below")
        self.bible_preview.setPlainText(st["current"] or "(empty)")

    def _bible_dirty(self):
        return (self._bible_mode == "form" and self._bible_heading is not None
                and self.bible_form_edit.toPlainText() !=
                (self._bible_form_loaded or "")) or \
            (self._bible_mode == "text" and self.bible_form_edit.toPlainText()
             != (self._bible_text_loaded or ""))

    def bible_begin(self):
        """Explicit session start: backs up the existing bible once."""
        if self._busy:
            return
        over = self._bible_overview or {}
        if not over.get("has_sections"):
            self._status(over.get("error") or "no bible sections", error=True)
            return
        root = plan.canonical_root(self._root)

        def fn(sink, token):
            out = plan.begin_bible_session(root, token=token, events=sink)
            out["baseline"] = plan.bible_baseline(root)
            return out

        self._dispatch(fn, kind="bible_begin")

    def bible_save(self):
        """Save answers (form + history) and preview; bible.md unchanged."""
        if self._busy or self._bible_heading is None:
            if self._bible_heading is None:
                self._status("Select a bible section first.")
            return False
        form = self.bible_form_edit.toPlainText()
        root = plan.canonical_root(self._root)
        heading = self._bible_heading

        def fn(sink, token):
            return plan.save_bible_answers(root, heading, form, token=token,
                                           events=sink)

        self._dispatch(fn, kind="bible_save")
        return True

    def bible_accept(self):
        """Explicit Accept: replace only this section of the captured bible."""
        if self._busy or self._bible_heading is None:
            return
        if not self._bible_session:
            self._status("Begin answering first: a session backs up the "
                         "existing bible before any section is replaced.",
                         error=True)
            return
        if not self.bible_preview.toPlainText().strip() or \
                self._bible_preview_is_current:
            self._status("Save answers first; the preview is what Accept "
                         "writes.", error=True)
            return
        section = self._bible_preview_section
        if section is None:
            self._status("Save answers first.", error=True)
            return
        if self._bible_dirty():
            self._status("The form has unsaved changes; Save answers before "
                         "accepting.", error=True)
            return
        base = self._bible_baseline
        heading = self._bible_heading
        root = plan.canonical_root(self._root)

        def fn(sink, token):
            return plan.accept_bible_section(root, heading, section,
                                             baseline=dict(base), token=token,
                                             events=sink)

        self._dispatch(fn, kind="bible_accept")

    def bible_edit_answers(self):
        """Return from the preview to the (saved) answer form."""
        if self._bible_heading is None:
            return
        self._bible_mode = "form"
        self._load_bible_form()

    def bible_skip(self):
        """Skip: nothing is written; saved answers stay."""
        self._bible_preview_section = None
        self.bible_preview.setPlainText("")
        self._status(f"Skipped {self._bible_heading}; saved answers and "
                     "accepted sections remain.")

    def bible_leave(self):
        """Leave the session: unaccepted previews are not committed."""
        self._bible_session = False
        self._bible_baseline = None
        self._bible_preview_section = None
        self.bible_preview.setPlainText("")
        self._status("Left the bible session; previously saved answers and "
                     "accepted sections remain.")

    def bible_edit_text(self):
        """Direct freeform section-text editing (built-in editor)."""
        over = self._bible_overview or {}
        sec = next((s for s in over.get("sections", [])
                    if s["heading"] == self._bible_heading), None)
        if sec is None:
            self._status("Select a bible section first.")
            return
        self._bible_mode = "text"
        self._bible_text_loaded = sec["body"]
        self.bible_form_edit.setPlainText(sec["body"])
        self.bible_editor_label.setText(
            f"Section text for {self._bible_heading} (freeform; custom "
            "headings and preamble are never relabeled or dropped)")

    def bible_save_text(self):
        if self._busy or self._bible_mode != "text":
            if self._bible_mode != "text":
                self._status("Open Edit section text first.")
            return
        body = self.bible_form_edit.toPlainText()
        heading = self._bible_heading
        root = plan.canonical_root(self._root)
        base = self._bible_baseline or self._refresh_bible_baseline()

        def fn(sink, token):
            return plan.edit_bible_section(root, heading, body,
                                           baseline=dict(base), token=token,
                                           events=sink)

        self._dispatch(fn, kind="bible_text_save")

    def bible_cancel_text(self):
        if self._bible_mode == "text":
            self._load_bible_form()

    def _refresh_bible_baseline(self):
        try:
            self._bible_baseline = plan.bible_baseline(self._root)
        except dop.OpError:
            self._bible_baseline = None
        return self._bible_baseline

    def bible_history_view(self):
        """Read-only history viewer in the reading pane."""
        try:
            hist = plan.bible_history(self._root)
        except dop.OpError as e:
            self._status(str(e), error=True)
            return
        lines = []
        for b in hist["bibles"]:
            lines.append(f"=== bible_history/{b['name']} ===\n{b['text']}")
        for a in hist["answers"]:
            lines.append(f"=== {a['name']} ===\n{a['text']}")
        for e in hist["errors"]:
            lines.append("warning: " + e)
        self._view_override = ("bible history",
                               "\n\n".join(lines) or "(no history files)")
        self._update_panes()

    def _build_setup_tab(self):
        """Setup pane: project state, preset import; settings arrive with the
        settings task. Create/Open stay on the top bar for every state."""
        box = QWidget()
        l = QVBoxLayout(box)
        l.setContentsMargins(0, 0, 0, 0)
        self.setup_status = QLabel("")
        self.setup_status.setWordWrap(True)
        l.addWidget(self.setup_status)
        row = QHBoxLayout()
        self.preset_import_btn = QPushButton("Import writer preset…")
        self.preset_import_btn.setToolTip("Pick a SillyTavern master-export "
                                          "JSON; its original bytes are "
                                          "copied to writer_preset.json. An "
                                          "existing destination is never "
                                          "overwritten.")
        self.preset_import_btn.clicked.connect(self.import_preset)
        row.addWidget(self.preset_import_btn)
        row.addStretch(1)
        l.addLayout(row)
        self.preset_note = QLabel("")
        self.preset_note.setWordWrap(True)
        l.addWidget(self.preset_note)
        self.setup_note = QLabel("")
        self.setup_note.setWordWrap(True)
        l.addWidget(self.setup_note)

        l.addWidget(QLabel("Settings (supported nonsecret project.json "
                           "fields; unknown fields and any existing key are "
                           "preserved)"))
        self.settings_note = QLabel("")
        self.settings_note.setWordWrap(True)
        sbtns = QHBoxLayout()
        self.settings_save_btn = QPushButton("Save settings")
        self.settings_save_btn.setToolTip("Validate and save only the fields "
                                          "you changed; blank clears an "
                                          "optional field")
        self.settings_save_btn.clicked.connect(self.save_settings)
        sbtns.addWidget(self.settings_save_btn)
        self.settings_cancel_btn = QPushButton("Cancel settings")
        self.settings_cancel_btn.setToolTip("Discard unsaved entries; the "
                                            "saved configuration is used")
        self.settings_cancel_btn.clicked.connect(self.cancel_settings)
        sbtns.addWidget(self.settings_cancel_btn)
        sbtns.addStretch(1)
        l.addLayout(sbtns)
        self.settings_form = self._build_settings_form()
        l.addWidget(self.settings_form, 2)

        l.addWidget(QLabel("Limits (fetched only by explicit action; a "
                           "model 404 is a found:false result)"))
        lbtns = QHBoxLayout()
        self.fetch_limits_btn = QPushButton("Fetch limits")
        self.fetch_limits_btn.setToolTip("One /plan request plus one lookup "
                                         "per distinct configured model "
                                         "through the shared Api; saves "
                                         "limits.json in the CLI shape")
        self.fetch_limits_btn.clicked.connect(self.fetch_limits)
        lbtns.addWidget(self.fetch_limits_btn)
        lbtns.addStretch(1)
        l.addLayout(lbtns)
        self.limits_view = QPlainTextEdit()
        self.limits_view.setReadOnly(True)
        self.limits_view.setPlaceholderText(
            "Fetched time, plan context/concurrency and each role's model "
            "context, max completion and plan availability appear here; "
            "credentials are never displayed.")
        l.addWidget(self.limits_view, 2)
        return box

    def _build_settings_form(self):
        """Generated validated form from the shared field allowlist."""
        from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout,
                                       QLineEdit, QScrollArea)
        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setVerticalSpacing(2)
        self._setting_editors = {}
        for row, (path, label, kind) in enumerate(plan.SETTING_FIELDS):
            lab = QLabel(label)
            lab.setToolTip(path)
            grid.addWidget(lab, row, 0)
            if kind == "bool":
                w = QCheckBox()
                w.stateChanged.connect(
                    lambda _s, p=path: self._touch_setting(p))
            elif kind.startswith("enum:"):
                w = QComboBox()
                w.addItems([""] + kind.split(":", 1)[1].split("|"))
                w.currentIndexChanged.connect(
                    lambda _i, p=path: self._touch_setting(p))
            elif kind == "lines":
                w = QPlainTextEdit()
                w.setFixedHeight(46)
                w.textChanged.connect(lambda p=path: self._touch_setting(p))
            else:
                w = QLineEdit()
                w.setPlaceholderText("(unset)" if ".preset_overrides." in
                                     path or kind not in ("text", "nonblank",
                                                          "url", "envname")
                                     else "")
                w.textEdited.connect(lambda _t, p=path: self._touch_setting(p))
            self._setting_editors[path] = (w, kind)
            grid.addWidget(w, row, 1)
        grid.setColumnStretch(1, 1)
        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        return scroll

    def _touch_setting(self, path):
        self._settings_touched[path] = True
        self._update_steering_ui()

    def settings_value(self, path):
        """Test/keyboard helper: the editor widget for one field."""
        return self._setting_editors[path][0]

    def set_setting(self, path, text):
        """Test/keyboard helper: set one field's raw text and mark it dirty."""
        w, kind = self._setting_editors[path]
        if kind == "bool":
            w.setChecked(str(text).lower() in ("1", "true", "yes"))
        elif kind.startswith("enum:"):
            w.setCurrentText(str(text))
        elif kind == "lines":
            w.setPlainText(str(text))
        else:
            w.setText(str(text))
        self._touch_setting(path)

    def _load_settings_form(self):
        """Fill the form from the shared read-only state (no calls)."""
        try:
            state = plan.settings_state(self._root)
        except dop.OpError as e:
            self.settings_note.setText(f"(settings unavailable: {e})")
            return
        self._settings_state = dict(state)
        self._settings_touched = {}
        try:
            self._settings_state["baseline"] = dict(
                plan.settings_baseline(self._root))
        except dop.OpError:
            self._settings_state["baseline"] = None
        for path, value in state["values"].items():
            w, kind = self._setting_editors[path]
            w.blockSignals(True)   # programmatic fill never marks dirty
            if kind == "bool":
                w.setChecked(bool(value))
            elif kind.startswith("enum:"):
                w.setCurrentText(str(value or ""))
            elif kind == "lines":
                w.setPlainText("\n".join(value) if isinstance(value, list)
                               else str(value or ""))
            else:
                w.setText("" if value is None else str(value))
            w.blockSignals(False)
        notes = list(state["warnings"])
        if not state["creds_ok"]:
            notes.append("no credentials: provider calls (Fetch limits, "
                         "generation) are unavailable, local editing still "
                         "works")
        self.settings_note.setText("; ".join(notes))

    def settings_dirty(self):
        return bool(self._settings_touched)

    def _settings_payload(self):
        values = {}
        for path in self._settings_touched:
            w, kind = self._setting_editors[path]
            if kind == "bool":
                values[path] = "true" if w.isChecked() else "false"
            elif kind.startswith("enum:"):
                values[path] = w.currentText() or None
            elif kind == "lines":
                text = w.toPlainText()
                values[path] = text if text.strip() else None
            else:
                values[path] = w.text().strip() or None
        return values

    def save_settings(self):
        """Validate and save the touched fields through the shared op."""
        if self._busy:
            self._status("An operation is running; settings writes are "
                         "paused until it settles.", error=True)
            return False
        values = self._settings_payload()
        root = plan.canonical_root(self._root)
        base = self._settings_state.get("baseline")
        if not base:
            try:
                base = dict(plan.settings_baseline(root))
            except dop.OpError as e:
                self._status(str(e), error=True)
                return False

        def fn(sink, token):
            return plan.save_settings(root, values, baseline=dict(base),
                                      token=token, events=sink)

        self._dispatch(fn, kind="settings_save")
        return True

    def cancel_settings(self):
        """Discard unsaved entries; the saved configuration stays."""
        self._settings_touched = {}
        self._load_settings_form()
        self._status("Settings unchanged; saved configuration in use.")

    def fetch_limits(self):
        """Explicit limits fetch; never runs on Create/Open/Save/tab change."""
        if self._busy:
            return
        root = plan.canonical_root(self._root)

        def fn(sink, token):
            return plan.fetch_limits(
                root, provider_factory=self._provider_factory,
                token=token, events=sink)

        self._dispatch(fn, kind="limits")

    def _limits_text(self, view):
        import json
        lines = [f"fetched: {view['fetched']}"]
        lines.append(f"plan: max context {view['plan_max_context']}, "
                     f"concurrency {view['plan_concurrency']}")
        for r in view["roles"]:
            if not r["found"]:
                lines.append(f"{r['role']:<10} {r['model']}: NOT FOUND "
                             "(check the exact id)")
                continue
            lines.append(f"{r['role']:<10} {r['model']}")
            lines.append(f"           context {r['context']}, max completion "
                         f"{r['max_completion']}, available on your plan: "
                         f"{r['available']}")
            if r["available"] is False:
                lines.append("           not available on your current plan")
            raw = r.get("raw")
            if raw is not None:
                lines.append("           raw: " + json.dumps(raw)[:400])
        return "\n".join(lines)

    # ------------------------------------------------------------- create/open

    def _resolve_dirty(self):
        """Resolve unsaved input before a destructive transition (project
        Create/Open); False cancels or defers the transition."""
        if self._scene_sel is not None and self.dirty():
            pick = self._choice(
                "Unsaved steering",
                f"Steering for {self._scene_sel} has unsaved changes.",
                ["Save", "Discard", "Cancel"])
            if pick == "Save":
                if not self._persist(self.steer_editor.toPlainText()):
                    return False
            elif pick != "Discard":
                return False
        if self._planning_dirty():
            pick = self._choice(
                "Unsaved planning input",
                "Settings, bible, outline or scene editing has unsaved "
                "changes. Save before continuing?",
                ["Save", "Discard", "Cancel"])
            if pick == "Save":
                if not self._save_planning_dirty():
                    return False   # the transition resumes after settlement
                return False
            if pick == "Discard":
                self._discard_planning_dirty()
                return True
            return False
        return True

    def _planning_dirty(self):
        return (self.settings_dirty() or self._bible_dirty()
                or self._outline_notes_dirty() or self._outline_body_dirty())

    def _save_planning_dirty(self):
        if self._bible_dirty():
            return self.bible_save()
        if self._outline_body_dirty():
            return self.outline_save_body()
        return self.save_settings()

    def _discard_planning_dirty(self):
        self._settings_touched = {}
        if self._bible_mode == "form":
            self.bible_form_edit.setPlainText(self._bible_form_loaded or "")
        else:
            self.bible_form_edit.setPlainText(self._bible_text_loaded or "")
        self.outline_notes_edit.setPlainText(self._outline_notes_loaded or "")
        self._outline_body_loaded = None
        self.outline_cancel()

    def _run_pending_action(self):
        """Continue a Create/Open deferred behind a dirty-form Save."""
        action = self._pending_action
        self._pending_action = None
        if action is None:
            return
        kind, target = action
        self._pending_root = target
        if kind == "create":
            def fn(sink, token):
                return plan.init_project(target, token=token, events=sink)
            self._dispatch(fn, kind="init")
        else:
            def fn(sink, token):
                return plan.project_overview(target)
            self._dispatch(fn, kind="open")

    def create_project(self):
        """Desktop Create: pick a location, initialize create-missing-only."""
        if self._busy:
            self._status("An operation is running; Create is disabled until "
                         "it settles.", error=True)
            return
        if not self._resolve_dirty():
            return
        picked = self._dir_picker("Create: choose a project directory",
                                  self._plan.get("root") or self._root)
        if not picked:
            self._status("No location picked; nothing was created.")
            return
        target = plan.canonical_root(picked)
        self._pending_action = ("create", target)
        if not self._resolve_dirty():
            self._pending_action = None
            return
        self._pending_action = None
        self._pending_root = target

        def fn(sink, token):
            return plan.init_project(target, token=token, events=sink)

        self._dispatch(fn, kind="init")

    def open_project_dialog(self):
        """Desktop Open: select an existing directory and read it without
        initializing, repairing or calling the provider."""
        if self._busy:
            self._status("An operation is running; Open is disabled until it "
                         "settles.", error=True)
            return
        if not self._resolve_dirty():
            return
        picked = self._dir_picker("Open: choose a project directory",
                                  self._plan.get("root") or self._root)
        if not picked:
            self._status("No location picked; the current project is "
                         "unchanged.")
            return
        target = plan.canonical_root(picked)
        if target == plan.canonical_root(self._root):
            self._plan = plan.project_overview(target)
            self.refresh(force=True)
            self._status("Reopened the current project.")
            return
        self._pending_action = ("open", target)
        if not self._resolve_dirty():
            self._pending_action = None
            return
        self._pending_action = None
        self._pending_root = target

        def fn(sink, token):
            return plan.project_overview(target)

        self._dispatch(fn, kind="open")

    def _rebind_root(self, root):
        """Bind a new project root; clear caches, baselines and planning
        state, then reload the views."""
        self._root = Path(root)
        self._cache = SourceCache()
        self.snap = None
        self._sel_data = None
        self._scene_sel = None
        self._steer = None
        self._batch = None
        self._preview_text = ""
        self._view_override = None
        self._draft_left = False
        self._stale_config = False
        self._plan = plan.project_overview(self._root)
        self._bible_overview = None
        self._bible_session = False
        self._bible_heading = None
        self._bible_baseline = None
        self._bible_preview_section = None
        self._bible_form_loaded = None
        self._bible_text_loaded = None
        self._outline_overview = None
        self._outline_candidates = []
        self._outline_notes_loaded = None
        self._outline_body_loaded = None
        self._scenes_overview = None
        self._scene_cards = None
        self._scenes_card_row = None
        self._scenes_preview_baseline = None
        self._scenes_force_once = False
        self._bind_steering(None)
        self.refresh(force=True)
        self._autoselect()

    def _update_setup_tab(self):
        """Refresh the setup pane from the read-only overview."""
        p = self._plan
        if self._settings_state.get("root") != p["root"] or \
                (not self._settings_touched and
                 not self._settings_state.get("loaded")):
            self._load_settings_form()
            self._settings_state["loaded"] = True
        lines = [f"project: {p['root']}"]
        if not p["exists"]:
            lines.append("The directory does not exist yet. Create "
                         "initializes it with the CLI init contents; "
                         "nothing is created without an explicit Create.")
        elif not p["config_ok"]:
            lines.append("project.json is missing or invalid; setup stays "
                         "usable and nothing is written against bad data. "
                         "Create fills only missing files.")
        else:
            lines.append(f"title: {p['title']}  target words: "
                         f"{p['target_words']}")
            lines.append(f"scenes saved: {p['scenes']}"
                         + (f"  (statuses: {', '.join(p['scene_status'])})"
                            if p["scene_status"] else ""))
            lines.append("outline.md: " + ("present" if p["outline_present"]
                                           else "absent"))
            missing = p["missing_files"]
            if missing:
                lines.append("missing init files: " + ", ".join(missing)
                             + " (Create creates only these)")
        if p["preset_found"]:
            lines.append("writer preset: found")
        else:
            lines.append("writer preset: not found (import one here or "
                         "configure roles.writer.preset in Settings)")
        creds = []
        if p["api_key_env"]:
            creds.append(f"environment {p['api_key_env']}: "
                         + ("set" if p["env_set"] else "not set"))
        creds.append("effective credentials: "
                     + ("available" if p["creds_ok"] else "missing"))
        lines.append("credentials: " + "; ".join(creds)
                     + " (availability only; no key value is shown)")
        for w in p["warnings"]:
            lines.append("warning: " + w)
        self.setup_status.setText("\n".join(lines))

    # ------------------------------------------------------------ preset import

    def import_preset(self):
        """Desktop preset import through the shared validation; no overwrite."""
        if self._busy:
            self._status("An operation is running; import is disabled until "
                         "it settles.", error=True)
            return
        src = self._preset_picker("Import a SillyTavern master-export preset")
        if not src:
            self._status("No preset picked; nothing was written.")
            return
        root = plan.canonical_root(self._root)
        self._import_src = src

        def fn(sink, token):
            return plan.import_preset(root, src, token=token, events=sink)

        self._dispatch(fn, kind="preset_import")

    def _default_dir_picker(self, title, proposed):
        from PySide6.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(self, title,
                                                str(proposed or self._root))
        return path or None

    def _default_preset_picker(self, title):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, title, str(self._root),
                                              "Presets (*.json)")
        return path or None

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
        if force:
            self._plan = plan.project_overview(self._root)
            self._refresh_bible_overview()
            self._refresh_outline_overview()
            self._refresh_scenes_overview()
        self._update_setup_tab()
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
        self._view_override = None   # selection navigation clears view-only text
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
            self._scene_warn = []
        else:
            self._steer = self._steering_state(scene_id)
            try:
                self._scene_warn = list(dop.session_info(
                    self._root, scene_id)["warnings"])
                self._scene_info_scene = scene_id
            except dop.OpError as e:
                self._scene_warn = [str(e)]
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
                        and scene_ok
                        and not self._busy)
        self.save_btn.setEnabled(editable)
        self.clear_btn.setEnabled(editable)
        self._update_draft_actions()
        self._update_steering_label()

    def _update_draft_actions(self):
        """Generate/Stop/Accept availability with recovery guidance."""
        scene_ok = (self._scene_sel is not None
                    and self._scene_sel in self._card_ids()
                    and self._steer is not None and self._steer.editable
                    and self._steer.baseline is not None
                    and not self._stale_config
                    and self._missing_node is None)
        missing = []
        if not self._session.get("preset_found"):
            missing.append("a writer preset (writer_preset.json)")
        if not self._session.get("creds_ok"):
            env = self._session.get("api_key_env") or "the configured key variable"
            missing.append(f"provider credentials (api_key in project.json or export {env}=...)")
        if missing:
            self.generate_note.setText(
                "Generate is unavailable: supply " + " and ".join(missing) + ".")
        elif self._scene_sel is None or not scene_ok:
            self.generate_note.setText(
                "Generate needs a selected scene with a writable card; "
                "select one in the sidebar.")
        else:
            self.generate_note.setText("")
        can_generate = bool(scene_ok and not missing and not self._busy
                            and not self._draft_left)
        self.generate_btn.setEnabled(can_generate)
        self.generate_btn.setToolTip(
            "Generate saves your current steering first, then asks the "
            "provider for candidate passages as siblings of the active head"
            + (("; unavailable: " + "; ".join(missing)) if missing else "")
            + ("; you left the draft loop (Leave draft again to re-enter)"
               if self._draft_left else ""))
        self.stop_btn.setEnabled(self._busy)
        for b in (self.create_btn, self.open_btn, self.preset_import_btn,
                  self.settings_save_btn, self.settings_cancel_btn,
                  self.fetch_limits_btn, self.bible_begin_btn,
                  self.bible_save_btn, self.bible_accept_btn,
                  self.bible_edit_btn, self.bible_skip_btn,
                  self.bible_leave_btn, self.bible_text_edit_btn,
                  self.bible_text_save_btn, self.bible_text_cancel_btn,
                  self.bible_history_btn, self.outline_generate_btn,
                  self.outline_reroll_btn, self.outline_view_btn,
                  self.outline_choose_btn, self.outline_edit_btn,
                  self.outline_save_btn, self.outline_cancel_btn,
                  self.scenes_generate_btn, self.scenes_accept_btn,
                  self.scenes_cancel_btn):
            b.setEnabled(not self._busy)
        has_batch = bool(self._batch and self._batch.get("saved"))
        for b in (self.accept_btn, self.view_btn, self.reroll_btn,
                  self.reroll_all_btn, self.add_btn, self.delete_btn,
                  self.keep_btn, self.discard_btn, self.new_passage_btn,
                  self.edit_head_btn, self.editor_save_btn,
                  self.editor_cancel_btn, self.rewind_btn,
                  self.use_as_head_btn, self.delete_node_btn,
                  self.save_pov_btn, self.save_cast_btn,
                  self.mark_done_btn, self.save_prompt_btn,
                  self.lore_toggle_btn, self.lore_all_on_btn,
                  self.lore_all_off_btn, self.lore_char_btn,
                  self.lore_alias_btn, self.lore_world_btn,
                  self.lore_import_btn):
            b.setEnabled(not self._busy and
                         (has_batch if b in (self.accept_btn, self.view_btn,
                                             self.reroll_btn, self.reroll_all_btn,
                                             self.add_btn, self.delete_btn,
                                             self.keep_btn, self.discard_btn)
                          else self._scene_sel is not None))

    # -------------------------------------------------------------- worker

    def _dispatch(self, fn, kind="generate", rows=None):
        """Start one operation on the worker thread; refuses when busy."""
        if self._busy:
            return False
        self._op_id += 1
        self._op_kind = kind
        self._op_rows = rows
        self._view_override = None
        op_id = self._op_id
        self._token = CancellationToken()
        thread = OpThread(op_id, lambda sink: fn(sink, self._token), parent=self)
        thread.event_sig.connect(self._on_worker_event)
        thread.done_sig.connect(self._on_worker_done)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._busy = True
        self._update_steering_ui()
        self._status(f"Working (operation {op_id})…")
        thread.start()
        return True

    def _on_worker_event(self, op_id, payload):
        """Queued progress event; late payloads of superseded ops are ignored."""
        if op_id != self._op_id or not self._busy:
            return
        kind = payload.get("type")
        if kind == "delta":
            self._preview_text += payload.get("text", "")
            self.preview.setPlainText(self._preview_text)
            bar = self.preview.verticalScrollBar()
            bar.setValue(bar.maximum())
        elif kind == "reset":
            self._preview_text = ""
            self.preview.setPlainText("")
        elif kind == "stream_start":
            self._preview_text = ""
            self.preview.setPlainText("")
            self._status("Streaming… (provisional preview; nothing is saved yet)")
        elif kind in ("candidate_done", "candidate_failed"):
            self._status(payload.get("msg", ""))
        elif kind == "progress":
            self._status(payload.get("msg", ""))
        elif kind == "note":
            self._status("warning: " + payload.get("text", ""))
        elif kind == "shortfall":
            self._status(f"warning: only {payload.get('got')} of "
                         f"{payload.get('wanted')} responses came back")
        elif kind == "skipped_empty":
            self._status("warning: a response cleaned to empty and was discarded")

    def _on_worker_done(self, op_id, outcome, value):
        if op_id != self._op_id:
            return  # a superseded operation settled late
        self._busy = False
        self._thread = None
        if outcome == "ok":
            try:
                self._on_op_ok(value)
            except Exception as e:  # noqa: BLE001 — a settlement bug must
                self._busy = False  # never wedge the window's controls
                self._status(f"settlement error: {type(e).__name__}: {e}",
                             error=True)
            self._update_steering_ui()
        elif outcome == "cancelled":
            self._update_steering_ui()
            self._preview_text = ""
            self.preview.setPlainText("")
            self._status("Stopped; nothing was saved. Head and saved "
                         "branches are unchanged.")
        else:
            self._update_steering_ui()
            self._pending_action = None   # a failed save never continues a
            self._pending_root = None     # deferred transition
            if getattr(value, "collision", False) and \
                    self._op_kind in ("import", "scenes_generate"):
                if self._op_kind == "scenes_generate":
                    pick = self._choice(
                        "Replace drafted scenes?",
                        str(value) + "\n\nConfirming makes the provider call "
                        "and previews replacement candidates; scenes.json "
                        "and every tree file stay unchanged until you accept "
                        "a preview.", ["Generate (force)", "Cancel"])
                    if pick == "Generate (force)":
                        self._scenes_force_once = True
                        self.scenes_generate()
                    else:
                        self._status("Force declined; no request was made "
                                     "and no scene or tree file changed.")
                    return
                self._on_import_collision(value)
                return
            self._status(str(value), error=True)
            if getattr(value, "stale", False):
                self._status(str(value) + " — Reload (Refresh) or retry.",
                             error=True)

    def _on_op_ok(self, value):
        kind = self._op_kind
        if isinstance(value, dop.GenerateResult):
            note = None
            if kind in ("reroll", "add") and self._batch:
                note = self._merge_batch(value)
            else:
                self._batch = {"scene": self._op_scene, "parent": value.parent,
                               "saved": list(value.saved),
                               "streamed": value.streamed}
            self._rebuild_tray()
            if value.over:
                self._status("Generation refused: the prompt is over the "
                             "context ceiling (trim bible/state/lore or lower "
                             "budgets in project.json). No provider call ran.",
                             error=True)
            elif kind == "reroll":
                self.refresh(force=True)
                msg = (f"Rerolled {len(value.saved)} slot(s); originals stay "
                       "saved as branches and the head is unchanged.")
                if note:
                    msg = f"warning: {note}"
                self._status(msg)
            elif kind == "add":
                self.refresh(force=True)
                self._status(
                    f"Added {len(value.saved)} candidate(s) to the batch; "
                    "head is unchanged.")
            elif value.saved:
                self.refresh(force=True)
                self._status(
                    f"{len(value.saved)} candidate(s) saved as branches for "
                    f"{self._op_scene}; head is unchanged. Select one and "
                    "press Accept when ready.")
            else:
                self._status("No complete candidate came back; head and "
                             "saved branches are unchanged.")
        elif kind == "accept" and isinstance(value, dict):
            self._batch = None
            self.tray.clear()
            self._preview_text = ""
            self.preview.setPlainText("")
            self.refresh(force=True)
            msg = f"accepted {value['head']}; head moved, other candidates stay saved branches"
            if value.get("ended"):
                self._status(msg)
                pick = self._choice(
                    "Scene end",
                    "The model signalled scene end. Mark the scene done?\n"
                    "(Declining leaves the post-accept status unchanged.)",
                    ["Mark scene done", "Keep status"])
                if pick == "Mark scene done":
                    self.mark_done()
                else:
                    self._status(msg + " — end suggestion declined; the "
                                 "post-accept status is unchanged")
                return
            self._status(msg)
        elif kind == "delete" and isinstance(value, dict):
            nid = value["deleted"]
            if self._batch and nid in self._batch["saved"]:
                self._batch["saved"].remove(nid)
                if not self._batch["saved"]:
                    self._batch = None
            self._rebuild_tray()
            self.refresh(force=True)
            self._status(f"deleted {nid}" +
                         (f"; head moved to {value['head']}" if value.get("head") is not None else ""))
        elif kind == "scene" and isinstance(value, dict):
            # scene field writes (pov/cast/mark done)
            self._scene_edit_dirty[value["scene"]] = False
            self.refresh(force=True)
            if "hint" in value:
                self._status(value["hint"] + " (continuity update is a later "
                             "separate step, not run here)")
            else:
                self._status("Scene fields saved")
        elif kind == "editor" and isinstance(value, dict):
            self.refresh(force=True)
            if "added" in value:
                self.cancel_editor()
                if value.get("added"):
                    self._status(
                        f"added {value['added']}"
                        + ("; planned became drafting"
                           if value.get("status_changed") else ""))
                else:
                    self._status("empty input: no passage added")
            else:
                if value.get("changed"):
                    self.cancel_editor()
                    self.editor_diff.setText(word_diff(value["old"], value["new"]))
                    self._status(f"edited {value['head']}; old text kept in "
                                 "history")
                else:
                    self._status("no changes (empty or unchanged input)")
        elif kind == "branch" and isinstance(value, dict):
            self.refresh(force=True)
            if "deleted" in value:
                self._status(f"deleted {value['deleted']}"
                             + (f"; head moved to {value['head']}"
                                if value.get("head") is not None else ""))
            else:
                self._status(f"head -> {value.get('head') or '(scene start)'}")
        elif kind == "dump" and isinstance(value, dict):
            self._status(f"wrote {value['path']} (exact prompt bytes; "
                         "no provider call)")
        elif kind in ("lore", "import") and isinstance(value, dict):
            self.refresh(force=True)
            if kind == "import":
                self._status(f"imported {value['imported']} "
                             f"({value['entries']} entries"
                             + (f", character {value['card_name']}"
                                if value.get("card_name") else "")
                             + (", replaced existing file"
                                if value.get("replaced") else "") + ")")
            else:
                self._status("Lorebooks updated")
        elif kind == "init" and isinstance(value, dict):
            root = Path(value["root"])
            created = value["created"] + value["dirs"]
            if self._pending_root is not None and \
                    plan.canonical_root(self._pending_root) == root:
                self._pending_root = None
                self._rebind_root(root)
                msg = "initialized " + root.name + ": " + \
                    (", ".join(created) if created else
                     "(nothing; all files already exist)")
                if value.get("preset"):
                    msg += "; writer_preset.json imported"
                self._status(msg)
            else:
                self.refresh(force=True)
                self._status("initialized " + root.name)
        elif kind == "open" and isinstance(value, dict):
            root = Path(value["root"])
            if self._pending_root is not None and \
                    plan.canonical_root(self._pending_root) == root:
                self._pending_root = None
                if not value["exists"]:
                    self._status("That directory does not exist; the current "
                                 "project is unchanged.", error=True)
                elif not value["config_ok"]:
                    self._status("That directory has no valid project.json; "
                                 "nothing was changed. Use Create there to "
                                 "initialize it.", error=True)
                else:
                    self._rebind_root(root)
                    self._status(f"opened {root.name} (read without "
                                 "initializing or provider calls)")
            else:
                self.refresh(force=True)
        elif kind == "preset_import" and isinstance(value, dict):
            self.refresh(force=True)
            self._status(f"imported {value['imported']} "
                         f"({value['bytes']} bytes copied unchanged); "
                         "readiness refreshed")
        elif kind == "settings_save" and isinstance(value, dict):
            self._load_settings_form()
            self._settings_state["loaded"] = True
            self.refresh(force=True)
            msg = (f"saved {len(value['saved'])} setting(s)"
                   + (f", cleared {len(value['cleared'])}"
                      if value["cleared"] else "") + "; unknown fields and "
                   "any existing key are preserved")
            self._status(msg)
            if self._pending_action is not None:
                self._run_pending_action()
        elif kind == "limits" and isinstance(value, dict):
            self.limits_view.setPlainText(self._limits_text(value["view"]))
            msg = ("limits fetched and saved to limits.json"
                   + (f"; not found: {', '.join(value['not_found'])}"
                      if value["not_found"] else ""))
            self._status(msg)
        elif kind == "bible_begin" and isinstance(value, dict):
            self._bible_session = True
            self._bible_baseline = dict(value.get("baseline") or {})
            self._bible_preview_section = None
            self._bible_preview_is_current = False
            if not self._bible_heading and self._bible_overview and \
                    self._bible_overview.get("sections"):
                self._bible_heading = \
                    self._bible_overview["sections"][0]["heading"]
            self._load_bible_form()
            msg = ("bible session started"
                   + (f"; backed up {value['backup']}" if value.get("backup")
                      else "") + ". Fill the form, Save answers, then Accept.")
            self._status(msg)
        elif kind == "bible_save" and isinstance(value, dict):
            self._bible_form_loaded = self.bible_form_edit.toPlainText()
            self._bible_mode = "form"
            self._bible_preview_section = value["preview"]
            self._bible_preview_is_current = False
            self.bible_preview.setPlainText(value["preview"] or "(empty)")
            self.bible_editor_label.setText(
                f"Preview for {value['heading']} ({value['words']} words) — "
                "bible.md is unchanged until you press Accept section")
            self._status(f"saved answers to {value['form_path']} and input "
                         "history; bible.md unchanged until Accept")
        elif kind == "bible_accept" and isinstance(value, dict):
            self._bible_preview_section = None
            self._bible_preview_is_current = True
            self._refresh_bible_overview()
            self._bible_baseline = self._refresh_bible_baseline()
            self._status(f"accepted {value['heading']} "
                         f"({value['words']} words) into bible.md")
        elif kind == "bible_text_save" and isinstance(value, dict):
            self._refresh_bible_overview()
            self._bible_baseline = self._refresh_bible_baseline()
            self._bible_mode = "form"
            self._load_bible_form()
            self._status(f"saved section text for {value['heading']}")
        elif kind == "outline_generate" and isinstance(value, dict):
            self._outline_candidates += value["candidates"]
            self._refresh_outline_overview()
            self._outline_notes_loaded = self.outline_notes_edit.toPlainText()
            self.outline_list.blockSignals(True)
            self.outline_list.clear()
            for name in (self._outline_overview or {}).get("candidates", []):
                self.outline_list.addItem(QListWidgetItem(name))
            self.outline_list.setCurrentRow(
                max(0, self.outline_list.count() - len(value["candidates"])))
            self.outline_list.blockSignals(False)
            msg = (f"{len(value['candidates'])} outline candidate(s) saved"
                   + (f"; {len(value['warnings'])} warning(s)" if
                      value["warnings"] else "") + "; outline.md unchanged "
                   "until you choose one")
            self._status(msg)
            for w in value["warnings"]:
                self._status("warning: " + w)
        elif kind == "outline_choose" and isinstance(value, dict):
            self._refresh_outline_overview()
            self.outline_body_edit.setReadOnly(True)
            self.outline_body_edit.setPlainText(
                self._outline_overview.get("outline") or "")
            self._status(f"saved {value['source']} to outline.md"
                         + (" (from saved history; it is now bound to the "
                            "current inputs by this explicit choice)"
                            if value.get("from_history") else "")
                         + "; no scene generation runs automatically")
        elif kind == "outline_save_body" and isinstance(value, dict):
            self._refresh_outline_overview()
            self._outline_body_loaded = None
            self.outline_body_edit.setReadOnly(True)
            self.outline_body_edit.setPlainText(
                self._outline_overview.get("outline") or "")
            self._status("saved the edited outline to outline.md (previous "
                         "outline backed up); the candidate file is "
                         "unchanged")
        elif kind == "scenes_generate" and isinstance(value, dict):
            self._scenes_preview_baseline = dict(value.get("baseline") or {})
            if value.get("raw") is not None:
                self._scene_cards = []
                self._rebuild_scenes_preview()
                self.scenes_preview.setPlainText(value["raw"])
                self._status("warning: " + "; ".join(value["warnings"])
                             + f" — raw output saved at outlines/"
                               f"{value['raw_path']}; Regenerate or Cancel")
            else:
                self._scene_cards = list(value["cards"])
                self._rebuild_scenes_preview()
                msg = (f"{len(value['cards'])} scene card(s) previewed; "
                       "scenes.json is unchanged until Accept")
                for w in value["warnings"]:
                    msg += "\nwarning: " + w
                self._status(msg)
        elif kind == "scenes_accept" and isinstance(value, dict):
            self._scene_cards = []
            self._scenes_preview_baseline = None
            self._scenes_card_row = None
            self._rebuild_scenes_preview()
            self.refresh(force=True)
            msg = (f"saved {value['saved']} scene card(s) to scenes.json"
                   + (f"; previous list backed up to {value['backup']}"
                      if value.get("backup") else "")
                   + "; trees were kept and the draft scene list refreshed")
            self._status(msg)

    def _merge_batch(self, value):
        """Reroll replaces only returned slots; add appends returned slots."""
        new = list(value.saved)
        if self._op_kind == "add":
            self._batch["saved"].extend(new)
            return None
        rows = self._op_rows or []
        for i, nid in zip(rows, new):
            self._batch["saved"][i] = nid
        if len(new) < len(rows):
            return (f"only {len(new)} of {len(rows)} rerolls came back; "
                    "the rest keep their old text")
        return None

    def _rebuild_tray(self):
        self.tray.clear()
        batch = self._batch or {}
        for k, nid in enumerate(batch.get("saved", []), 1):
            self.tray.addItem(QListWidgetItem(f"[{k}] {nid}"))

    def _tray_selected(self):
        row = self.tray.currentRow()
        batch = self._batch or {}
        saved = batch.get("saved", [])
        if 0 <= row < len(saved):
            return row
        return None

    def view_candidate(self):
        """Show the selected candidate's full text; never accepts."""
        row = self._tray_selected()
        if row is None:
            self._status("Select a candidate in the tray to view it.")
            return
        nid = self._batch["saved"][row]
        view = self.snap.trees.get(self._batch["scene"]) if self.snap else None
        info = view.nodes.get(nid) if view else None
        if info is None:
            self.refresh(force=True)
            view = self.snap.trees.get(self._batch["scene"]) if self.snap else None
            info = view.nodes.get(nid) if view else None
        if info is None:
            self._status(f"candidate {nid} is not in the saved tree yet; "
                         "press Refresh and try again", error=True)
            return
        self._view_override = (f"candidate {nid} (view only — not accepted)",
                               info.text)
        self._update_panes()
        self._status(f"Viewing candidate {nid} (not accepted; head unchanged)")

    def _generate_slots(self, count, rows=None, kind="reroll"):
        """Reroll/add: siblings of the batch's captured parent, not the
        currently viewed node."""
        if self._busy or not self._batch:
            return
        self._op_scene = self._batch["scene"]

        def fn(sink, token):
            return dop.generate_candidates(
                self._root, self._batch["scene"], count=count,
                parent=self._batch["parent"],
                provider_factory=self._provider_factory, token=token,
                events=sink)

        self._dispatch(fn, kind=kind, rows=rows)

    def reroll_selected(self):
        rows = [self._tray_selected()] if self._tray_selected() is not None else []
        if not rows:
            self._status("Select a candidate in the tray to reroll it.")
            return
        self._generate_slots(len(rows), rows=rows, kind="reroll")

    def reroll_all(self):
        if not self._batch:
            return
        rows = list(range(len(self._batch["saved"])))
        self._generate_slots(len(rows), rows=rows, kind="reroll")

    def add_candidates(self):
        self._generate_slots(self.add_spin.value(), kind="add")

    def delete_candidate(self):
        """Separately labelled Delete leaf: eligible leaves only."""
        if self._busy:
            return
        row = self._tray_selected()
        if row is None:
            self._status("Select a candidate in the tray to delete it.")
            return
        nid = self._batch["saved"][row]
        self._op_scene = self._batch["scene"]

        def fn(sink, token):
            return dop.delete_leaf(self._root, self._batch["scene"], nid,
                                   token=token, events=sink)

        self._dispatch(fn, kind="delete")

    def close_tray(self, label):
        """Keep branches / Discard preview: non-destructive tray close."""
        self._batch = None
        self._rebuild_tray()
        self._preview_text = ""
        self.preview.setPlainText("")
        self._view_override = None
        self._update_panes()
        self._status(f"{label}: tray closed; saved candidates remain in the "
                     "branch tree and the head is unchanged")

    # -------------------------------------------------------- scene/context

    def _update_scene_tab(self):
        """Refresh the read-only card/status; warnings come from the
        session's captured CLI-prologue notes."""
        scene = self._scene_sel
        if scene is None or self.snap is None:
            self.scene_card.setPlainText("")
            self.scene_status.setText("")
            self.scene_warnings.setText("")
            self.pov_edit.setText("")
            self.cast_edit.setText("")
            return
        try:
            card = dop.scene_card(self._root, scene)
            self._scene_warn = list(self._session_scene_warnings())
        except dop.OpError as e:
            self.scene_card.setPlainText(f"(scene sources unreadable: {e})")
            self.scene_status.setText("")
            return
        if self.scene_card.toPlainText() != card["card"]:
            self.scene_card.setPlainText(card["card"])
        self.scene_status.setText(
            f"status: {card['status']}  target: {card['target_words']} words  "
            f"{{{{char}}}} = {card['char']}")
        self.scene_warnings.setText("\n".join(self._scene_warn))
        for edit, value in ((self.pov_edit, card["pov"]),
                            (self.cast_edit, card["cast"])):
            if edit.hasFocus() or (self._scene_edit_dirty.get(scene, False)):
                continue
            if edit.text() != value:
                edit.setText(value)

    def _session_scene_warnings(self):
        """Per-scene warnings (earlier scenes) computed at scene switch."""
        return getattr(self, "_scene_warn", [])
    def save_pov(self):
        self._dispatch_scene_field(lambda sink, token, scene:
                                   dop.set_pov(self._root, scene,
                                               self.pov_edit.text().strip(),
                                               token=token))

    def save_cast(self):
        names = [x.strip() for x in self.cast_edit.text().split(",") if x.strip()]
        self._dispatch_scene_field(lambda sink, token, scene:
                                   dop.set_cast(self._root, scene, names,
                                                token=token))

    def _dispatch_scene_field(self, mkfn):
        if self._busy or self._scene_sel is None:
            return
        scene = self._scene_sel
        self._scene_edit_dirty[scene] = True
        self._op_scene = scene

        def fn(sink, token):
            return mkfn(sink, token, scene)

        self._dispatch(fn, kind="scene")

    def mark_done(self):
        if self._busy or self._scene_sel is None:
            return
        scene = self._scene_sel
        self._op_scene = scene

        def fn(sink, token):
            return dop.mark_done(self._root, scene, token=token)

        self._dispatch(fn, kind="scene")

    def next_unfinished(self):
        """First non-done scene; all-done explains explicit reopening."""
        try:
            rows = dop.scene_overview(self._root)
        except dop.OpError as e:
            self._status(str(e), error=True)
            return
        row = next((r for r in rows if r["status"] != "done"), None)
        if row is None:
            self._status("All scenes are done; select a scene in the sidebar "
                         "to reopen it explicitly (like CLI --scene ID).")
            return
        self.select_item("manuscript", row["id"], None)
        self._status(f"resumed {row['id']} — {row['title'] or '(untitled)'} "
                     f"(status {row['status']})")

    def inspect_context(self):
        """Budget/sampler/lore report for captured inputs; never a call."""
        scene = self._scene_sel
        if scene is None:
            self._status("Select a scene to inspect its context.")
            return
        try:
            prep = dop.prepare_report(self._root, scene,
                                      passage_words=self.length_spin.value())
        except dop.OpError as e:
            self._status(str(e), error=True)
            return
        self.context_view.setPlainText(self._format_report(prep))

    def show_exact_prompt(self):
        scene = self._scene_sel
        if scene is None:
            self._status("Select a scene to see its exact prompt.")
            return
        try:
            prep = dop.prepare_report(self._root, scene,
                                      passage_words=self.length_spin.value())
        except dop.OpError as e:
            self._status(str(e), error=True)
            return
        self.context_view.setPlainText(prep["prompt"])

    def save_last_prompt(self):
        """Exact prompt bytes to last_prompt.txt through the serial boundary."""
        scene = self._scene_sel
        if scene is None or self._busy:
            return
        self._op_scene = scene

        def fn(sink, token):
            return dop.dump_prompt(self._root, scene,
                                   passage_words=self.length_spin.value())

        self._dispatch(fn, kind="dump")

    @staticmethod
    def _format_report(prep):
        import json
        r = prep["report"]
        lines = [f"context estimate (chars/token {r['ratio']}):"]
        for k, v in r["parts"].items():
            lines.append(f"  {k:<12} ~{v}")
        lines.append(f"  {'TOTAL':<12} ~{r['total']}  (+{r['max_tokens']} "
                     f"completion; ceiling {r['ceiling']} from {r['ceiling_source']})")
        lines.append(f"  {{{{char}}}} = {r['char']}   {{{{user}}}} = {r['user']}   "
                     f"mode = {'continue' if r['continuing'] else 'scene start'}")
        lines.append("  samplers: " + json.dumps(prep["params"])
                     + (f"   + {json.dumps(prep['extra'])}" if prep["extra"] else ""))
        if r["lore"]:
            lines.append("  lore injected:")
            lines += ["    " + ln for ln in r["lore"]]
        else:
            lines.append("  lore injected: (none)")
        lines += [f"  note: {n}" for n in r["notes"]]
        if r["over"]:
            lines.append("  OVER the context ceiling: trim the bible/state/"
                         "lore or lower budgets in project.json")
        return "\n".join(lines)

    # ------------------------------------------------------- draft actions

    def generate(self):
        """Generate candidates for the selected scene; saves steering first."""
        scene = self._scene_sel
        if scene is None or self._busy:
            return
        if self.dirty():
            if not self._persist(self.steer_editor.toPlainText()):
                return  # status already explains; no provider request starts
        self._op_scene = scene

        def fn(sink, token):
            return dop.generate_candidates(
                self._root, scene, count=self.count_spin.value(),
                passage_words=self.length_spin.value(),
                provider_factory=self._provider_factory, token=token,
                events=sink)

        self._dispatch(fn)

    def accept_candidate(self):
        """Accept the tray-selected candidate; never implicit."""
        if self._busy:
            return
        batch = self._batch
        if not batch or not batch.get("saved"):
            self._status("No completed candidate to accept.", error=True)
            return
        row = self.tray.currentRow()
        nid = batch["saved"][row if 0 <= row < len(batch["saved"]) else 0]
        self._op_scene = batch["scene"]

        def fn(sink, token):
            return dop.accept_candidate(self._root, batch["scene"], nid,
                                        token=token, events=sink)

        self._dispatch(fn, kind="accept")

    def stop(self):
        """Cooperative Stop: the token is observed at request/chunk/save
        boundaries; repeated Stop is safe."""
        if self._busy:
            self._token.cancel()
            self._status("Stopping — waiting for the active request to "
                         "settle (bounded by its configured timeout)…")

    def _wait_for_settlement(self):
        """Pump GUI events until the worker settles (never a blocking join,
        never a thread kill). Bounded loop; the operation itself is bounded by
        the configured request timeouts."""
        guard = 0
        while self._busy and guard < 200000:
            QApplication.processEvents()
            guard += 1

    def _reading_text(self):
        kind, tree_id, node_id = self._sel_data or (None, None, None)
        if self.snap is None:
            return ""
        if self._view_override is not None:
            return self._view_override[1]
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
        if self._busy:
            self._status("An operation is running; steering writes are paused "
                         "until it settles.", error=True)
            return False
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
        self._update_scene_tab()
        self._lore_refresh()
        self._update_setup_tab()
        self._update_bible_tab()
        self._update_outline_tab()
        self._update_scenes_tab()
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
        if self._busy:
            pick = self._choice(
                "Operation running",
                "A draft operation is running on the worker.\n\n"
                "Stop and wait requests a cooperative Stop and closes only "
                "after the worker settles. Keep open leaves the window and "
                "the job running.",
                ["Stop and wait", "Keep open"])
            if pick != "Stop and wait":
                ev.ignore()
                self._status("Kept open; the operation continues. Close again "
                             "to Stop and wait.")
                return
            self._token.cancel()
            self._status("Stopping — waiting for the operation to settle…")
            self._wait_for_settlement()
            if self._busy:
                ev.ignore()
                return
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
