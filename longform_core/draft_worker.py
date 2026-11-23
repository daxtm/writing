"""One background worker per operation (ADR-0007).

Plain Qt threading with no business logic: the operation callable runs on the
worker thread; progress events and the terminal outcome are queued (automatic
for cross-thread signal/slot connections) and carry the operation id so GUI
slots can ignore late payloads from superseded operations. Cancellation is
cooperative via the shared token — no thread is ever killed.
"""

from PySide6.QtCore import QThread, Signal

from .cancel import Cancelled
from .draft_operations import OpError
from .utils import FatalError


class OpThread(QThread):
    """Runs one `fn(sink, token)` on its own thread.

    Signals: `event_sig(op_id, payload)` for typed progress events and
    `done_sig(op_id, outcome, value)` exactly once, with outcome "ok",
    "cancelled" or "error" (value is an OpError for "error").
    """

    event_sig = Signal(int, dict)
    done_sig = Signal(int, str, object)

    def __init__(self, op_id, fn, parent=None):
        super().__init__(parent)
        self._op_id = op_id
        self._fn = fn

    def run(self):
        op_id = self._op_id
        sink = lambda payload: self.event_sig.emit(op_id, dict(payload))
        try:
            value = self._fn(sink)
            self.done_sig.emit(op_id, "ok", value)
        except Cancelled:
            self.done_sig.emit(op_id, "cancelled", None)
        except OpError as e:
            self.done_sig.emit(op_id, "error", e)
        except FatalError as e:
            self.done_sig.emit(op_id, "error", OpError(str(e.msg)))
        except Exception as e:  # noqa: BLE001 — the GUI needs a readable failure, never a dead thread
            self.done_sig.emit(op_id, "error", OpError(f"{type(e).__name__}: {e}"))
