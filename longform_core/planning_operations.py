"""Qt-independent planning operations shared by the CLI and the GUI (ADR-0007).

Extracted from commands.cmd_init/limits/bible/outline/scenes incrementally:
plain captured inputs, opaque expected baselines, optional provider
factory/token/event sink; sanitized plain view/result/error records. The CLI
keeps questions, printing, paging and $EDITOR as an adapter with unchanged
prompts, files and transcripts; GUI calls never reach ask/page/edit_text or
subprocess commands. Operations separate prepare/generate, preview and
explicit commit: workers never wait for an author decision.
"""

import json
import os
import re
from pathlib import Path

from .cancel import Cancelled
from .config import BIBLE_TEMPLATE, DEFAULT_CONFIG, STATE_TEMPLATE
from .draft_operations import (_advance, _capture, _emit, _project_of,
                               _read_bytes, _stale_check, OpError)
from .project import Project
from .utils import (FatalError, deep_merge, now, read_text, save_input, stamp,
                    write_text)

# ------------------------------------------------------- initialization


INIT_FILES = {
    "project.json": json.dumps(DEFAULT_CONFIG, indent=2) + "\n",
    "bible.md": BIBLE_TEMPLATE,
    "state.md": STATE_TEMPLATE,
    "scenes.json": "[]\n",
    "summaries.json": json.dumps({"scenes": {}, "arcs": []}, indent=2) + "\n",
}
INIT_DIRS = ("trees", "outlines", "critiques", "checks", "state_history",
             "lorebooks", "bible_history")


def canonical_root(root):
    """One canonical absolute project path; never follows a symlinked root."""
    root = Path(root).expanduser()
    if not root.is_absolute():
        root = Path.cwd() / root
    return Path(os.path.normpath(str(root)))


def _write_bytes_safe(path, data):
    """Atomic byte write refusing an existing non-file or symlink target."""
    if path.is_symlink():
        raise OpError(f"{path.name} is a symlink; refusing to write")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def init_project(root, *, preset_src=None, token=None, events=None):
    """Create-missing-only initialization with cmd_init's exact payloads.

    Existing files are never replaced, even malformed; a name collision with a
    directory or symlink is an error (with what was already created reported),
    not permission to reset. A preset source imports through the existing
    master-export validation without overwriting an existing destination.
    """
    root = canonical_root(root)
    if token:
        token.check()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise OpError(f"the project directory could not be created "
                      f"({type(e).__name__})") from None
    made, dirs_made, problems = [], [], []
    for name, content in INIT_FILES.items():
        path = root / name
        try:
            if path.is_symlink():
                raise OpError(f"{name} is a symlink; not overwritten")
            if path.exists() and not path.is_file():
                raise OpError(f"{name} exists and is not a regular file; "
                              "not overwritten")
        except OSError as e:
            raise OpError(f"{name} could not be inspected "
                          f"({type(e).__name__})") from None
        if not path.exists():
            write_text(path, content)
            made.append(name)
    for d in INIT_DIRS:
        dp = root / d
        if dp.is_symlink():
            raise OpError(f"{d}/ is a symlink; not replaced"
                          + _partial_note(made, dirs_made))
        if dp.exists():
            if not dp.is_dir():
                raise OpError(f"{d} exists and is not a directory; not replaced"
                              + _partial_note(made, dirs_made))
            continue
        try:
            dp.mkdir()
        except OSError as e:
            raise OpError(f"{d}/ could not be created ({type(e).__name__})"
                          + _partial_note(made, dirs_made)) from None
        dirs_made.append(d)
    preset = None
    if preset_src:
        preset = import_preset(root, preset_src, token=token)
    _emit(events, "initialized", created=len(made))
    return {"root": str(root), "created": made, "dirs": dirs_made,
            "preset": preset, "warnings": problems}


def _partial_note(made, dirs_made):
    if made or dirs_made:
        return (f" (created before the error: "
                f"{', '.join(made + dirs_made)}; initialization is not a "
                "transaction)")
    return ""


REQUIRED_PRESET_KEYS = ("instruct", "context", "sysprompt", "preset")


def import_preset(root, src, *, token=None, events=None):
    """Copy an explicitly picked SillyTavern master export to writer_preset.json.

    Unchanged source bytes; never overwrites an existing destination (no
    Replace button); an invalid or unreadable source changes nothing.
    """
    root = canonical_root(root)
    dst = root / "writer_preset.json"
    if dst.is_symlink() or (dst.exists() and not dst.is_file()):
        raise OpError("writer_preset.json exists and is not a regular file; "
                      "not overwritten", collision=True)
    if dst.exists():
        raise OpError("writer_preset.json already exists; not overwritten "
                      "(configure an existing preset path in Settings if "
                      "appropriate)", collision=True)
    src = Path(src).expanduser()
    try:
        data = src.read_bytes()
    except OSError as e:
        raise OpError("the selected preset could not be read "
                      f"({type(e).__name__})") from None
    try:
        d = json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise OpError(f"the selected preset is not valid JSON: {e}") from None
    if not isinstance(d, dict):
        raise OpError("the selected preset is not a SillyTavern master export "
                      "(not a JSON object)")
    for k in REQUIRED_PRESET_KEYS:
        if k not in d:
            raise OpError("the selected preset is not a SillyTavern master "
                          f"export (missing '{k}')")
    if token:
        token.check()
    try:
        _write_bytes_safe(dst, data)
    except OSError as e:
        raise OpError(f"writer_preset.json could not be written "
                      f"({type(e).__name__})") from None
    _emit(events, "preset_imported", name="writer_preset.json")
    return {"imported": "writer_preset.json", "bytes": len(data),
            "replaced": False}


# ------------------------------------------------------------------ open

_SAFE_JSON_FILES = ("project.json", "scenes.json", "summaries.json")
_INIT_FILE_NAMES = tuple(INIT_FILES)


def _safe_read_json(path, warnings, label):
    if path.is_symlink():
        warnings.append(f"{label} is a symlink and was not read")
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        warnings.append(f"{label} is missing or not valid JSON")
        return None
    if not isinstance(raw, dict) and label == "project.json":
        warnings.append(f"{label} is not a JSON object")
        return None
    return raw


def project_overview(root):
    """Read-only sanitized setup view for the Setup pane (no writes, no calls).

    Works for missing directories, empty directories and invalid configs; the
    only credential facts are the environment name and boolean availability —
    an existing inline api_key is never echoed or migrated.
    """
    root = canonical_root(root)
    out = {"root": str(root), "exists": root.is_dir(), "config_ok": False,
           "title": "", "target_words": 0, "scenes": 0, "scene_status": [],
           "preset_found": False, "preset_path": "", "api_key_env": "",
           "env_set": False, "inline_key": False, "creds_ok": False,
           "outline_present": False, "trees": [], "created_files": [],
           "missing_files": [], "dirs": [], "warnings": []}
    if not out["exists"]:
        out["warnings"].append("the directory does not exist yet; "
                               "use Create to initialize it")
        return out
    warnings = out["warnings"]
    missing = [n for n in _INIT_FILE_NAMES
               if not _plain_file(root / n)]
    out["missing_files"] = missing
    out["created_files"] = [n for n in _INIT_FILE_NAMES
                            if _plain_file(root / n)]
    out["dirs"] = [d for d in INIT_DIRS if (root / d).is_dir()]
    raw = _safe_read_json(root / "project.json", warnings, "project.json")
    if raw is None:
        out["warnings"] = warnings
        return out
    out["config_ok"] = True
    cfg = deep_merge(DEFAULT_CONFIG, raw)
    out["title"] = str(cfg.get("title", ""))
    out["target_words"] = cfg.get("target_words", 0)
    scenes_raw = _safe_read_json(root / "scenes.json", warnings, "scenes.json")
    if isinstance(scenes_raw, list):
        out["scenes"] = len(scenes_raw)
        out["scene_status"] = [str(s.get("status", ""))
                               for s in scenes_raw if isinstance(s, dict)]
    out["outline_present"] = (root / "outline.md").is_file()
    trees = root / "trees"
    if trees.is_dir() and not trees.is_symlink():
        try:
            out["trees"] = sorted(p.name for p in trees.glob("*.json"))
        except OSError:
            warnings.append("trees/ could not be listed")
    env = str(cfg.get("api_key_env") or "")
    out["api_key_env"] = env
    out["env_set"] = bool(env) and bool(os.environ.get(env, "").strip())
    out["inline_key"] = bool(str(cfg.get("api_key") or "").strip())
    out["creds_ok"] = out["inline_key"] or out["env_set"]
    preset = str(cfg.get("roles", {}).get("writer", {}).get("preset", "")
                 or "writer_preset.json")
    ppath = Path(preset).expanduser()
    if not ppath.is_absolute():
        if _escapes(root, ppath):
            warnings.append("the configured writer preset path is unsafe; "
                            "it was not read")
            ppath = None
        else:
            ppath = root / ppath
    if ppath is not None:
        out["preset_path"] = str(ppath)
        out["preset_found"] = ppath.is_file()
    out["warnings"] = warnings
    return out


def _plain_file(path):
    try:
        return path.is_file() and not path.is_symlink()
    except OSError:
        return False


def _escapes(root, rel):
    try:
        (root / rel).resolve().relative_to(root)
    except (OSError, ValueError):
        return True
    return False
