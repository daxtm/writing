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


def run_frozen(binary: Path, args, env, cwd=None, stdin=None, timeout=300):
    tmp_dir = Path(env["TMPDIR"])
    proc = subprocess.run([str(binary), *args], env=env, cwd=cwd, input=stdin,
                          capture_output=True, text=True, timeout=timeout)
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
    guard_dir = root / "netguard"
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
    executable into a temporary directory with spaces."""
    if not BUILD_SCRIPT.is_file():
        pytest.fail(f"scripts/build-standalone.sh not found at {BUILD_SCRIPT}: the documented "
                    "build entry point does not exist, so the standalone owner journey cannot run")
    print("\nbuilding standalone executable via scripts/build-standalone.sh ...")
    proc = subprocess.run(["bash", str(BUILD_SCRIPT)], cwd=str(REPO),
                          capture_output=True, text=True, timeout=3600)
    if proc.returncode != 0:
        pytest.fail("scripts/build-standalone.sh failed:\n"
                    + (proc.stdout or "") + "\n" + (proc.stderr or ""))
    exe = REPO / "dist" / BINARY_NAME
    if not exe.is_file():
        pytest.fail(f"build script reported success but no artifact at {exe}")
    if not os.access(exe, os.X_OK):
        pytest.fail(f"{exe} is not executable")
    venv_py = REPO / "build" / "standalone" / "venv" / "bin" / "python"
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
                     "compress", "critique", "check", "revise", "status", "export")


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
    for name in ("project.json", "bible.md", "state.md", "scenes.json", "summaries.json"):
        assert (proj / name).is_file(), name
    for d in ("trees", "outlines", "critiques", "checks", "state_history", "lorebooks", "bible_history"):
        assert (proj / d).is_dir(), d
    cfg = json.loads((proj / "project.json").read_text(encoding="utf-8"))
    assert cfg["title"] == "Untitled"


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
    print(json.dumps({
        "carchive": cnames,
        "pyz": pyz_names,
        "libpython_name": libpython_name,
        "has_pyinit_ssl": b"PyInit__ssl" in libpython,
        "cacert_size": len(cacert),
        "cacert_head": cacert[:2048].decode("ascii", "replace"),
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


def test_archive_contains_no_private_or_test_inputs(archive_contents):
    names = archive_contents["carchive"] + archive_contents["pyz"]
    for fragment in FORBIDDEN_ARCHIVE_FRAGMENTS:
        assert not any(fragment in n for n in names), f"private/test input {fragment!r} in bundle"


def test_build_script_fails_without_uv(tmp_path):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    r = subprocess.run(["bash", str(BUILD_SCRIPT)], cwd=str(REPO),
                       capture_output=True, text=True, env=env, timeout=300)
    assert r.returncode != 0, "build script must exit nonzero when uv is missing"
    assert "uv not found" in (r.stderr + r.stdout)
