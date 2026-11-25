"""Contract tests for scripts/check.sh, using fake python3/uv executables.

The check entry point owns the shared CPython minor policy (ADR-0013): the
root `.python-version` pin is the single authority, patch updates inside the
pinned minor are accepted automatically, and every phase runs on an explicitly
selected managed CPython 3.13.x regardless of host Python, active environments
or a conflicting `UV_PYTHON`.
"""

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check.sh"

REQUEST = "cpython@3.13"

# The fake uv logs "$*" unquoted, so each expected entry is a command prefix
# (the isolated preflight interpreter query continues on the same log line).
EXPECTED_ORDER = [
    "uv python install --upgrade cpython@3.13",
    "uv run --no-project --python cpython@3.13 --managed-python python -c",
    "uv run --no-project --python cpython@3.13 --managed-python python -m py_compile longform.py",
    "uv run --python cpython@3.13 --managed-python --script longform.py --help",
    "bash scripts/build-standalone.sh",
    "uv run --no-project --python cpython@3.13 --managed-python --with pytest --with httpx pytest -q tests/test_standalone.py",
    # the fake uv logs "$*" without shell quoting; the real command quotes the
    # version range: uv run ... --with 'pyside6>=6.12.0,<6.13' pytest -q tests --ignore=tests/test_standalone.py
    "uv run --no-project --python cpython@3.13 --managed-python --with pytest --with httpx --with pyside6>=6.12.0,<6.13 pytest -q tests --ignore=tests/test_standalone.py",
]

EXPECTED_STDOUT = (
    "== python: CPython 3.13.15\n== syntax\n== cli smoke\n== standalone\n== tests\n"
)


@pytest.fixture
def tmp_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts" / "check.sh")
    (repo / "longform.py").write_text("# dummy source file\n", encoding="utf-8")
    (repo / ".python-version").write_text("cpython@3.13\n", encoding="utf-8")
    (repo / "tests").mkdir()
    fake_build = repo / "scripts" / "build-standalone.sh"
    fake_build.write_text(textwrap.dedent('''\
        #!/usr/bin/env bash
        echo "bash scripts/build-standalone.sh" >> "$FAKE_LOG"
        exit ${FAKE_BUILD_EXIT:-0}
    '''), encoding="utf-8")
    fake_build.chmod(0o755)
    return repo


def make_fake(tmp_path, name, body):
    d = tmp_path / f"fake-{name}"
    d.mkdir()
    exe = d / name
    exe.write_text(textwrap.dedent(body), encoding="utf-8")
    exe.chmod(0o755)
    return d


def run_script(tmp_repo, tmp_path, with_uv=True, extra_env=None):
    fake_py = make_fake(tmp_path, "python3", '''\
        echo "python3 $*" >> "$FAKE_LOG"
    ''')
    parts = [str(fake_py)]
    if with_uv:
        fake_uv = make_fake(tmp_path, "uv", '''\
            echo "uv $*" >> "$FAKE_LOG"
            if [[ "$*" == *"python -c"* ]]; then
              echo "${FAKE_PY_IMPL:-CPython} ${FAKE_PY_VERSION:-3.13.15}"
            fi
            case "$*" in
              *--ignore*) exit ${FAKE_PYTEST_EXIT:-0} ;;
              *test_standalone.py*) exit ${FAKE_STANDALONE_EXIT:-0} ;;
              *pytest*) exit ${FAKE_PYTEST_EXIT:-0} ;;
              *"python install"*) exit ${FAKE_INSTALL_EXIT:-0} ;;
              *) exit ${FAKE_UV_EXIT:-0} ;;
            esac
        ''')
        parts.append(str(fake_uv))
    env = dict(os.environ)
    env["FAKE_LOG"] = str(tmp_repo / "log")
    env["PATH"] = os.pathsep.join(parts + ["/usr/bin", "/bin"])
    env.update(extra_env or {})
    return subprocess.run(["bash", str(tmp_repo / "scripts" / "check.sh")],
                          capture_output=True, text=True, env=env, timeout=120)


def log_lines(tmp_repo):
    return (tmp_repo / "log").read_text(encoding="utf-8").splitlines()


def assert_logged_commands(tmp_repo, expected):
    lines = log_lines(tmp_repo)
    assert len(lines) == len(expected), lines
    for line, exp in zip(lines, expected):
        assert line.startswith(exp), (line, exp)


def test_check_script_command_order_and_success(tmp_repo, tmp_path):
    r = run_script(tmp_repo, tmp_path, with_uv=True)
    assert r.returncode == 0, r.stderr
    assert_logged_commands(tmp_repo, EXPECTED_ORDER)
    assert r.stdout == EXPECTED_STDOUT


def test_check_script_provisions_latest_313_patch_automatically(tmp_repo, tmp_path):
    """Latest-available-patch policy: the check entry point provisions the
    requested minor with `uv python install --upgrade` (never a fixed patch)
    and never edits the pin or launcher metadata to take a newer patch."""
    r = run_script(tmp_repo, tmp_path, with_uv=True)
    assert r.returncode == 0, r.stderr
    lines = log_lines(tmp_repo)
    assert lines[0] == "uv python install --upgrade cpython@3.13"
    assert "--upgrade" in lines[0], "minor request alone may reuse an old patch"
    assert "3.13.15" not in lines[0], "no patch value may be baked into the request"
    assert (tmp_repo / ".python-version").read_text(encoding="utf-8") == "cpython@3.13\n"


@pytest.mark.parametrize("reported", ["3.13.9", "3.13.15"])
def test_check_script_accepts_different_313_patches(tmp_repo, tmp_path, reported):
    """Different allowed 3.13 patches are accepted without policy edits; the
    reported line always shows the actual full version, never a placeholder."""
    r = run_script(tmp_repo, tmp_path, with_uv=True, extra_env={"FAKE_PY_VERSION": reported})
    assert r.returncode == 0, r.stderr
    assert f"== python: CPython {reported}" in r.stdout
    assert "== syntax" in r.stdout and "== tests" in r.stdout


def test_check_script_selects_explicit_request_despite_host_env(tmp_repo, tmp_path):
    """Host Python, active environments and a conflicting UV_PYTHON must not
    change the selected implementation/minor: every phase carries the explicit
    managed CPython 3.13 request and no bare python3 is invoked."""
    r = run_script(tmp_repo, tmp_path, with_uv=True, extra_env={"UV_PYTHON": "3.12"})
    assert r.returncode == 0, r.stderr
    assert r.stdout == EXPECTED_STDOUT
    for line in log_lines(tmp_repo):
        if line.startswith("uv run"):
            assert "--python cpython@3.13" in line, line
            assert "--managed-python" in line, line
        else:
            assert not line.startswith("python3"), line


def test_check_script_rejects_other_implementation(tmp_repo, tmp_path):
    r = run_script(tmp_repo, tmp_path, with_uv=True, extra_env={"FAKE_PY_IMPL": "PyPy"})
    assert r.returncode != 0
    blob = r.stdout + r.stderr
    assert "PyPy" in blob and "cpython@3.13" in blob
    assert "== python:" not in r.stdout
    assert "== syntax" not in r.stdout


def test_check_script_rejects_wrong_minor(tmp_repo, tmp_path):
    r = run_script(tmp_repo, tmp_path, with_uv=True, extra_env={"FAKE_PY_VERSION": "3.12.14"})
    assert r.returncode != 0
    blob = r.stdout + r.stderr
    assert "cpython@3.13" in blob
    assert "== python:" not in r.stdout
    assert "== syntax" not in r.stdout


@pytest.mark.parametrize("pin", [
    "",
    "3.13",
    "cpython@3.13.15",  # patch-specific: patches must stay automatic
    "cpython@3.12",
    "cpython@3.14",
    "pypy@3.13",
    "cpython@3.13+freethreaded",
    "cpython@3.13\n3.13",
    " cpython@3.13",
])
def test_check_script_rejects_missing_or_malformed_pins(tmp_repo, tmp_path, pin):
    (tmp_repo / ".python-version").write_text(pin, encoding="utf-8")
    r = run_script(tmp_repo, tmp_path, with_uv=True)
    assert r.returncode != 0
    blob = r.stdout + r.stderr
    assert ".python-version" in blob, blob
    assert "== python:" not in r.stdout
    assert "== syntax" not in r.stdout
    assert log_lines(tmp_repo) == [], "no command may run on an invalid pin"


def test_check_script_missing_pin_fails(tmp_repo, tmp_path):
    (tmp_repo / ".python-version").unlink()
    r = run_script(tmp_repo, tmp_path, with_uv=True)
    assert r.returncode != 0
    assert ".python-version" in (r.stdout + r.stderr)
    assert log_lines(tmp_repo) == []


def test_check_script_provisioning_failure_propagates(tmp_repo, tmp_path):
    """An unprovisionable requested minor fails before syntax compilation or
    any suite can pass on a fallback interpreter."""
    r = run_script(tmp_repo, tmp_path, with_uv=True, extra_env={"FAKE_INSTALL_EXIT": "1"})
    assert r.returncode != 0
    assert "cpython@3.13" in (r.stdout + r.stderr)
    assert "== python:" not in r.stdout
    assert log_lines(tmp_repo) == ["uv python install --upgrade cpython@3.13"]


def test_check_script_failing_pytest_propagates(tmp_repo, tmp_path):
    r = run_script(tmp_repo, tmp_path, with_uv=True, extra_env={"FAKE_PYTEST_EXIT": "3"})
    assert r.returncode == 3
    assert_logged_commands(tmp_repo, EXPECTED_ORDER)
    assert "== tests" in r.stdout


def test_check_script_failing_frozen_tests_fail_checks(tmp_repo, tmp_path):
    r = run_script(tmp_repo, tmp_path, with_uv=True, extra_env={"FAKE_STANDALONE_EXIT": "5"})
    assert r.returncode == 5
    assert_logged_commands(tmp_repo, EXPECTED_ORDER[:5])
    assert "== standalone" in r.stdout
    assert "== tests" not in r.stdout


def test_check_script_failing_build_fails_checks(tmp_repo, tmp_path):
    r = run_script(tmp_repo, tmp_path, with_uv=True, extra_env={"FAKE_BUILD_EXIT": "7"})
    assert r.returncode == 7
    assert_logged_commands(tmp_repo, EXPECTED_ORDER[:4])
    assert "== standalone" in r.stdout
    assert "== tests" not in r.stdout


def test_check_script_missing_build_script_fails_checks(tmp_repo, tmp_path):
    (tmp_repo / "scripts" / "build-standalone.sh").unlink()
    r = run_script(tmp_repo, tmp_path, with_uv=True)
    assert r.returncode != 0
    assert_logged_commands(tmp_repo, EXPECTED_ORDER[:3])
    assert "== standalone" in r.stdout
    assert "== tests" not in r.stdout


def test_check_script_missing_uv_with_tests_is_error(tmp_repo, tmp_path):
    r = run_script(tmp_repo, tmp_path, with_uv=False)
    assert r.returncode != 0
    blob = r.stdout + r.stderr
    assert "uv not found" in blob
    assert "== syntax" not in blob, "syntax must not run on a fallback interpreter"
    assert log_lines(tmp_repo) == []


def test_check_script_missing_uv_without_tests_is_error(tmp_repo, tmp_path):
    (tmp_repo / "tests").rmdir()
    r = run_script(tmp_repo, tmp_path, with_uv=False)
    assert r.returncode != 0
    blob = r.stdout + r.stderr
    assert "uv not found" in blob
    assert log_lines(tmp_repo) == []


FROZEN_GUI_TESTS = (
    "test_copied_binary_runs_help_without_python_uv_or_checkout",
    "test_copied_binary_headless_cli_without_display_variables",
    "test_copied_binary_with_no_arguments_launches_gui",
    "test_archive_contains_gui_application_modules",
    "test_archive_contains_qt_runtime_and_wayland_plugins",
    "test_frozen_gui_refuses_platforms_before_qt",
    "test_frozen_gui_missing_wayland_socket_gives_standalone_advice",
)


def test_real_check_script_runs_mandatory_frozen_gui_coverage():
    """The real check entry point builds once and runs the frozen GUI tests;
    those tests contain no skip path, so missing build/Qt/compiler
    dependencies fail the checks instead of passing silently."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "bash scripts/build-standalone.sh" in script
    assert "pytest -q tests/test_standalone.py" in script
    frozen = (REPO / "tests" / "test_standalone.py").read_text(encoding="utf-8")
    for name in FROZEN_GUI_TESTS:
        assert f"def {name}" in frozen, f"{name} disappeared from frozen coverage"
    assert "pytest.mark.skip" not in frozen
    assert "pytest.skip(" not in frozen
    assert "pytest.importorskip" not in frozen


def test_real_check_script_enforces_minor_policy():
    """The real check entry point reads the authoritative pin, provisions the
    requested minor with --upgrade, prints the verified version before the
    phase markers, selects it explicitly for every phase, and never invokes a
    bare host python3."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert ".python-version" in script, "the pin file is the interpreter authority"
    assert "uv python install --upgrade" in script
    assert 'echo "== python: ' in script, "verified version must be reported"
    assert "python3 -m py_compile" not in script, "bare host python3 must not be used"
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("uv run"):
            assert "--python" in stripped, f"explicit request missing: {stripped}"
            assert "--managed-python" in stripped, f"managed selection missing: {stripped}"
