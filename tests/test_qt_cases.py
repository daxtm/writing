"""Run tests/qt_widget_cases.py in an isolated subprocess, offscreen.

The child case file is a plain script, so pytest never collects it twice in the
parent. A missing GUI runtime or any failing widget case fails this wrapper
with a diagnostic; widget coverage is never skipped.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_qt_widget_cases_run_offscreen(net_guard_env):
    """Every offscreen case executes; missing Qt or a child failure is nonzero."""
    env = dict(net_guard_env)
    env["QT_QPA_PLATFORM"] = "offscreen"
    r = subprocess.run(
        [sys.executable, str(REPO / "tests" / "qt_widget_cases.py")],
        capture_output=True, text=True, env=env, timeout=300, cwd=str(REPO))
    assert r.returncode == 0, f"offscreen Qt cases failed\n{r.stdout}\n{r.stderr}"
    assert "FAIL" not in r.stdout


def test_qt_presentation_case_at_scale_2(net_guard_env):
    """The presentation case also passes in a 200%-scale offscreen run:
    scrollable/larger layouts must not clip into unusable widgets."""
    env = dict(net_guard_env)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["QT_SCALE_FACTOR"] = "2"
    r = subprocess.run(
        [sys.executable, str(REPO / "tests" / "qt_widget_cases.py"),
         "case_workflow_presentation"],
        capture_output=True, text=True, env=env, timeout=300, cwd=str(REPO))
    assert r.returncode == 0, \
        f"scale-2 presentation case failed\n{r.stdout}\n{r.stderr}"
    assert "FAIL" not in r.stdout
