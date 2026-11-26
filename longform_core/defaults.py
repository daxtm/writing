"""Reviewed application-owned new-project defaults (ADR-0010).

Loads the two packaged resources under ``longform_core/resources/``:
``project_defaults.json`` (supported nonsecret settings for new projects) and
``writer_preset.json`` (the reviewed SillyTavern master export). Independent of
the current directory, Qt-free and offline: a plain data helper beside the
config/init code, shared by the CLI, the GUI and the frozen executable.

Contract:
- A fresh validated copy per call; callers may mutate it freely.
- Forced sanitizing fields: empty ``api_key``, ``api_key_env`` is
  ``FEATHERLESS_API_KEY``, ``roles.writer.preset`` is the project-relative
  ``writer_preset.json``.
- Explicit approved-field schema validation, recorded with the resources; an
  unknown or mistyped field fails closed with a message naming only the field
  path and the expected kind, never a value.
- A missing or corrupt resource raises :class:`DefaultsError`; there is no
  old-default fallback and no network fetch. The owner's original source files
  are never read at runtime.
"""

import copy
import json
import sys
from pathlib import Path

__all__ = ["DefaultsError", "project_defaults", "writer_preset_bytes",
           "validate_defaults", "validate_preset", "resource_candidates"]


class DefaultsError(Exception):
    """A bundled defaults resource is missing, unreadable, corrupt or fails
    review validation; initialization fails closed (sanitized message)."""


# ------------------------------------------------------------ value kinds

def _posint(v):
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def _nonnegint(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _posnum(v):
    return _num(v) and v > 0


def _nonnegnum(v):
    return _num(v) and v >= 0


def _prob01(v):
    return _num(v) and 0 <= v <= 1


def _margin(v):
    return _num(v) and 0 <= v < 1


def _text(v):
    return isinstance(v, str)


def _nonblank(v):
    return isinstance(v, str) and v.strip() != ""


def _boolean(v):
    return isinstance(v, bool)


def _envname(v):
    if not isinstance(v, str) or not v:
        return False
    if not (v[0].isalpha() or v[0] == "_"):
        return False
    return all(c.isalnum() or c == "_" for c in v)


def _url(v):
    return isinstance(v, str) and v.startswith(("http://", "https://"))


def _lines(v):
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _empty(v):
    return v == ""


def _enum(*allowed):
    def check(v):
        return v in allowed
    return check


_KINDS = {
    "empty": _empty, "posint": _posint, "nonnegint": _nonnegint,
    "num": _num, "posnum": _posnum, "nonnegnum": _nonnegnum,
    "prob01": _prob01, "margin": _margin, "text": _text,
    "nonblank": _nonblank, "bool": _boolean, "envname": _envname,
    "url": _url, "lines": _lines,
}


def _fields(spec):
    """Normalize a schema level: ``{key: kind_or_schema}``."""
    return spec


class _Optional(dict):
    """A schema level whose approved fields may all be absent."""


def _optional(spec):
    return _Optional(spec)


# ------------------------------------------------- defaults schema (approved)

# Every allowed field with its expected kind. Anything absent is rejected; a
# present field with the wrong type is rejected. Recorded with the resources
# (docs/project-defaults.md).
_ROLES_CHAT = _fields({
    "model": "nonblank", "temperature": "nonnegnum", "max_tokens": "posint",
    "thinking": "bool",
})
_DEFAULTS_SCHEMA = {
    "title": "text", "target_words": "posint", "api_base": "url",
    "api_key": "empty", "api_key_env": "envname",
    "max_context_fallback": "posint", "context_safety_margin": "margin",
    "prompt_budget": "posint", "chars_per_token_default": "posnum",
    "max_parallel": "posint", "request_timeout_s": "posnum",
    "roles": {
        "planner": {**_ROLES_CHAT, "min_p": "prob01",
                    "thinking_budget": "nonnegint"},
        "writer": {
            "model": "nonblank", "preset": "nonblank",
            "preset_overrides": _optional({
                "temp": "nonnegnum", "genamt": "nonnegint",
                "max_length": "nonnegint", "top_k": "nonnegint",
                "top_p": "prob01", "min_p": "prob01", "rep_pen": "posnum",
                "freq_pen": "num", "presence_pen": "num",
                "dry_multiplier": "nonnegnum", "dry_base": "posnum",
                "dry_allowed_length": "nonnegint",
                "dry_penalty_last_n": "nonnegint",
                "dry_sequence_breakers": "lines",
            }),
            "swipes": "posint", "passage_words": "posint",
            "user_name": "text",
            "absent_character_lore": _enum("reference", "exclude"),
            "lore_match_whole_words": "bool",
        },
        "summarizer": _ROLES_CHAT, "critic": _ROLES_CHAT,
        "editor": {"model": "nonblank", "temperature": "nonnegnum",
                   "min_p": "prob01", "max_tokens": "posint"},
    },
    "budget_tokens": {
        "bible": "nonnegint", "scene_card": "nonnegint",
        "summary": "nonnegint", "state": "nonnegint", "lore": "nonnegint",
        "recent": "nonnegint", "steer": "nonnegint",
    },
    "summary": {
        "detailed_recent_scenes": "nonnegint", "detailed_words": "nonnegint",
        "brief_words": "nonnegint", "arc_words": "nonnegint",
    },
    "banned_phrases": "lines",
    "ngram": {"n": "posint", "min_count": "posint", "top": "posint"},
}

FORCED_DEFAULTS = (
    ("api_key", ""), ("api_key_env", "FEATHERLESS_API_KEY"),
    ("roles.writer.preset", "writer_preset.json"),
)


# --------------------------------------------------- preset schema (approved)

def _strings(v):
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _numbers(v):
    return isinstance(v, list) and \
        all(isinstance(x, (int, float)) and not isinstance(x, bool)
            for x in v)


def _mapping_or_list(v):
    return (isinstance(v, dict) and all(isinstance(k, str) for k in v)) \
        or _strings(v)


def _scalars(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _scalar_or_str(v):
    return isinstance(v, (str, int, float)) and not isinstance(v, bool)


# SillyTavern instruct/context/sysprompt metadata fields approved for the
# bundled export (recorded with the resource in docs/project-defaults.md).
_PRESET_SCHEMA = {
    "instruct": {
        "activation_regex": "text", "first_input_sequence": "text",
        "first_output_sequence": "text", "input_sequence": "text",
        "input_suffix": "text", "last_input_sequence": "text",
        "last_output_sequence": "text", "last_system_sequence": "text",
        "macro": "bool", "name": "text", "names_behavior": _scalar_or_str,
        "names_force_groups": "bool", "output_sequence": "text",
        "output_suffix": "text", "skip_examples": "bool",
        "stop_sequence": "text", "system_same_as_user": "bool",
        "system_sequence": "text", "system_sequence_prefix": "text",
        "system_sequence_suffix": "text", "system_suffix": "text",
        "user_alignment_message": "text", "wrap": "bool",
    },
    "context": {
        "allow_jailbreak": "bool", "always_force_name2": "bool",
        "chat_start": "text", "example_separator": "text", "name": "text",
        "names_as_stop_strings": "bool", "single_line": "bool",
        "story_string": "text", "trim_sentences": "bool",
        "use_stop_strings": "bool",
    },
    "sysprompt": {"content": "text", "name": "text"},
    "preset": {
        "add_bos_token": "bool", "ban_eos_token": "bool",
        "banned_tokens": "text", "do_sample": "bool",
        "dry_allowed_length": _nonnegint, "dry_base": _scalar_or_str,
        "dry_multiplier": _nonnegnum, "dry_penalty_last_n": _nonnegint,
        "dry_sequence_breakers": "text", "dynatemp": "bool",
        "dynatemp_exponent": _num, "dynatemp_range": _num,
        "early_stopping": "bool", "encoder_rep_pen": _scalar_or_str,
        "epsilon_cutoff": _num, "eta_cutoff": _num, "freq_pen": _num,
        "genamt": _nonnegint, "grammar_string": "text",
        "guidance_scale": _scalar_or_str, "ignore_eos_token": "bool",
        "ignore_eos_token_aphrodite": "bool", "json_schema": _mapping_or_list,
        "length_penalty": _num, "logit_bias": _strings, "max_length": _posint,
        "max_temp": _num, "min_length": _nonnegint, "min_p": _scalar_or_str,
        "min_temp": _num, "mirostat_eta": _num, "mirostat_mode": _nonnegint,
        "mirostat_tau": _num, "name": "text", "negative_prompt": "text",
        "no_repeat_ngram_size": _nonnegint, "nsigma": _num,
        "num_beams": _nonnegint, "penalty_alpha": _num,
        "presence_pen": _num, "rep_pen": _scalar_or_str,
        "rep_pen_decay": _num, "rep_pen_range": _num, "rep_pen_size": _num,
        "rep_pen_slope": _num, "sampler_order": _numbers,
        "sampler_priority": _strings, "samplers": _strings,
        "samplers_priorities": _strings, "skip_special_tokens": "bool",
        "smoothing_curve": _num, "smoothing_factor": _num, "skew": _num,
        "spaces_between_special_tokens": "bool",
        "spaces_between_special_tokens_aphrodite": "bool",
        "speculative_ngram": "bool", "temp": _scalar_or_str,
        "temperature_last": "bool", "tfs": _scalar_or_str, "top_a": _num,
        "top_k": _scalar_or_str, "top_p": _scalar_or_str,
        "typical_p": _scalar_or_str, "xtc_probability": _num,
        "xtc_threshold": _num,
    },
}


# ------------------------------------------------------------------ loading

def resource_candidates():
    """Where the packaged resources may live: the frozen onefile extraction
    root first, then the package directory next to this module."""
    out = []
    base = getattr(sys, "_MEIPASS", None)  # PyInstaller onefile extraction root
    if base:
        out.append(Path(base) / "longform_core" / "resources")
    out.append(Path(__file__).resolve().parent / "resources")
    return out


def _resource_bytes(name):
    for d in resource_candidates():
        path = d / name
        try:
            if path.is_file():
                return path.read_bytes()
        except OSError as e:
            raise DefaultsError(f"the bundled {name} exists but could not be "
                                f"read ({type(e).__name__}); this "
                                "installation is incomplete") from None
    raise DefaultsError(f"the bundled {name} is missing from this "
                        "installation; new projects cannot receive their "
                        "defaults without it (reinstall longform)")


def _parse(name, data):
    try:
        return json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise DefaultsError(f"the bundled {name} is not valid JSON and "
                            "cannot be used") from None


# --------------------------------------------------------------- validation

def _fail(path, why):
    raise DefaultsError(f"the bundled defaults fail review validation: "
                        f"{path} {why}")


def _walk(schema, data, path):
    """Approved-field walk: unknown keys and wrong kinds fail with the field
    path and expected kind only, never a value."""
    if not isinstance(data, dict):
        _fail(path or "the resource", "is not a JSON object")
    for key, value in data.items():
        if key not in schema:
            _fail(f"{path}.{key}" if path else key,
                  "is not an approved field")
    for key, spec in schema.items():
        here = f"{path}.{key}" if path else key
        if key not in data:
            if isinstance(schema, _Optional):
                continue
            _fail(here, "is required")
        value = data[key]
        if isinstance(spec, dict):
            if not isinstance(value, dict):
                _fail(here, "must be an object")
            _walk(spec, value, here)
        else:
            check = _KINDS.get(spec, spec)
            if not callable(check):
                _fail(here, "has no validation rule (schema bug)")
            if not check(value):
                _fail(here, f"must satisfy the '{spec}' rule")


def validate_defaults(data):
    """Validate parsed ``project_defaults.json`` content; returns it."""
    _walk(_DEFAULTS_SCHEMA, data, "")
    for dotted, forced in FORCED_DEFAULTS:
        cur = data
        parts = dotted.split(".")
        for p in parts[:-1]:
            cur = cur[p]
        if cur[parts[-1]] != forced:
            _fail(dotted, "must hold the reviewed forced value")
    return data


def validate_preset(data):
    """Validate parsed bundled ``writer_preset.json`` content; returns it.

    Same approved-field policy as the defaults, plus the master-export
    structural requirement used for explicit imports.
    """
    if not isinstance(data, dict):
        _fail("the bundled preset", "is not a JSON object")
    for key in ("instruct", "context", "sysprompt", "preset"):
        if key not in data:
            _fail(key, "is required (not a SillyTavern master export)")
    _walk(_PRESET_SCHEMA, data, "")
    return data


# ------------------------------------------------------------------ public

def project_defaults():
    """A fresh validated copy of the reviewed new-project settings."""
    return copy.deepcopy(
        validate_defaults(_parse("project_defaults.json",
                                 _resource_bytes("project_defaults.json"))))


def writer_preset_bytes():
    """The reviewed bundled preset's exact bytes (validated before use)."""
    data = _resource_bytes("writer_preset.json")
    validate_preset(_parse("writer_preset.json", data))
    return data
