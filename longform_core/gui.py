"""GUI startup: explicit native Wayland policy and lazy Qt loading.

Importing this module must not import PySide6/Tk or require a display; the Qt
widgets live in longform_core.gui_window and are imported only inside
run_cli(). All diagnostics are actionable and sanitized: no credentials,
project configuration, or raw tracebacks.
"""

import os
import shlex
import sys

REQUIRED_PLATFORM = "wayland"


def launch_command():
    """The command that starts this GUI, for recovery guidance.

    Source runs keep the documented uv invocation; a frozen executable must
    point at the copied binary itself (absolute, shell-quoted), because the
    frozen user has no Python, uv or checkout.
    """
    if getattr(sys, "frozen", False):
        return shlex.quote(sys.executable or "longform")
    return "uv run --script longform.py"


def launch_advice():
    """Complete native-Wayland launch guidance for the current mode."""
    return f"QT_QPA_PLATFORM={REQUIRED_PLATFORM} {launch_command()} gui DIR"


def missing_runtime_message():
    if getattr(sys, "frozen", False):
        return ("gui: the GUI runtime (PySide6) is unavailable in this executable. "
                "Re-copy or rebuild the executable, then run: " + launch_advice())
    return ("gui: the GUI runtime (PySide6) is unavailable. "
            "Provision the declared dependency with: " + launch_advice())


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
            f"Run: {launch_advice()}")
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
        print(f"{missing_runtime_message()} ({type(e).__name__}: {e})",
              file=sys.stderr, flush=True)
        return 1
    try:
        return gui_window.run(dir_path)
    except Exception as e:  # keep diagnostics concise; no raw traceback
        print(f"gui: startup failed ({type(e).__name__}: {e})",
              file=sys.stderr, flush=True)
        print("gui: check the Wayland session/socket and Qt Wayland/system "
              f"libraries, then run: {launch_advice()}", file=sys.stderr, flush=True)
        return 1
