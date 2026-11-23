"""GUI startup: explicit native Wayland policy and lazy Qt loading.

Importing this module must not import PySide6/Tk or require a display; the Qt
widgets live in longform_core.gui_window and are imported only inside
run_cli(). All diagnostics are actionable and sanitized: no credentials,
project configuration, or raw tracebacks.
"""

import os
import sys

REQUIRED_PLATFORM = "wayland"

MISSING_RUNTIME = ("gui: the GUI runtime (PySide6) is unavailable. "
                   "Provision the declared dependency with: "
                   "uv run --script longform.py gui DIR")

FALLBACK_ADVICE = (f"Run: QT_QPA_PLATFORM={REQUIRED_PLATFORM} "
                   "uv run --script longform.py gui DIR")


class GuiLaunchError(Exception):
    """Sanitized, actionable launch failure; never carries project data."""


def resolve_platform(env=None):
    """Apply the platform policy and return the required platform name.

    Unset (or empty) QT_QPA_PLATFORM means Wayland: os.environ is set so the
    Qt platform plugin cannot silently pick something else. If set, exactly
    'wayland' is accepted; anything else (including fallback lists such as
    'wayland,xcb' or 'offscreen') is refused before Qt is ever loaded.
    """
    value = os.environ.get("QT_QPA_PLATFORM") if env is None else env
    if value is None or value == "":
        os.environ["QT_QPA_PLATFORM"] = REQUIRED_PLATFORM
        return REQUIRED_PLATFORM
    if value != REQUIRED_PLATFORM:
        raise GuiLaunchError(
            f"gui requires native Wayland; QT_QPA_PLATFORM='{value}' is not "
            f"supported here (no XWayland/offscreen fallback window). "
            f"{FALLBACK_ADVICE}")
    return value


def run_cli(dir_path):
    """CLI entry for `gui DIR`; returns a process exit code, never raises."""
    try:
        resolve_platform()
    except GuiLaunchError as e:
        print(f"gui: {e}", file=sys.stderr, flush=True)
        return 1
    try:
        from . import gui_window
    except ImportError as e:
        print(f"{MISSING_RUNTIME} ({type(e).__name__}: {e})",
              file=sys.stderr, flush=True)
        return 1
    try:
        return gui_window.run(dir_path)
    except Exception as e:  # keep diagnostics concise; no raw traceback
        print(f"gui: startup failed ({type(e).__name__}: {e})",
              file=sys.stderr, flush=True)
        print("gui: check the Wayland session/socket and Qt Wayland/system "
              f"libraries, then {FALLBACK_ADVICE}", file=sys.stderr, flush=True)
        return 1
