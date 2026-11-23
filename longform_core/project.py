"""Project state on disk."""

import json
from pathlib import Path

from .config import DEFAULT_CONFIG, LOCK
from .utils import deep_merge, die, read_json, write_json

class Project:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        if not (self.root / "project.json").exists():
            die(f"no project.json in {self.root} (run: init {self.root})")
        self.cfg = deep_merge(DEFAULT_CONFIG, read_json(self.root / "project.json", {}))

    def f(self, *parts):
        return self.root.joinpath(*parts)

    def scenes(self):
        return read_json(self.f("scenes.json"), [])

    def save_scenes(self, scenes):
        write_json(self.f("scenes.json"), scenes)

    def scene_index(self, scenes, sid):
        for i, s in enumerate(scenes):
            if s["id"] == sid:
                return i
        die(f"no scene with id {sid}")

    def summaries(self):
        return read_json(self.f("summaries.json"), {"scenes": {}, "arcs": []})

    def save_summaries(self, d):
        write_json(self.f("summaries.json"), d)

    # tokens
    def ratio(self, model):
        c = read_json(self.f("calib.json"), {}).get(model)
        if c and c.get("tokens", 0) > 500:
            return c["chars"] / c["tokens"]
        return float(self.cfg["chars_per_token_default"])

    def est(self, model, text):
        return int(len(text or "") / self.ratio(model)) + 1

    def record_calib(self, model, chars, tokens):
        if not tokens:
            return
        with LOCK:
            d = read_json(self.f("calib.json"), {})
            c = d.get(model, {"chars": 0, "tokens": 0})
            c["chars"] += chars
            c["tokens"] += tokens
            d[model] = c
            write_json(self.f("calib.json"), d)

    def ceiling(self, model):
        fb = int(self.cfg["max_context_fallback"])
        lim = read_json(self.f("limits.json"), None)
        if not lim:
            return fb, None, "max_context_fallback (no limits.json; run: limits)"
        plan_max = (lim.get("plan") or {}).get("max_context_length")
        m = (lim.get("models") or {}).get(model) or {}
        vals = [v for v in (plan_max, m.get("context")) if isinstance(v, int) and v > 0]
        mc = m.get("max_completion") if isinstance(m.get("max_completion"), int) else None
        if not vals:
            return fb, mc, "max_context_fallback (limits.json has no value for this model)"
        return min(vals), mc, "limits.json"

    def log_call(self, rec):
        with LOCK:
            with open(self.f("calls.jsonl"), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # writer preset
    def preset_path(self):
        p = Path(self.cfg["roles"]["writer"]["preset"]).expanduser()
        return p if p.is_absolute() else self.f(str(p))

    def preset(self):
        path = self.preset_path()
        if not path.exists():
            die(f"writer preset not found: {path} (copy your SillyTavern preset there, or run: init {self.root} --preset FILE)")
        d = read_json(path)
        for k in ("instruct", "context", "sysprompt", "preset"):
            if k not in d:
                die(f"{path} is not a SillyTavern master export (missing '{k}')")
        d = json.loads(json.dumps(d))
        d["preset"].update(self.cfg["roles"]["writer"].get("preset_overrides") or {})
        return d

    def writer_ceiling(self, preset):
        model = self.cfg["roles"]["writer"]["model"]
        ceil, mc, src = self.ceiling(model)
        ml = preset["preset"].get("max_length")
        if isinstance(ml, int) and 0 < ml < ceil:
            return ml, mc, f"preset max_length (below {src} value {ceil})"
        return ceil, mc, src

