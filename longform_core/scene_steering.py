"""Per-scene tree-level steering persistence (Qt-independent).

The GUI shell's narrow write boundary: reads and writes only the top-level
`steer` field of trees/<scene>.json, only for a scene that has a card in
scenes.json, and only through paths safe under one canonical root. Baselines
capture the exact tree source bytes (or absence) plus the scene card from
when editing began; a save against a different baseline is refused as stale.
This is stale-input detection, not a lock: concurrent CLI/GUI writers remain
unsupported.
"""

import json
from dataclasses import dataclass

from .reader_model import _ID_RE, _canonical, _no_symlink_below
from .utils import write_json

DEFAULT_TREE = {"nodes": {}, "head": None, "counter": 0}


class SteeringError(Exception):
    """Sanitized steering failure; the message uses relative source names only."""


@dataclass(frozen=True)
class Baseline:
    """Opaque edit baseline: scene-card identity + exact tree bytes/absence."""

    scenes_card: dict
    tree_bytes: bytes | None  # None = the tree file did not exist


@dataclass
class SteeringState:
    """What the editor may show for one scene."""

    scene_id: str | None
    text: str | None          # saved steering; None when not editable
    baseline: Baseline | None
    editable: bool
    reason: str | None        # sanitized explanation when not editable


@dataclass
class SaveOutcome:
    ok: bool
    reason: str | None = None
    stale: bool = False       # baseline conflict: offer Reload / Keep editing
    baseline: Baseline | None = None  # the new baseline after a successful save


def _scenes_card(root, scene_id):
    path = root / "scenes.json"
    if not path.exists():
        raise SteeringError("scenes.json is missing")
    try:
        data = json.loads(path.read_bytes().decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        raise SteeringError("scenes.json could not be read")
    if not isinstance(data, list):
        raise SteeringError("scenes.json has an unexpected structure")
    for card in data:
        if isinstance(card, dict) and card.get("id") == scene_id:
            return card
    raise SteeringError(f"scene {scene_id} has no card in scenes.json")


def _tree_path(root, scene_id):
    rel = ("trees", f"{scene_id}.json")
    if not _no_symlink_below(root, *rel):
        raise SteeringError(f"trees/{scene_id}.json is a symlink; "
                            "steering is read-only")
    return root.joinpath(*rel)


def _tree_bytes(root, scene_id):
    path = _tree_path(root, scene_id)
    try:
        return path.read_bytes() if path.exists() else None
    except OSError:
        raise SteeringError(f"trees/{scene_id}.json could not be read; "
                            "steering is read-only")


def _parse_tree(raw_bytes, scene_id):
    if raw_bytes is None:
        return dict(DEFAULT_TREE)
    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise SteeringError(f"trees/{scene_id}.json is not valid JSON; "
                            "steering is read-only")
    if not isinstance(data, dict) or not isinstance(data.get("nodes"), dict):
        raise SteeringError(f"trees/{scene_id}.json has an unexpected "
                            "structure; steering is read-only")
    return data


def _state(scene_id, text, baseline, editable, reason):
    return SteeringState(scene_id=scene_id, text=text, baseline=baseline,
                         editable=editable, reason=reason)


def load(root, scene_id) -> SteeringState:
    """Read one scene's steering plus a safe edit baseline (no writes)."""
    root = _canonical(root)
    if not isinstance(scene_id, str) or not _ID_RE.match(scene_id):
        return _state(scene_id if isinstance(scene_id, str) else None, None,
                      None, False, "unsafe scene id; steering is read-only")
    try:
        card = _scenes_card(root, scene_id)
        raw_bytes = _tree_bytes(root, scene_id)
        data = _parse_tree(raw_bytes, scene_id)
    except SteeringError as e:
        return _state(scene_id, None, None, False, str(e))
    baseline = Baseline(scenes_card=card, tree_bytes=raw_bytes)
    steer = data.get("steer", "")
    if not isinstance(steer, str):
        return _state(scene_id, None, baseline, False,
                      f"trees/{scene_id}.json steering is not text; "
                      "steering is read-only")
    return _state(scene_id, steer, baseline, True, None)


def save(root, scene_id, text, baseline) -> SaveOutcome:
    """Persist `text` as the scene's tree-level steering.

    Refuses stale baselines, changed scene cards, unsafe paths, and damaged
    trees before any write; on success returns the baseline of the saved
    bytes. Only the top-level `steer` field is set; every other field is
    preserved as-is.
    """
    if baseline is None:
        return SaveOutcome(ok=False, reason="no saved baseline; reload the "
                                            "scene before saving")
    if not isinstance(text, str):
        return SaveOutcome(ok=False, reason="steering text must be plain text")
    root = _canonical(root)
    if not isinstance(scene_id, str) or not _ID_RE.match(scene_id):
        return SaveOutcome(ok=False, reason="unsafe scene id; not saved")
    try:
        card = _scenes_card(root, scene_id)
    except SteeringError as e:
        return SaveOutcome(ok=False, reason=str(e))
    if card != baseline.scenes_card:
        return SaveOutcome(ok=False, stale=True,
                           reason=f"the scene card for {scene_id} changed on "
                                  "disk since editing began")
    try:
        path = _tree_path(root, scene_id)
        raw_bytes = _tree_bytes(root, scene_id)
    except SteeringError as e:
        return SaveOutcome(ok=False, reason=str(e))
    if raw_bytes != baseline.tree_bytes:
        return SaveOutcome(ok=False, stale=True,
                           reason=f"saved steering for {scene_id} changed on "
                                  "disk since editing began")
    try:
        data = _parse_tree(raw_bytes, scene_id)
    except SteeringError as e:
        return SaveOutcome(ok=False, reason=str(e))
    data["steer"] = text
    try:
        write_json(path, data)
    except OSError:
        return SaveOutcome(ok=False,
                           reason=f"trees/{scene_id}.json could not be written")
    saved = (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return SaveOutcome(ok=True, baseline=Baseline(scenes_card=card,
                                                  tree_bytes=saved))
