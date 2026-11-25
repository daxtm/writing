"""Standalone-executable acceptance tests.

These tests exercise the *production* artifact built by scripts/build-standalone.sh
(never a development wrapper): the executable is copied alone into a temporary
directory with spaces and run by absolute path from an unrelated working
directory with Python/uv and the source checkout absent from its environment.

The whole session is network-guarded at the native level: an LD_PRELOAD guard
compiled with cc denies Internet socket creation/connection, datagram sends and
hostname resolution for the frozen bootloader, interpreter and every child
process, and a small native challenge probe proves the denial without Python on
PATH. Source-side monkeypatch/sitecustomize guards (tests/conftest.py) are kept
and still cover the source CLI parity runs.

Missing compiler, missing guard or a failed build fails explicitly -- coverage
is never skipped.
"""

import json
import hashlib
import os
import re
import shutil
import subprocess
import sys
import textwrap
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPO / "scripts" / "build-standalone.sh"
BINARY_NAME = "longform"

# Recognizable stderr marker emitted by the native guard on every denied call.
NET_DENIAL_MARKER = "LONGFORM-NETWORK-DENIED"

CREDENTIAL_VARS = ("FEATHERLESS_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
TRUST_VARS = ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "SSL_CERT_DIR", "CURL_CA_BUNDLE")
DISPLAY_VARS = ("DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET", "QT_QPA_PLATFORM")
PYTHON_VARS = ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONOPTIMIZE",
               "PYTHONWARNINGS", "PYTHONUSERBASE", "PYTHONNOUSERSITE", "PYTHONUNBUFFERED")

# ---------------------------------------------------------------------------
# Native network guard (test-only). Interposed functions deny Internet traffic
# before it reaches the network and print the marker to stderr. LD_PRELOAD is
# inherited by children, so the guard also covers them.
# ---------------------------------------------------------------------------

NETGUARD_C = r"""
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <netdb.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>
#include <arpa/inet.h>

static void deny(const char *op) {
    fprintf(stderr, "LONGFORM-NETWORK-DENIED op=%s\n", op);
}

static int internet_family(const struct sockaddr *addr, socklen_t len) {
    if (!addr || len < sizeof(sa_family_t)) return 0;
    return addr->sa_family == AF_INET || addr->sa_family == AF_INET6;
}

int socket(int domain, int type, int protocol) {
    if (domain == AF_INET || domain == AF_INET6) {
        deny("socket");
        errno = EPERM;
        return -1;
    }
    static int (*real_sym)(int, int, int);
    if (!real_sym) real_sym = (int (*)(int, int, int))dlsym(RTLD_NEXT, "socket");
    return real_sym(domain, type, protocol);
}

int connect(int fd, const struct sockaddr *addr, socklen_t len) {
    if (internet_family(addr, len)) {
        deny("connect");
        errno = EPERM;
        return -1;
    }
    static int (*real_sym)(int, const struct sockaddr *, socklen_t);
    if (!real_sym) real_sym = (int (*)(int, const struct sockaddr *, socklen_t))dlsym(RTLD_NEXT, "connect");
    return real_sym(fd, addr, len);
}

ssize_t sendto(int fd, const void *buf, size_t n, int flags,
               const struct sockaddr *addr, socklen_t alen) {
    if (internet_family(addr, alen)) {
        deny("sendto");
        errno = EPERM;
        return -1;
    }
    static ssize_t (*real_sym)(int, const void *, size_t, int, const struct sockaddr *, socklen_t);
    if (!real_sym) real_sym = (ssize_t (*)(int, const void *, size_t, int, const struct sockaddr *, socklen_t))
        dlsym(RTLD_NEXT, "sendto");
    return real_sym(fd, buf, n, flags, addr, alen);
}

int getaddrinfo(const char *node, const char *service,
                const struct addrinfo *hints, struct addrinfo **res) {
    deny("getaddrinfo");
    (void)node; (void)service; (void)hints; (void)res;
    return EAI_FAIL;
}

struct hostent *gethostbyname(const char *name) {
    deny("gethostbyname");
    (void)name;
    h_errno = HOST_NOT_FOUND;
    return NULL;
}

struct hostent *gethostbyname2(const char *name, int af) {
    deny("gethostbyname2");
    (void)name; (void)af;
    h_errno = HOST_NOT_FOUND;
    return NULL;
}
"""

# ---------------------------------------------------------------------------
# Native challenge probe (test-only). Tries every guarded operation and exits 0
# only when each one was denied -- without Python on PATH.
# ---------------------------------------------------------------------------

PROBE_C = r"""
#include <arpa/inet.h>
#include <errno.h>
#include <netdb.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

int main(void) {
    int failures = 0;
    int s = socket(AF_INET, SOCK_STREAM, 0);
    if (s >= 0) {
        fprintf(stderr, "probe: socket(AF_INET) unexpectedly succeeded\n");
        failures++;
        close(s);
    } else {
        fprintf(stderr, "probe: socket(AF_INET) denied with errno=%d\n", errno);
    }
    int u = socket(AF_UNIX, SOCK_STREAM, 0);
    if (u >= 0) {
        struct sockaddr_in a;
        memset(&a, 0, sizeof a);
        a.sin_family = AF_INET;
        a.sin_port = htons(80);
        a.sin_addr.s_addr = inet_addr("192.0.2.1"); /* TEST-NET-1, never routed */
        if (connect(u, (struct sockaddr *)&a, sizeof a) == 0) {
            fprintf(stderr, "probe: connect(AF_INET) unexpectedly succeeded\n");
            failures++;
        } else {
            fprintf(stderr, "probe: connect(AF_INET) denied with errno=%d\n", errno);
        }
        struct sockaddr_in d;
        memcpy(&d, &a, sizeof d);
        if (sendto(u, "x", 1, 0, (struct sockaddr *)&d, sizeof d) >= 0) {
            fprintf(stderr, "probe: sendto(AF_INET) unexpectedly succeeded\n");
            failures++;
        } else {
            fprintf(stderr, "probe: sendto(AF_INET) denied with errno=%d\n", errno);
        }
        close(u);
    } else {
        fprintf(stderr, "probe: AF_UNIX socket failed unexpectedly (errno=%d)\n", errno);
        failures++;
    }
    struct addrinfo *res = NULL;
    int rc = getaddrinfo("localhost", "80", NULL, &res);
    if (rc == 0) {
        fprintf(stderr, "probe: getaddrinfo unexpectedly succeeded\n");
        failures++;
        freeaddrinfo(res);
    } else {
        fprintf(stderr, "probe: getaddrinfo denied (rc=%d)\n", rc);
    }
    struct hostent *h = gethostbyname("localhost");
    if (h != NULL) {
        fprintf(stderr, "probe: gethostbyname unexpectedly succeeded\n");
        failures++;
    }
    return failures ? 1 : 0;
}
"""


def require_cc() -> str:
    cc = shutil.which("cc")
    if not cc:
        pytest.fail("native guard: no cc compiler found; frozen standalone tests cannot run "
                    "(install a C compiler, e.g. gcc, providing cc)")
    return cc


@pytest.fixture(scope="session")
def net_guard(tmp_path_factory):
    """Compile the native LD_PRELOAD guard and challenge it with the probe."""
    cc = require_cc()
    d = tmp_path_factory.mktemp("netguard")
    (d / "netguard.c").write_text(NETGUARD_C, encoding="utf-8")
    (d / "probe.c").write_text(PROBE_C, encoding="utf-8")
    so = d / "netguard.so"
    probe = d / "probe"
    for src, out, shared in (("netguard.c", so, True), ("probe.c", probe, False)):
        cmd = [cc, "-fPIC", "-O2"]
        if shared:
            cmd.append("-shared")
        cmd += ["-o", str(out), str(d / src), "-ldl"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            pytest.fail(f"native guard: compiling {src} failed:\n{r.stderr}")

    # Empty PATH directory: the probe must prove denial without Python/uv.
    empty_dir = tmp_path_factory.mktemp("empty-path")
    env = {"PATH": str(empty_dir), "HOME": str(d), "TMPDIR": str(d),
           "LD_PRELOAD": str(so)}
    r = subprocess.run([str(probe)], env=env, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        pytest.fail("native guard challenge: the probe reached the network despite the guard:\n"
                    + r.stderr + "\n" + r.stdout)
    if NET_DENIAL_MARKER not in r.stderr:
        pytest.fail("native guard challenge: denial marker missing from probe stderr:\n" + r.stderr)
    return types.SimpleNamespace(dir=d, so=so, probe=probe)


def frozen_env(root: Path, guard: Path, extra=None) -> dict:
    """Clean environment for frozen runs: empty PATH dir, no Python paths, no
    credentials, no trust overrides, native guard active."""
    empty_dir = root / "empty-path"
    tmp_dir = root / "tmp"
    empty_dir.mkdir(exist_ok=True)
    tmp_dir.mkdir(exist_ok=True)
    env = {
        "PATH": str(empty_dir),
        "HOME": str(root),
        "TMPDIR": str(tmp_dir),
        "LD_PRELOAD": str(guard),
    }
    for var in CREDENTIAL_VARS + TRUST_VARS + PYTHON_VARS:
        env[var] = ""
    for var in DISPLAY_VARS:
        env.pop(var, None)
    env.update(extra or {})
    return env


def check_clean_extraction(tmp_dir: Path):
    """PyInstaller must remove its extraction dir; no writes left in TMPDIR."""
    leftovers = [p.name for p in tmp_dir.iterdir()]
    assert not leftovers, f"extraction/tmp writes left behind in {tmp_dir}: {leftovers}"


def assert_no_denial(proc):
    blob = (proc.stdout or "") + (proc.stderr or "")
    assert NET_DENIAL_MARKER not in blob, (
        f"native network guard denied something during a frozen run:\n{blob}")


def _disable_core_dumps():
    """Qt aborts at native plugin failure; tests do not need core files."""
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except Exception:
        pass


def run_frozen(binary: Path, args, env, cwd=None, stdin=None, timeout=300):
    tmp_dir = Path(env["TMPDIR"])
    proc = subprocess.run([str(binary), *args], env=env, cwd=cwd, input=stdin,
                          capture_output=True, text=True, timeout=timeout,
                          preexec_fn=_disable_core_dumps)
    assert_no_denial(proc)
    check_clean_extraction(tmp_dir)
    return proc


# ---------------------------------------------------------------------------
# Source CLI runs for parity (existing invocation, sitecustomize network guard)
# ---------------------------------------------------------------------------

def source_env(root: Path) -> dict:
    """Real environment minus credentials, with the subprocess network guard."""
    env = dict(os.environ)
    for var in CREDENTIAL_VARS:
        env.pop(var, None)
    root.mkdir(parents=True, exist_ok=True)
    import tempfile
    guard_dir = Path(tempfile.mkdtemp(prefix="longform-netguard-"))
    guard_dir.mkdir(exist_ok=True)
    (guard_dir / "sitecustomize.py").write_text(textwrap.dedent("""
        import socket

        def _refuse(*_a, **_k):
            raise AssertionError("network access attempted in a test subprocess")

        socket.socket.connect = _refuse
        socket.create_connection = _refuse
    """), encoding="utf-8")
    env["PYTHONPATH"] = str(guard_dir)
    return env


def run_source(args, root: Path, cwd=None, extra_env=None, timeout=300):
    env = source_env(root)
    env.update(extra_env or {})
    proc = subprocess.run(["uv", "run", "--script", str(REPO / "longform.py"), *args],
                          env=env, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return proc


# ---------------------------------------------------------------------------
# Session-scoped build through the production script
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def built(tmp_path_factory, net_guard):
    """Build once per session through the documented script, then copy only the
    executable into a temporary directory with spaces. An artifact that is
    newer than every build input (e.g. produced by ./scripts/check.sh moments
    earlier) is reused; anything missing or stale is rebuilt by the script."""
    if not BUILD_SCRIPT.is_file():
        pytest.fail(f"scripts/build-standalone.sh not found at {BUILD_SCRIPT}: the documented "
                    "build entry point does not exist, so the standalone owner journey cannot run")
    exe = REPO / "dist" / BINARY_NAME
    venv_py = REPO / "build" / "standalone" / "venv" / "bin" / "python"
    inputs = [BUILD_SCRIPT, REPO / "scripts" / "standalone-requirements.txt", REPO / "longform.py"]
    inputs += sorted((REPO / "longform_core").glob("*.py"))
    inputs += sorted((REPO / "longform_core" / "resources").glob("*.json"))
    inputs += [REPO / "scripts" / "standalone_sidecars.py"]
    inputs += sorted((REPO / "scripts" / "standalone-licenses").glob("*"))
    fresh = (exe.is_file() and venv_py.is_file()
             and all(p.stat().st_mtime_ns <= exe.stat().st_mtime_ns for p in inputs))
    if not fresh:
        print("\nbuilding standalone executable via scripts/build-standalone.sh ...")
        proc = subprocess.run(["bash", str(BUILD_SCRIPT)], cwd=str(REPO),
                              capture_output=True, text=True, timeout=3600)
        if proc.returncode != 0:
            pytest.fail("scripts/build-standalone.sh failed:\n"
                        + (proc.stdout or "") + "\n" + (proc.stderr or ""))
    if not exe.is_file():
        pytest.fail(f"build script reported success but no artifact at {exe}")
    if not os.access(exe, os.X_OK):
        pytest.fail(f"{exe} is not executable")
    if not venv_py.is_file():
        pytest.fail(f"build venv interpreter missing at {venv_py}; the build script did not "
                    "provision its documented build environment")
    copied_dir = tmp_path_factory.mktemp("copied dir with spaces")
    copied = copied_dir / BINARY_NAME
    shutil.copy2(exe, copied)
    copied.chmod(0o755)
    return types.SimpleNamespace(exe=exe, copied=copied, copied_dir=copied_dir, venv_py=venv_py,
                                 guard_so=net_guard.so)


# ---------------------------------------------------------------------------
# Owner journey (tasks 1.1)
# ---------------------------------------------------------------------------

EXPECTED_COMMANDS = ("init", "limits", "bible", "outline", "scenes", "draft", "update-state",
                     "compress", "critique", "check", "revise", "status", "export", "gui")

GUI_APPLICATION_MODULES = (
    "longform_core.gui", "longform_core.gui_window", "longform_core.draft_operations",
    "longform_core.planning_operations", "longform_core.review_operations",
    "longform_core.draft_worker", "longform_core.reader_model", "longform_core.scene_steering",
    "PySide6", "shiboken6",
)

# PySide6's Qt bindings and Shiboken are native extension modules: PyInstaller
# stores them in the CArchive, not the PYZ.
GUI_NATIVE_BINDINGS = (
    "PySide6/QtCore.abi3.so", "PySide6/QtGui.abi3.so", "PySide6/QtWidgets.abi3.so",
    "shiboken6/Shiboken.abi3.so",
)


def test_copied_binary_runs_help_without_python_uv_or_checkout(built, tmp_path):
    """Copy only the binary away from the checkout, run it by absolute path from
    another working directory with an empty PATH dir."""
    work = tmp_path / "work dir with spaces"
    work.mkdir()
    env = frozen_env(tmp_path, built.guard_so)
    r = run_frozen(built.copied, ["--help"], env=env, cwd=work)
    assert r.returncode == 0, r.stderr
    for cmd in EXPECTED_COMMANDS:
        assert cmd in r.stdout, f"--help did not list {cmd}"
    assert "gui [DIR]" in r.stdout, "help must show the optional GUI directory"


def test_copied_binary_init_creates_project_files(built, tmp_path):
    work = tmp_path / "also unrelated cwd"
    work.mkdir()
    env = frozen_env(tmp_path, built.guard_so)
    proj = tmp_path / "demo project"
    r = run_frozen(built.copied, ["init", str(proj)], env=env, cwd=work)
    assert r.returncode == 0, r.stderr
    assert f"project: {proj}" in r.stdout
    made = r.stdout.splitlines()[1]
    assert made.startswith("created: ")
    assert made == "created: project.json, bible.md, state.md, scenes.json, " \
        "summaries.json, writer_preset.json", made
    for name in ("project.json", "bible.md", "state.md", "scenes.json",
                 "summaries.json", "writer_preset.json"):
        assert (proj / name).is_file(), name
    for d in ("trees", "outlines", "critiques", "checks", "state_history",
              "lorebooks", "bible_history"):
        assert (proj / d).is_dir(), d
    cfg = json.loads((proj / "project.json").read_text(encoding="utf-8"))
    assert cfg["title"] == "Untitled"
    # The bundled defaults match the reviewed repository assets byte for byte.
    assert (proj / "writer_preset.json").read_bytes() == \
        (REPO / "longform_core" / "resources" / "writer_preset.json").read_bytes(), \
        "the copied executable must ship the reviewed preset verbatim"
    defaults = json.loads(
        (REPO / "longform_core" / "resources" / "project_defaults.json")
        .read_text(encoding="utf-8"))
    for key, value in defaults.items():
        if key == "api_key":
            assert cfg.get("api_key", "") == "", "no credential is initialized"
            continue
        assert cfg.get(key) == value, \
            f"project.json field {key} not taken from the bundled defaults"


def test_copied_binary_init_repeat_and_preset_override(built, tmp_path):
    """create-missing-only semantics and explicit override precedence agree
    between the copied executable and the source launcher, with the owner's
    originals inaccessible and no checkout adjacency supplying defaults."""
    work = tmp_path / "repeat work dir"
    work.mkdir()
    env = frozen_env(tmp_path, built.guard_so)
    proj = tmp_path / "repeat project"
    assert run_frozen(built.copied, ["init", str(proj)], env=env, cwd=work).returncode == 0

    preset = proj / "writer_preset.json"
    preset.write_text('{"custom": true}\n', encoding="utf-8")
    before = preset.read_bytes()
    r = run_frozen(built.copied, ["init", str(proj)], env=env, cwd=work)
    assert r.returncode == 0, r.stderr
    assert "nothing; all files already exist" in r.stdout, r.stdout
    assert preset.read_bytes() == before, "repeat init overwrote an existing preset"

    # an explicit synthetic preset wins for a missing destination
    synthetic = tmp_path / "synthetic override.json"
    synthetic.write_text(json.dumps(WRITER_PRESET) + "\n", encoding="utf-8")
    other = tmp_path / "override project"
    r = run_frozen(built.copied, ["init", str(other), "--preset", str(synthetic)],
                   env=env, cwd=work)
    assert r.returncode == 0, r.stderr
    assert (other / "writer_preset.json").read_bytes() == synthetic.read_bytes()
    # an existing destination is preserved and the override is refused
    r = run_frozen(built.copied, ["init", str(other), "--preset", str(synthetic)],
                   env=env, cwd=work)
    assert r.returncode == 0, r.stderr
    assert "not overwritten" in r.stdout or "not-overwritten" in r.stdout, r.stdout
    assert (other / "writer_preset.json").read_bytes() == synthetic.read_bytes()

    # an invalid explicit preset fails closed with a diagnostic, exit nonzero
    bad = tmp_path / "bad preset.json"
    bad.write_text("{not valid json", encoding="utf-8")
    fresh = tmp_path / "fresh failclosed"
    r = run_frozen(built.copied, ["init", str(fresh), "--preset", str(bad)],
                   env=env, cwd=work)
    assert r.returncode != 0, r.stdout
    blob = r.stdout + r.stderr
    assert "error: the selected preset is not valid JSON" in blob, blob
    assert "created before the error" in blob, \
        "partial work must be reported truthfully"
    assert not (fresh / "writer_preset.json").exists(), \
        "an invalid preset must not produce a preset"
    # an unreadable explicit source names the supplied path, as in source
    gone = tmp_path / "unreadable preset.json"
    fresh2 = tmp_path / "fresh unreadable"
    r = run_frozen(built.copied, ["init", str(fresh2), "--preset", str(gone)],
                   env=env, cwd=work)
    assert r.returncode != 0, r.stdout
    assert str(gone) in r.stdout + r.stderr, "the diagnostic must name the path"
    assert not (fresh2 / "writer_preset.json").exists()


def test_copied_binary_headless_cli_without_display_variables(built, tmp_path):
    """help/init/status/export must not need a display, Qt or Wayland: the
    frozen CLI keeps working when every display variable is absent."""
    work = tmp_path / "headless caller cwd"
    work.mkdir()
    proj = tmp_path / "headless project"
    env = frozen_env(tmp_path, built.guard_so)
    for var in DISPLAY_VARS:
        assert var not in env, f"{var} leaked into the headless environment"
    r = run_frozen(built.copied, ["--help"], env=env, cwd=work)
    assert r.returncode == 0, r.stderr
    assert "gui" in r.stdout
    r = run_frozen(built.copied, ["init", str(proj)], env=env, cwd=work)
    assert r.returncode == 0, r.stderr
    assert (proj / "project.json").is_file()
    r = run_frozen(built.copied, ["status", str(proj)], env=env, cwd=work)
    assert r.returncode == 0, r.stderr
    out = work / "headless export.md"
    r = run_frozen(built.copied, ["export", str(proj), "--out", str(out)],
                   env=env, cwd=work)
    assert r.returncode == 0, r.stderr
    assert out.is_file() and out.read_text(encoding="utf-8").strip()


def test_copied_binary_with_no_arguments_launches_gui(built, tmp_path):
    """Double-click/no-argument startup takes the GUI path, not an argparse
    error: with no Wayland socket it emits the frozen recovery advice and
    exits nonzero before any project or network work."""
    runtime = tmp_path / "no-args-runtime"
    runtime.mkdir()
    work = tmp_path / "no-args cwd"
    work.mkdir()
    env = frozen_env(tmp_path, built.guard_so,
                     extra={"XDG_RUNTIME_DIR": str(runtime),
                            "WAYLAND_DISPLAY": "missing-socket-0"})
    r = run_frozen(built.copied, [], env=env, cwd=work, timeout=120)
    blob = r.stdout + r.stderr
    assert r.returncode != 0, blob
    assert "native Wayland is required" in blob, blob
    assert str(built.copied) in blob, "frozen guidance must name the copied executable"
    assert "uv run" not in blob
    assert "the following arguments are required" not in blob


# ---------------------------------------------------------------------------
# Artifact inspection (tasks 1.2)
# ---------------------------------------------------------------------------

FORBIDDEN_ARCHIVE_FRAGMENTS = (
    "myfic", "tests", ".env", "writer_prompt_fixture", "test_standalone",
    "netguard", "sitecustomize", "56295265",
)

INSPECT_ARCHIVE_SCRIPT = textwrap.dedent("""
    import json, sys, tempfile, os
    from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader
    exe = sys.argv[1]
    r = CArchiveReader(exe)
    cnames = list(r.toc)
    pyz_names = []
    for n in cnames:
        if n.endswith(".pyz"):
            fd, path = tempfile.mkstemp(suffix=".pyz")
            os.close(fd)
            try:
                with open(path, "wb") as fh:
                    fh.write(r.extract(n))
                pyz_names = list(ZlibArchiveReader(path).toc)
            finally:
                os.unlink(path)
    libpython_name = [n for n in cnames if n.startswith("libpython")][0]
    libpython = r.extract(libpython_name)
    cacert = r.extract("certifi/cacert.pem")
    import hashlib
    resources = {}
    for n in cnames:
        if n.startswith("longform_core/resources/"):
            data = r.extract(n)
            resources[n] = {"bytes": len(data),
                            "sha256": hashlib.sha256(data).hexdigest()}
    print(json.dumps({
        "carchive": cnames,
        "pyz": pyz_names,
        "libpython_name": libpython_name,
        "has_pyinit_ssl": b"PyInit__ssl" in libpython,
        "cacert_size": len(cacert),
        "cacert_head": cacert[:2048].decode("ascii", "replace"),
        "resources": resources,
    }))
""")


@pytest.fixture(scope="session")
def archive_contents(built):
    r = subprocess.run([str(built.venv_py), "-c", INSPECT_ARCHIVE_SCRIPT, str(built.exe)],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        pytest.fail("inspecting the built archive failed:\n" + r.stderr)
    return json.loads(r.stdout)


def test_archive_contains_runtime_modules_ssl_and_ca_data(archive_contents):
    carchive, pyz = archive_contents["carchive"], archive_contents["pyz"]
    assert "longform" in carchive, "launcher script not bundled"
    assert "libpython" in archive_contents["libpython_name"]
    for mod in ("longform_core", "longform_core.cli", "longform_core.commands",
                "longform_core.utils", "ssl", "httpx", "httpcore", "anyio", "certifi"):
        assert mod in pyz, f"{mod} not bundled in the PYZ archive"
    # _ssl is statically compiled into the bundled libpython on this toolchain
    assert archive_contents["has_pyinit_ssl"], "no bundled _ssl extension found"
    assert archive_contents["cacert_size"] > 10000, "certifi CA data missing or empty"
    assert "BEGIN CERTIFICATE" in archive_contents["cacert_head"]


def test_archive_contains_gui_application_modules(archive_contents):
    """The frozen executable must contain the GUI dispatch, window, shared
    operations and the Qt bindings it imports -- not only the CLI closure."""
    pyz = archive_contents["pyz"]
    for mod in GUI_APPLICATION_MODULES:
        assert mod in pyz, f"GUI module {mod} not bundled in the PYZ archive"


def test_archive_contains_qt_runtime_and_wayland_plugins(archive_contents):
    """Qt native libraries and the native Wayland platform plugin must be in
    the archive; a CLI-only executable cannot satisfy this."""
    carchive = archive_contents["carchive"]
    for binding in GUI_NATIVE_BINDINGS:
        assert binding in carchive, f"Qt/Shiboken binding {binding!r} not bundled"
    for fragment in ("libQt6Core.so", "libQt6Gui.so", "libQt6Widgets.so",
                     "libQt6WaylandClient.so", "libshiboken6"):
        assert any(fragment in n for n in carchive), \
            f"Qt/Shiboken native component {fragment!r} not bundled"
    wayland_plugins = [n for n in carchive
                       if "PySide6/Qt/plugins/platforms/" in n and "qwayland" in n]
    assert wayland_plugins, \
        "no Wayland platform plugin bundled under PySide6/Qt/plugins/platforms/"


def test_archive_contains_no_private_or_test_inputs(archive_contents):
    names = archive_contents["carchive"] + archive_contents["pyz"]
    for fragment in FORBIDDEN_ARCHIVE_FRAGMENTS:
        assert not any(fragment in n for n in names), f"private/test input {fragment!r} in bundle"


def test_archive_bundles_reviewed_resources_exactly(archive_contents):
    """Only the two reviewed defaults assets are packaged, byte-identical to the
    repository copies; any missing/stale/corrupt packaged resource breaks the
    frozen suite instead of producing a silently incomplete executable."""
    resources = archive_contents["resources"]
    assert set(resources) == {"longform_core/resources/project_defaults.json",
                              "longform_core/resources/writer_preset.json"}, \
        f"unexpected packaged resource set: {sorted(resources)}"
    for name, info in resources.items():
        repo_bytes = (REPO / name).read_bytes()
        assert info["bytes"] == len(repo_bytes), name
        assert info["sha256"] == hashlib.sha256(repo_bytes).hexdigest(), \
            f"{name} differs between the archive and the repository"
    assert all(f not in archive_contents["carchive"] + archive_contents["pyz"]
               for f in ("project.json", "writer_prompt_fixture.json",
                         "56295265-LLam_ception-1.3.json")), \
        "private project data must never be packaged"


# ---------------------------------------------------------------------------
# GUI startup policy and recovery advice (standalone GUI)
# ---------------------------------------------------------------------------

REFUSED_PLATFORMS = ("xcb", "offscreen", "wayland,xcb", "wayland,offscreen")


def project_snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.mark.parametrize("platform", REFUSED_PLATFORMS)
def test_frozen_gui_refuses_platforms_before_qt(built, tmp_path, platform):
    """The copied executable refuses every non-Wayland platform before Qt
    loads: no fallback window, no project writes, no uv advice."""
    root = make_project(tmp_path / "frozen policy project")
    before = project_snapshot(root)
    env = frozen_env(tmp_path, built.guard_so, extra={"QT_QPA_PLATFORM": platform})
    r = run_frozen(built.copied, ["gui", str(root)], env=env, cwd=tmp_path)
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "native Wayland" in r.stderr
    assert str(built.copied) in r.stderr, "advice must name the copied executable"
    assert "uv run" not in r.stderr, "frozen advice must not require uv or source"
    assert "gui DIR" in r.stderr
    assert project_snapshot(root) == before, "refused GUI must not write project files"


@pytest.mark.parametrize("platform", REFUSED_PLATFORMS)
def test_source_gui_refuses_platforms_before_qt(built, tmp_path, platform):
    root = make_project(tmp_path / "source policy project")
    before = project_snapshot(root)
    r = run_source(["gui", str(root)], root=tmp_path,
                   extra_env={"QT_QPA_PLATFORM": platform})
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "native Wayland" in r.stderr
    assert "uv run --script longform.py gui" in r.stderr
    assert str(built.copied) not in r.stderr
    assert project_snapshot(root) == before


@pytest.mark.parametrize("platform", (None, "wayland"))
def test_frozen_gui_missing_wayland_socket_gives_standalone_advice(
        built, tmp_path, platform):
    """With no Wayland socket the native plugin aborts after the flushed
    pre-start guidance; the copied executable must point at itself, not uv."""
    root = make_project(tmp_path / f"missing socket project {platform}")
    before = project_snapshot(root)
    runtime = tmp_path / f"isolated-runtime-{platform or 'unset'}"
    runtime.mkdir()
    extra = {"XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "missing-socket-0"}
    if platform:
        extra["QT_QPA_PLATFORM"] = platform
    else:
        extra["QT_QPA_PLATFORM"] = ""
    env = frozen_env(tmp_path, built.guard_so, extra=extra)
    r = run_frozen(built.copied, ["gui", str(root)], env=env, cwd=tmp_path, timeout=120)
    assert r.returncode != 0, "GUI must fail when the Wayland socket is missing"
    blob = r.stdout + r.stderr
    assert "native Wayland is required" in blob
    assert str(built.copied) in blob, "frozen guidance must name the copied executable"
    assert "uv run" not in blob, "frozen guidance must not require uv or source"
    assert project_snapshot(root) == before, "failed GUI startup must not write project files"


@pytest.mark.parametrize("platform", (None, "wayland"))
def test_source_gui_missing_wayland_socket_keeps_source_advice(built, tmp_path, platform):
    root = make_project(tmp_path / f"source missing socket {platform}")
    runtime = tmp_path / f"source-runtime-{platform or 'unset'}"
    runtime.mkdir()
    extra = {"XDG_RUNTIME_DIR": str(runtime), "WAYLAND_DISPLAY": "missing-socket-0",
             "QT_QPA_PLATFORM": platform or ""}
    r = run_source(["gui", str(root)], root=tmp_path, extra_env=extra, timeout=180)
    assert r.returncode != 0
    blob = r.stdout + r.stderr
    assert "native Wayland is required" in blob
    assert "uv run --script longform.py gui" in blob
    assert str(built.copied) not in blob


# ---------------------------------------------------------------------------
# External editor invocation (tasks 2.1)
# ---------------------------------------------------------------------------

ENV_EDITOR_SH = """\
#!/bin/sh
{
  printf 'LD_LIBRARY_PATH=[%s]\\n' "$LD_LIBRARY_PATH"
  printf 'LD_LIBRARY_PATH_SET=[%s]\\n' "${LD_LIBRARY_PATH+set}"
  printf 'LD_LIBRARY_PATH_ORIG=[%s]\\n' "$LD_LIBRARY_PATH_ORIG"
  printf 'LD_LIBRARY_PATH_ORIG_SET=[%s]\\n' "${LD_LIBRARY_PATH_ORIG+set}"
} > "$EDITOR_DUMP"
printf 'EDITED BY FAKE EDITOR\\n' >> "$1"
"""


def make_env_editor(tmp_path):
    dump = tmp_path / "editor-env-dump.txt"
    editor = tmp_path / "env-editor.sh"
    editor.write_text(ENV_EDITOR_SH, encoding="utf-8")
    editor.chmod(0o755)
    return editor, dump


def read_env_dump(dump):
    fields = {}
    for line in dump.read_text(encoding="utf-8").splitlines():
        m = re.match(r"(\w+)=\[(.*)\]", line)
        if m:
            fields[m.group(1)] = m.group(2)
    return fields


def test_frozen_edit_text_restores_library_path(tmp_path, monkeypatch):
    """Frozen only: the editor child must see the host's original library search
    path instead of the extraction directory."""
    from longform_core import utils
    editor, dump = make_env_editor(tmp_path)
    monkeypatch.setenv("VISUAL", str(editor))
    monkeypatch.setenv("EDITOR", str(editor))
    monkeypatch.setenv("EDITOR_DUMP", str(dump))
    monkeypatch.setenv("LD_LIBRARY_PATH", "/frozen/extraction/dir")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/host/original/lib")
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    result = utils.edit_text("original text\n")
    assert "original text" in result and "EDITED BY FAKE EDITOR" in result
    env = read_env_dump(dump)
    assert env["LD_LIBRARY_PATH"] == "/host/original/lib"


def test_frozen_edit_text_without_original_library_path_removes_it(tmp_path, monkeypatch):
    from longform_core import utils
    editor, dump = make_env_editor(tmp_path)
    monkeypatch.setenv("VISUAL", str(editor))
    monkeypatch.setenv("EDITOR", str(editor))
    monkeypatch.setenv("EDITOR_DUMP", str(dump))
    monkeypatch.setenv("LD_LIBRARY_PATH", "/frozen/extraction/dir")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    utils.edit_text("text\n")
    env = read_env_dump(dump)
    assert env["LD_LIBRARY_PATH_SET"] != "set", "extraction path must not leak into the editor"


def test_source_edit_text_behavior_unchanged(tmp_path, monkeypatch):
    """Without frozen execution the env is inherited exactly as before."""
    from longform_core import utils
    editor, dump = make_env_editor(tmp_path)
    monkeypatch.setenv("VISUAL", str(editor))
    monkeypatch.setenv("EDITOR", str(editor))
    monkeypatch.setenv("EDITOR_DUMP", str(dump))
    monkeypatch.setenv("LD_LIBRARY_PATH", "/host/whatever/lib")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/elsewhere/lib")
    monkeypatch.delattr(sys, "frozen", raising=False)

    result = utils.edit_text("text\n")
    env = read_env_dump(dump)
    assert env["LD_LIBRARY_PATH"] == "/host/whatever/lib"
    assert "text" in result and "EDITED BY FAKE EDITOR" in result


# ---------------------------------------------------------------------------
# Synthetic projects used by frozen-command tests
# ---------------------------------------------------------------------------

WRITER_PRESET = {
    "preset": {"temp": 1.0, "genamt": 50},
    "instruct": {"macro": True, "input_sequence": "\n", "input_suffix": "\n",
                 "output_sequence": "\n", "stop_sequence": ""},
    "context": {"story_string": "{{description}}"},
    "sysprompt": {"content": "You narrate {{char}}."},
}

TREE_1 = {
    "nodes": {
        "n1": {"id": "n1", "parent": None, "text": "Opening.", "sep": "\n\n",
               "source": "model", "created": "2026-01-01 10:00", "model": "test-model",
               "steer": "keep quiet"},
        "n2": {"id": "n2", "parent": None, "text": "An inactive branch not exported.",
               "sep": "\n\n", "source": "model", "created": "2026-01-01 10:01",
               "model": "test-model"},
    },
    "head": "n1", "counter": 2,
}

ACTIVE_TEXT_1 = "Opening."


def make_project(root: Path, scenes=None, trees=None, banned=None, preset=True, summaries=None):
    """A fixed synthetic project (no API use): config, optional preset, scenes
    and per-scene trees, including inactive branches."""
    root.mkdir(parents=True, exist_ok=True)
    cfg = {"title": "Frozen parity test"}
    if banned is not None:
        cfg["banned_phrases"] = banned
    (root / "project.json").write_text(json.dumps(cfg) + "\n", encoding="utf-8")
    if preset:
        (root / "writer_preset.json").write_text(json.dumps(WRITER_PRESET) + "\n", encoding="utf-8")
    (root / "bible.md").write_text("# Story bible\n\nA quiet town.\n", encoding="utf-8")
    (root / "state.md").write_text("Mara is at the yard.\n", encoding="utf-8")
    (root / "scenes.json").write_text(json.dumps(scenes if scenes is not None else [
        {"id": "s001", "chapter": 1, "title": "Yard", "pov": "Mara",
         "characters": ["Mara"], "goal": "count the windows", "target_words": 100,
         "status": "drafting"},
    ]) + "\n", encoding="utf-8")
    (root / "summaries.json").write_text(json.dumps(summaries if summaries is not None
                                                    else {"scenes": {}, "arcs": []}) + "\n",
                                         encoding="utf-8")
    (root / "trees").mkdir(exist_ok=True)
    for sid, tree in (trees or {"s001": TREE_1}).items():
        (root / "trees" / f"{sid}.json").write_text(json.dumps(tree) + "\n", encoding="utf-8")
    return root


def test_frozen_binary_draft_edit_saves_through_fake_editor(built, tmp_path):
    """A synthetic draft session in the copied executable edits the steering note
    with a user-supplied fake editor; the editor must see the host's original
    library search environment, and its edits must be saved through the draft
    flow."""
    root = make_project(tmp_path / "editor project")
    editor, dump = make_env_editor(tmp_path)

    # Case 1: an original host library path exists (as LD_LIBRARY_PATH_ORIG set
    # before the freeze).
    env = frozen_env(tmp_path, built.guard_so, extra={
        "VISUAL": str(editor), "EDITOR": str(editor), "EDITOR_DUMP": str(dump),
        "LD_LIBRARY_PATH_ORIG": "/host/original/lib",
    })
    r = run_frozen(built.copied, ["draft", str(root), "--scene", "s001"], env=env,
                   stdin="se\nq\n", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "steer set: EDITED BY FAKE EDITOR" in r.stdout
    tree = json.loads((root / "trees" / "s001.json").read_text(encoding="utf-8"))
    assert tree["steer"] == "EDITED BY FAKE EDITOR"
    fields = read_env_dump(dump)
    assert fields["LD_LIBRARY_PATH"] == "/host/original/lib", \
        "the bundled extraction path must not leak into the editor"

    # Case 2: no original library path; the editor child sees none.
    dump.unlink()
    env = frozen_env(tmp_path, built.guard_so, extra={
        "VISUAL": str(editor), "EDITOR": str(editor), "EDITOR_DUMP": str(dump),
    })
    r = run_frozen(built.copied, ["draft", str(root), "--scene", "s001"], env=env,
                   stdin="se\nq\n", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    fields = read_env_dump(dump)
    assert fields.get("LD_LIBRARY_PATH_SET") != "set", \
        f"editor saw a library search path it must not see: {fields}"
    assert fields.get("LD_LIBRARY_PATH_ORIG_SET") != "set"


# ---------------------------------------------------------------------------
# Frozen/source CLI parity (tasks 2.2)
# ---------------------------------------------------------------------------

STAMP_RE = re.compile(r"\(\d{4}-\d{2}-\d{2}T[^)]*\)")


def normalize(text, roots=(), prog_name=True):
    """Only documented normalizations: temporary roots, program name, and the
    known fixture timestamps. argparse wraps the usage block according to the
    program-name length, so the wrapped usage is compared whitespace-collapsed
    (a consequence of the permitted program-name difference)."""
    for root in roots:
        text = text.replace(str(root), "ROOT")
    if prog_name:
        text = text.replace("longform.py", "longform")
        usage_re = re.compile(r"^usage:[^\n]*\n(?:[ \t][^\n]*\n?)*", re.M)
        m = usage_re.search(text)
        if m:
            text = text[:m.start()] + " ".join(m.group(0).split()) + "\n" + text[m.end():]
    return STAMP_RE.sub("(STAMP)", text)


def parity(built, tmp_path, args, *, stdin=None, cwd="frozen-work", extra=None):
    """Run the same command through the copied binary and the source launcher on
    separate synthetic projects and compare output/exit status after
    normalization."""
    f_root = tmp_path / "frozen-root"
    s_root = tmp_path / "source-root"
    f_cwd = tmp_path / cwd
    f_cwd.mkdir(parents=True, exist_ok=True)
    s_cwd = tmp_path / (cwd + "-src")
    s_cwd.mkdir(parents=True, exist_ok=True)

    f_args = [a.replace("@ROOT@", str(f_root)) for a in args]
    s_args = [a.replace("@ROOT@", str(s_root)) for a in args]

    fr = run_frozen(built.copied, f_args, env=frozen_env(tmp_path, built.guard_so, extra=extra),
                    cwd=f_cwd, stdin=stdin)
    sr = run_source(s_args, root=s_root, cwd=s_cwd, extra_env=None)
    assert fr.returncode == sr.returncode, \
        f"exit status mismatch: frozen {fr.returncode} vs source {sr.returncode}\n" \
        f"frozen stderr: {fr.stderr}\nsource stderr: {sr.stderr}"
    f_norm = normalize(fr.stdout, roots=(f_root,)) + "|||" + normalize(fr.stderr, roots=(f_root,))
    s_norm = normalize(sr.stdout, roots=(s_root,)) + "|||" + normalize(sr.stderr, roots=(s_root,))
    assert f_norm == s_norm, (
        "frozen/source output mismatch:\n--- frozen ---\n" + f_norm + "\n--- source ---\n" + s_norm)
    return fr, sr, f_root, s_root


def test_parity_help(built, tmp_path):
    parity(built, tmp_path, ["--help"])


def test_parity_invalid_command(built, tmp_path):
    parity(built, tmp_path, ["definitely-not-a-command"])


def test_parity_missing_required_argument(built, tmp_path):
    parity(built, tmp_path, ["revise"])


def test_parity_missing_project_directory(built, tmp_path):
    parity(built, tmp_path, ["status", "/definitely/not/a/project/path"])


def test_parity_init_first_and_repeated(built, tmp_path):
    _, _, f_root, s_root = parity(built, tmp_path, ["init", "@ROOT@"])
    # Same files with the same contents on both sides.
    f_files = {p.relative_to(f_root).as_posix(): p for p in f_root.rglob("*") if p.is_file()}
    s_files = {p.relative_to(s_root).as_posix(): p for p in s_root.rglob("*") if p.is_file()}
    assert f_files and set(f_files) == set(s_files)
    for rel, fpath in f_files.items():
        assert fpath.read_bytes() == s_files[rel].read_bytes(), rel
    f_dirs = {p.relative_to(f_root).as_posix() for p in f_root.rglob("*") if p.is_dir()}
    s_dirs = {p.relative_to(s_root).as_posix() for p in s_root.rglob("*") if p.is_dir()}
    assert f_dirs == s_dirs
    # Repeated init changes nothing.
    parity(built, tmp_path, ["init", "@ROOT@"], cwd="frozen-work-2")


def test_parity_init_with_preset(tmp_path, built):
    """--preset copies a fixed synthetic SillyTavern-style preset on both sides."""
    preset = tmp_path / "synthetic preset.json"
    preset.write_text(json.dumps(WRITER_PRESET) + "\n", encoding="utf-8")
    f_root = tmp_path / "frozen-root"
    s_root = tmp_path / "source-root"
    fr = run_frozen(built.copied, ["init", str(f_root), "--preset", str(preset)],
                    env=frozen_env(tmp_path, built.guard_so), cwd=tmp_path)
    sr = run_source(["init", str(s_root), "--preset", str(preset)], root=tmp_path, cwd=tmp_path)
    assert fr.returncode == sr.returncode == 0, (fr.stderr, sr.stderr)
    assert normalize(fr.stdout, roots=(f_root,)) == normalize(sr.stdout, roots=(s_root,))
    assert (f_root / "writer_preset.json").read_bytes() == (s_root / "writer_preset.json").read_bytes()


def test_parity_status_with_inactive_branch(built, tmp_path):
    root = make_project(tmp_path / "frozen-root")
    make_project(tmp_path / "source-root")
    parity(built, tmp_path, ["status", "@ROOT@"], cwd="parity-status")


def test_parity_check_reports(built, tmp_path):
    banned = ["red dragon", "spine"]
    scenes = [
        {"id": "s001", "chapter": 1, "title": "One", "characters": [], "target_words": 100},
        {"id": "s002", "chapter": 1, "title": "Two", "characters": [], "target_words": 100},
    ]
    text1 = "Shivers down her spine. The red dragon flew over green hills. " * 3
    trees = {
        "s001": {
            "nodes": {
                "n1": {"id": "n1", "parent": None, "text": text1, "sep": "\n\n",
                       "source": "model", "created": "2026-01-01 10:00", "model": "m"},
                "n2": {"id": "n2", "parent": None, "text": "An inactive branch with the red dragon.",
                       "sep": "\n\n", "source": "model", "created": "2026-01-01 10:01", "model": "m"},
            },
            "head": "n1", "counter": 2,
        },
        "s002": {
            "nodes": {
                "n1": {"id": "n1", "parent": None, "text": "Shivers down another spine.",
                       "sep": "\n\n", "source": "model", "created": "2026-01-01 10:02", "model": "m"},
            },
            "head": "n1", "counter": 1,
        },
    }
    make_project(tmp_path / "frozen-root", scenes=scenes, trees=trees, banned=banned)
    make_project(tmp_path / "source-root", scenes=scenes, trees=trees, banned=banned)
    parity(built, tmp_path, ["check", "@ROOT@"], cwd="parity-check")
    # Reports written on both sides are identical after stamp normalization.
    f_report = (tmp_path / "frozen-root" / "checks" / "all.md").read_text(encoding="utf-8")
    s_report = (tmp_path / "source-root" / "checks" / "all.md").read_text(encoding="utf-8")
    assert STAMP_RE.sub("(STAMP)", f_report) == STAMP_RE.sub("(STAMP)", s_report)
    assert "inactive branch" not in f_report, "inactive branch text must not be checked"


def test_parity_export_active_branch(built, tmp_path):
    make_project(tmp_path / "frozen-root")
    make_project(tmp_path / "source-root")
    fr, sr, f_root, s_root = parity(built, tmp_path, ["export", "@ROOT@"],
                                    cwd="parity-export")
    f_ms = (f_root / "manuscript.md").read_text(encoding="utf-8")
    s_ms = (s_root / "manuscript.md").read_text(encoding="utf-8")
    assert f_ms == s_ms
    assert "An inactive branch not exported." not in f_ms
    assert ACTIVE_TEXT_1 in f_ms
    # Relative --out resolves against the caller's working directory, not the
    # executable or extraction dir.
    work = tmp_path / "caller cwd"
    work.mkdir()
    env = frozen_env(tmp_path, built.guard_so)
    r = run_frozen(built.copied, ["export", str(f_root), "--out", "relative.md"], env=env, cwd=work)
    assert r.returncode == 0, r.stderr
    assert (work / "relative.md").is_file()
    assert (work / "relative.md").read_text(encoding="utf-8") == f_ms


def test_parity_limits_without_credentials(built, tmp_path):
    make_project(tmp_path / "frozen-root", preset=False)
    make_project(tmp_path / "source-root", preset=False)
    parity(built, tmp_path, ["limits", "@ROOT@"], cwd="parity-limits")


def test_no_writes_to_bundle_or_extraction_paths(built, tmp_path):
    """Frozen runs leave the dist/build sidecars untouched and the extraction
    TMPDIR clean (checked by run_frozen for every invocation)."""
    dist_before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in (REPO / "dist").iterdir()}
    build_marker = REPO / "build" / "standalone"
    build_before = {p.name: p.stat().st_mtime_ns for p in build_marker.iterdir()}
    env = frozen_env(tmp_path, built.guard_so)
    run_frozen(built.copied, ["--help"], env=env)
    dist_after = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in (REPO / "dist").iterdir()}
    build_after = {p.name: p.stat().st_mtime_ns for p in build_marker.iterdir()}
    assert dist_before == dist_after
    assert build_before == build_after


def test_build_script_fails_without_uv(tmp_path):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    r = subprocess.run(["bash", str(BUILD_SCRIPT)], cwd=str(REPO),
                       capture_output=True, text=True, env=env, timeout=300)
    assert r.returncode != 0, "build script must exit nonzero when uv is missing"
    assert "uv not found" in (r.stderr + r.stdout)


# ---------------------------------------------------------------------------
# Builder interpreter policy: fake provisioning contracts (task 1.3, ADR-0013)
# ---------------------------------------------------------------------------

def make_fake_build_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(BUILD_SCRIPT, repo / "scripts" / "build-standalone.sh")
    (repo / ".python-version").write_text("cpython@3.13\n", encoding="utf-8")
    (repo / "scripts" / "standalone-requirements.txt").write_text(
        "httpx==0.28.1\n", encoding="utf-8")
    return repo


def make_fake_provisioner(tmp_path):
    d = tmp_path / "fake-provisioner"
    d.mkdir()
    template = d / "fake-python"
    template.write_text(textwrap.dedent("""\
        #!/usr/bin/env bash
        if [[ "$1" == "-c" && "$2" == *python_implementation* ]]; then
          echo "${FAKE_VENV_IMPL:-CPython} ${FAKE_VENV_VERSION:-3.13.15}"
          exit ${FAKE_VENV_PY_EXIT:-0}
        fi
        exit 0
    """), encoding="utf-8")
    template.chmod(0o755)
    uv = d / "uv"
    uv.write_text(textwrap.dedent("""\
        #!/usr/bin/env bash
        echo "uv $*" >> "$FAKE_LOG"
        case "$*" in
          *"python install"*) exit ${FAKE_INSTALL_EXIT:-0} ;;
          *"pip install"*) exit ${FAKE_PIP_EXIT:-0} ;;
          *"venv"*)
            target="${*: -1}"
            mkdir -p "$target/bin"
            cp "$FAKE_VENV_PYTHON_TEMPLATE" "$target/bin/python"
            chmod +x "$target/bin/python"
            exit ${FAKE_VENV_EXIT:-0} ;;
          *) exit ${FAKE_UV_EXIT:-0} ;;
        esac
    """), encoding="utf-8")
    uv.chmod(0o755)
    return d


def run_fake_build(repo, tmp_path, extra_env=None):
    prov = make_fake_provisioner(tmp_path)
    env = {
        "PATH": os.pathsep.join([str(prov), "/usr/bin", "/bin"]),
        "HOME": str(tmp_path),
        "FAKE_LOG": str(repo / "log"),
        "FAKE_VENV_PYTHON_TEMPLATE": str(prov / "fake-python"),
    }
    env.update(extra_env or {})
    return subprocess.run(["bash", str(repo / "scripts" / "build-standalone.sh")],
                          cwd=str(repo), capture_output=True, text=True, env=env,
                          timeout=300)


def fake_build_log(repo):
    log = repo / "log"
    if not log.is_file():
        return []
    return log.read_text(encoding="utf-8").splitlines()


def test_build_script_provisions_latest_313_patch_automatically(tmp_path):
    """The builder requests the pinned minor with --upgrade and selects it
    explicitly for its cleared venv; no patch value appears in any request."""
    repo = make_fake_build_repo(tmp_path)
    r = run_fake_build(repo, tmp_path, {"FAKE_PIP_EXIT": "4"})
    lines = fake_build_log(repo)
    assert lines[0] == "uv python install --upgrade cpython@3.13"
    assert r.returncode != 0  # stopped at the fake pinned dependency install
    assert "could not install pinned build requirements" in r.stderr
    venv_line = next(l for l in lines if l.startswith("uv venv"))
    assert "--python cpython@3.13" in venv_line
    assert "--managed-python" in venv_line
    assert "--clear" in venv_line
    assert "3.13.15" not in venv_line, "no patch value may be baked into a request"


def test_build_script_explicit_requests_despite_host_env(tmp_path):
    """Another Python first on PATH resolution or a conflicting UV_PYTHON must
    not change the selected implementation/minor."""
    repo = make_fake_build_repo(tmp_path)
    r = run_fake_build(repo, tmp_path,
                       {"FAKE_PIP_EXIT": "4", "UV_PYTHON": "3.12"})
    lines = fake_build_log(repo)
    assert lines[0] == "uv python install --upgrade cpython@3.13"
    venv_line = next(l for l in lines if l.startswith("uv venv"))
    assert "--python cpython@3.13" in venv_line
    pip_line = next(l for l in lines if l.startswith("uv pip install"))
    assert "--python " in pip_line, pip_line


@pytest.mark.parametrize("impl,version", [("PyPy", "3.13.5"), ("CPython", "3.12.14"),
                                          ("CPython", "3.14.10")])
def test_build_script_rejects_wrong_interpreter_before_dependencies(tmp_path, impl, version):
    """A provisioned interpreter of the wrong implementation or minor fails
    before pip or PyInstaller can run; the diagnostic names the request and
    the actual interpreter."""
    repo = make_fake_build_repo(tmp_path)
    r = run_fake_build(repo, tmp_path,
                       {"FAKE_VENV_IMPL": impl, "FAKE_VENV_VERSION": version})
    assert r.returncode != 0
    lines = fake_build_log(repo)
    assert not any(l.startswith("uv pip install") for l in lines), lines
    assert not any("PyInstaller" in l for l in lines), lines
    blob = r.stdout + r.stderr
    assert impl in blob and version in blob
    assert "cpython@3.13" in blob


def test_build_script_provisioning_failure_propagates(tmp_path):
    repo = make_fake_build_repo(tmp_path)
    r = run_fake_build(repo, tmp_path, {"FAKE_INSTALL_EXIT": "1"})
    assert r.returncode != 0
    assert fake_build_log(repo) == ["uv python install --upgrade cpython@3.13"]
    assert "cpython@3.13" in (r.stdout + r.stderr)


@pytest.mark.parametrize("pin", ["", "3.13", "cpython@3.13.15", "cpython@3.12",
                                 "pypy@3.13", "cpython@3.13\n3.13"])
def test_build_script_rejects_missing_or_malformed_pins(tmp_path, pin):
    repo = make_fake_build_repo(tmp_path)
    (repo / ".python-version").write_text(pin, encoding="utf-8")
    r = run_fake_build(repo, tmp_path)
    assert r.returncode != 0
    assert ".python-version" in (r.stdout + r.stderr)
    assert fake_build_log(repo) == [], "no provisioning may run on an invalid pin"


def test_build_script_missing_pin_fails(tmp_path):
    repo = make_fake_build_repo(tmp_path)
    (repo / ".python-version").unlink()
    r = run_fake_build(repo, tmp_path)
    assert r.returncode != 0
    assert ".python-version" in (r.stdout + r.stderr)
    assert fake_build_log(repo) == []


# ---------------------------------------------------------------------------
# Sidecars: build identity and third-party notices (tasks 1.3)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def build_json(built):
    path = REPO / "dist" / "longform-build.json"
    if not path.is_file():
        pytest.fail("dist/longform-build.json missing; the build must record its identity")
    return json.loads(path.read_text(encoding="utf-8"))


def test_build_json_records_source_platform_interpreter_deps(built, build_json):
    src = build_json["source"]
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO),
                          capture_output=True, text=True).stdout.strip()
    assert src["commit"] == head
    status = subprocess.run(["git", "status", "--porcelain", "-uno"], cwd=str(REPO),
                            capture_output=True, text=True).stdout
    assert src["dirty"] == bool(status.strip())

    plat = build_json["platform"]
    assert plat["os"] == "Linux"
    assert plat["arch"] == "x86_64"
    assert re.search(r"\d+\.\d+", plat["glibc"])

    interp = build_json["interpreter"]
    assert interp["requested"] == "cpython@3.13", \
        "the sidecar must record the reviewed minor request"
    assert interp["implementation"] == "CPython"
    version = tuple(int(part) for part in interp["version"].split(".")[:2])
    assert version >= (3, 12), (
        f"build interpreter {interp['version']} is below 3.12: PySide6 6.12.0 drops "
        "a reference to None on every Qt call there (PYSIDE-3424), so long GUI sessions "
        "abort with 'none_dealloc: deallocating None'")
    assert version == (3, 13), \
        f"build interpreter {interp['version']} disagrees with the requested cpython@3.13"
    # the full actual version is recorded; the patch is observed, never asserted
    assert re.fullmatch(r"3\.13\.\d+", interp["version"]), interp["version"]

    deps = build_json["dependencies"]
    for name, version in (("pyinstaller", "6.22.3"), ("pyinstaller-hooks-contrib", "2026.10"),
                          ("httpx", "0.28.1"), ("certifi", None)):
        actual = next((v for k, v in deps.items() if k.lower().replace("_", "-") == name), None)
        assert actual is not None, f"{name} not recorded"
        if version:
            assert actual == version, f"{name}: expected {version}, recorded {actual}"

    host = build_json["host_libraries"]
    assert "libc.so.6" in host["ldd_artifact"], "artifact ldd boundary not recorded"
    assert host["ldd_version"] == plat["glibc"]

    art = build_json["artifact"]
    assert art["bytes"] == built.exe.stat().st_size
    import hashlib
    assert art["sha256"] == hashlib.sha256(built.exe.read_bytes()).hexdigest()

    res = build_json["bundled_resources"]
    assert "ADR-0010" in res["note"]
    assert [e["path"] for e in res["files"]] == \
        ["longform_core/resources/project_defaults.json",
         "longform_core/resources/writer_preset.json"]
    for e in res["files"]:
        repo_bytes = (REPO / e["path"]).read_bytes()
        assert e["bytes"] == len(repo_bytes)
        assert e["sha256"] == hashlib.sha256(repo_bytes).hexdigest()

    for name, version in (("pyside6-essentials", "6.12.0"), ("shiboken6", "6.12.0")):
        actual = next((v for k, v in deps.items()
                       if k.lower().replace("_", "-") == name), None)
        assert actual == version, f"{name}: expected {version}, recorded {actual}"


NONE_PROBE = textwrap.dedent("""
    import os
    import sys

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication([])
    widget = QWidget()
    before = sys.getrefcount(None)
    for i in range(50000):
        widget.setEnabled(i % 2 == 0)
        widget.clearMask()
        widget.setToolTip(None)
    after = sys.getrefcount(None)
    print(f"None refcount {before} -> {after}")
    assert after >= before, after
""")


def test_build_python_does_not_drop_none_refcount_under_qt_churn(built):
    """PYSIDE-3424: PySide6 6.12.0's abi3 wheels assume immortal None. On
    CPython 3.11 every None-returning Qt call loses a reference and a
    long-running GUI aborts with 'none_dealloc: deallocating None'; CPython
    3.12+ makes None immortal. The build interpreter must never leak here."""
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    proc = subprocess.run([str(built.venv_py), "-c", NONE_PROBE],
                          capture_output=True, text=True, timeout=120, env=env)
    assert proc.returncode == 0, (
        "build interpreter leaks references to None under Qt call churn "
        f"(PYSIDE-3424); exit {proc.returncode}\n{proc.stdout}\n{proc.stderr}")


def test_build_json_records_gui_versions_plugins_and_native_inspection(built, build_json):
    """The sidecar records the actual GUI closure: binding/Qt versions, every
    bundled plugin, and ldd results that separate bundled libraries from host
    dependencies for the Qt/Wayland files."""
    gui = build_json["gui"]
    assert gui["pyside6"] == "6.12.0"
    assert gui["shiboken6"] == "6.12.0"
    assert re.fullmatch(r"6\.12\.\d+", gui["qt"]), gui["qt"]
    assert gui["bindings_distribution"] == "pyside6-essentials"
    assert "LGPL-3.0-only" in gui["license"]

    inventory = gui["inventory"]
    for binding in GUI_NATIVE_BINDINGS:
        assert binding in inventory["bindings"], binding
    assert any(n.startswith("PySide6/Qt/lib/libQt6Core.so") for n in inventory["libraries"].values())
    assert any(n.startswith("PySide6/Qt/lib/libQt6WaylandClient.so")
               for n in inventory["libraries"].values())
    assert inventory["wayland_platform_plugins"], "no Wayland platform plugin recorded"
    assert all("libqwayland" in n for n in inventory["wayland_platform_plugins"])
    assert any("libxdg-shell" in n for n in inventory["wayland_shell_plugins"])
    assert inventory["wayland_decoration_plugins"]
    assert inventory["wayland_graphics_plugins"]
    assert "PySide6/Qt/plugins/platforms/libqwayland.so" in inventory["plugins"]

    native = gui["native_dependency_inspection"]
    assert native["inspected"], "no native GUI files inspected"
    assert any("libQt6Core.so" in entry for entry in native["inspected"])
    assert any("libqwayland" in entry for entry in native["inspected"])
    assert native["bundled"], "no bundled native dependencies detected"
    assert "libwayland-client.so.0" in native["host"], \
        "Wayland client library must stay a documented host dependency"
    assert all(name for name in native["bundled"] + native["host"])


def test_third_party_notices_cover_bundled_licenses(built, build_json):
    path = REPO / "dist" / "THIRD-PARTY-NOTICES.txt"
    if not path.is_file():
        pytest.fail("dist/THIRD-PARTY-NOTICES.txt missing; the build must record license texts")
    text = path.read_text(encoding="utf-8")
    assert "PSF" in text, "Python runtime license text missing"
    assert "Bootloader Exception" in text, "PyInstaller bootloader exception missing"
    assert "Mozilla Public License" in text, "certifi (CA data) license text missing"
    for name, version in (("httpx", "0.28.1"), ("certifi", None), ("anyio", None),
                          ("pyinstaller", "6.22.3"), ("pyinstaller-hooks-contrib", "2026.10")):
        assert f"{name} {version}  (" in text if version else f"{name} " in text, \
            f"license section for {name} missing"
    gui = build_json["gui"]
    assert f"PySide6 {gui['pyside6']}" in text
    assert f"Shiboken6 {gui['shiboken6']}" in text
    assert f"Qt {gui['qt']} native libraries" in text
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in text, "LGPLv3 text missing"
    assert "GNU GENERAL PUBLIC LICENSE\nVersion 2, June 1991" in text, "GPLv2 text missing"
    assert "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007" in text, "GPLv3 text missing"
    assert "Bundled plugin inventory:" in text
    for plugin in gui["inventory"]["wayland_platform_plugins"]:
        assert plugin in text, f"bundled plugin {plugin} not listed in notices"
    assert "Bundled reviewed resources (application-owned, ADR-0010):" in text
    for e in build_json["bundled_resources"]["files"]:
        assert e["path"] in text, f"bundled resource {e['path']} not listed"
        assert f"sha256={e['sha256']}" in text
    for fragment in ("fuckpi", "56295265", "LLam_ception"):
        assert fragment not in text, "private source data leaked into notices"


def test_copied_binary_runs_without_sidecars(built, tmp_path):
    """The copied executable is alone in its directory: neither sidecar present."""
    assert not (built.copied_dir / "longform-build.json").exists()
    assert not (built.copied_dir / "THIRD-PARTY-NOTICES.txt").exists()
    env = frozen_env(tmp_path, built.guard_so)
    r = run_frozen(built.copied, ["--help"], env=env)
    assert r.returncode == 0, r.stderr
    assert "usage:" in r.stdout


def test_extracted_certifi_data_loads_into_verifying_ssl_context(built, tmp_path):
    """Packaging/trust evidence: the bundled CA data parses into a verifying SSL
    context without an HTTPS call."""
    script = textwrap.dedent("""
        import json, ssl, tempfile, os, sys
        from PyInstaller.archive.readers import CArchiveReader
        r = CArchiveReader(sys.argv[1])
        data = r.extract("certifi/cacert.pem")
        fd, path = tempfile.mkstemp(suffix=".pem")
        os.close(fd)
        try:
            with open(path, "wb") as fh:
                fh.write(data)
            ctx = ssl.create_default_context(cafile=path)
        finally:
            os.unlink(path)
        print(json.dumps({"verify_mode": ctx.verify_mode, "ca_certs": len(ctx.get_ca_certs())}))
    """)
    r = subprocess.run([str(built.venv_py), "-c", script, str(built.exe)],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        pytest.fail("loading bundled CA data into an SSL context failed:\n" + r.stderr)
    result = json.loads(r.stdout)
    import ssl as _ssl
    assert result["verify_mode"] == _ssl.CERT_REQUIRED, "verification must stay enabled"
    assert result["ca_certs"] > 50, "certifi CA bundle did not load any certificates"


# ---------------------------------------------------------------------------
# Bundled defaults: failure and override parity (project-defaults-full-init)
# ---------------------------------------------------------------------------

def test_parity_init_explicit_preset_failure_and_missing_source(built, tmp_path):
    """Invalid and unreadable explicit presets fail closed identically: exit
    status, the diagnostic naming the supplied path and no success transcript
    agree between the copied executable and the source launcher."""
    bad = tmp_path / "bad preset.json"
    bad.write_text("{nope", encoding="utf-8")
    fr, sr, f_root, _ = parity(built, tmp_path,
                               ["init", "@ROOT@", "--preset", str(bad)])
    assert fr.returncode != 0
    assert "not valid JSON" in fr.stderr
    assert not (f_root / "writer_preset.json").exists()
    gone = tmp_path / "definitely gone.json"
    fr, _, _, _ = parity(built, tmp_path,
                         ["init", "@ROOT@", "--preset", str(gone)],
                         cwd="frozen-work-bad")
    assert fr.returncode != 0
    assert "gone.json" in fr.stderr + fr.stdout


def test_parity_init_preset_restore_after_removal(built, tmp_path):
    """Removing a default preset and repeating init restores exactly that
    missing default on both sides (create-missing-only, other bytes intact)."""
    _, _, f_root, s_root = parity(built, tmp_path, ["init", "@ROOT@"])
    for root in (f_root, s_root):
        (root / "writer_preset.json").unlink()
    parity(built, tmp_path, ["init", "@ROOT@"], cwd="frozen-work-restore")
    assert (f_root / "writer_preset.json").read_bytes() == \
        (REPO / "longform_core" / "resources" / "writer_preset.json").read_bytes()
    assert (f_root / "writer_preset.json").read_bytes() == \
        (s_root / "writer_preset.json").read_bytes()
