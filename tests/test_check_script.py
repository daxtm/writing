"""Contract tests for the unchanged scripts/check.sh, using fake python3/uv executables."""

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check.sh"

EXPECTED_ORDER = [
    "python3 -m py_compile longform.py",
    "uv run --script longform.py --help",
    "bash scripts/build-standalone.sh",
    "uv run --with pytest --with httpx pytest -q tests/test_standalone.py",
    "uv run --with pytest --with httpx pytest -q tests --ignore=tests/test_standalone.py",
]


@pytest.fixture
def tmp_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts" / "check.sh")
    (repo / "longform.py").write_text("# dummy source file\n", encoding="utf-8")
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
            case "$*" in
              *--ignore*) exit ${FAKE_PYTEST_EXIT:-0} ;;
              *test_standalone.py*) exit ${FAKE_STANDALONE_EXIT:-0} ;;
              *pytest*) exit ${FAKE_PYTEST_EXIT:-0} ;;
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


def test_check_script_command_order_and_success(tmp_repo, tmp_path):
    r = run_script(tmp_repo, tmp_path, with_uv=True)
    assert r.returncode == 0, r.stderr
    assert log_lines(tmp_repo) == EXPECTED_ORDER
    assert r.stdout == "== syntax\n== cli smoke\n== standalone\n== tests\n"


def test_check_script_failing_pytest_propagates(tmp_repo, tmp_path):
    r = run_script(tmp_repo, tmp_path, with_uv=True, extra_env={"FAKE_PYTEST_EXIT": "3"})
    assert r.returncode == 3
    assert log_lines(tmp_repo) == EXPECTED_ORDER
    assert "== tests" in r.stdout


def test_check_script_failing_frozen_tests_fail_checks(tmp_repo, tmp_path):
    r = run_script(tmp_repo, tmp_path, with_uv=True, extra_env={"FAKE_STANDALONE_EXIT": "5"})
    assert r.returncode == 5
    assert log_lines(tmp_repo) == EXPECTED_ORDER[:4]
    assert "== standalone" in r.stdout
    assert "== tests" not in r.stdout


def test_check_script_failing_build_fails_checks(tmp_repo, tmp_path):
    r = run_script(tmp_repo, tmp_path, with_uv=True, extra_env={"FAKE_BUILD_EXIT": "7"})
    assert r.returncode == 7
    assert log_lines(tmp_repo) == EXPECTED_ORDER[:3]
    assert "== standalone" in r.stdout
    assert "== tests" not in r.stdout


def test_check_script_missing_build_script_fails_checks(tmp_repo, tmp_path):
    (tmp_repo / "scripts" / "build-standalone.sh").unlink()
    r = run_script(tmp_repo, tmp_path, with_uv=True)
    assert r.returncode != 0
    assert log_lines(tmp_repo) == EXPECTED_ORDER[:2]
    assert "== standalone" in r.stdout
    assert "== tests" not in r.stdout


def test_check_script_missing_uv_with_tests_is_error(tmp_repo, tmp_path):
    r = run_script(tmp_repo, tmp_path, with_uv=False)
    assert r.returncode == 1
    assert "tests/ exists but uv is unavailable" in r.stderr
    assert log_lines(tmp_repo) == ["python3 -m py_compile longform.py"]


def test_check_script_missing_uv_without_tests_skips(tmp_repo, tmp_path):
    (tmp_repo / "tests").rmdir()
    r = run_script(tmp_repo, tmp_path, with_uv=False)
    assert r.returncode == 0
    assert "no tests/ yet" in r.stderr or "no tests/ yet" in r.stdout
    assert log_lines(tmp_repo) == ["python3 -m py_compile longform.py"]
