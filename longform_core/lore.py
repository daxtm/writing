"""Lorebooks: card parsing, matching, assembly."""

import base64
import json
import re
import zlib
from pathlib import Path

from .utils import name_re, read_json, warn, write_json

def card_png_json(data):
    """Card JSON from PNG bytes (tEXt/iTXt chunk 'ccv3' preferred, then 'chara'); None if absent."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos, found = 8, {}
    while pos + 8 <= len(data):
        length = int.from_bytes(data[pos:pos + 4], "big")
        ctype = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"tEXt":
            key, _, val = body.partition(b"\x00")
            found[key.decode("latin-1").lower()] = val
        elif ctype == b"iTXt":
            key, _, rest = body.partition(b"\x00")
            if len(rest) < 2:
                continue
            compressed, rest = rest[0], rest[2:]
            _lang, _, rest = rest.partition(b"\x00")
            _tkey, _, val = rest.partition(b"\x00")
            try:
                found[key.decode("latin-1").lower()] = zlib.decompress(val) if compressed else val
            except zlib.error:
                continue
        elif ctype == b"IEND":
            break
    for key in ("ccv3", "chara"):
        if key in found:
            try:
                return json.loads(base64.b64decode(found[key]).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                continue
    return None


def read_card_png(path):
    """Card JSON from a SillyTavern character PNG file; None if the file holds no card data."""
    return card_png_json(Path(path).read_bytes())


def card_fields(d):
    """The character fields of a V2/V3 card (under 'data') or a V1 card (top level); None if not a card."""
    if not isinstance(d, dict):
        return None
    if isinstance(d.get("data"), dict) and ("name" in d["data"] or "character_book" in d["data"]):
        return d["data"]
    if "name" in d and ("description" in d or "personality" in d) and "entries" not in d:
        return d
    return None


def parse_book_data(d, stem):
    """Pure parse of card/World Info data (as read from a file) into (card_name, entries).

    Accepts a V2/V3 character card (under 'data'), a V1 card (top level), a World
    Info export with an 'entries' mapping, or a bare list/dict of entries.
    """
    card = card_fields(d)
    card_name, raw, synth = None, [], []
    if card is not None:
        card_name = (card.get("name") or stem).strip()
        raw = (card.get("character_book") or {}).get("entries", [])
        desc = (card.get("description") or "").strip()
        pers = (card.get("personality") or "").strip()
        content = desc + (("\n\nPersonality: " + pers) if pers else "")
        if content.strip():
            keys = [card_name] + ([card_name.split()[0]] if len(card_name.split()) > 1 else [])
            synth.append({"name": "card description", "keys": keys, "secondary": [], "content": content,
                          "enabled": True, "constant": False, "selective": False, "logic": 0, "order": 100,
                          "before": False, "case": None, "whole": None})
    elif isinstance(d, dict) and "entries" in d:
        raw = d["entries"]
    elif isinstance(d, list):
        raw = d
    if isinstance(raw, dict):
        raw = list(raw.values())
    out = []
    for e in raw:
        if not isinstance(e, dict):
            continue

        def keylist(v):
            if isinstance(v, str):
                v = v.split(",")
            return [str(k).strip() for k in (v or []) if str(k).strip()]

        pos = e.get("position", 0)
        out.append({
            "name": e.get("comment") or e.get("name") or "",
            "keys": keylist(e.get("key", e.get("keys", []))),
            "secondary": keylist(e.get("keysecondary", e.get("secondary_keys", []))),
            "content": e.get("content") or "",
            "enabled": bool(e.get("enabled", True)) and not bool(e.get("disable", False)),
            "constant": bool(e.get("constant", False)),
            "selective": bool(e.get("selective", False)),
            "logic": int(e.get("selectiveLogic", 0) or 0),
            "order": int(e.get("order", e.get("insertion_order", 100)) or 100),
            "before": pos in (0, "before_char"),
            "case": e.get("caseSensitive", e.get("case_sensitive")),
            "whole": e.get("matchWholeWords"),
        })
    return card_name, synth + out


def parse_book(path):
    """Read a SillyTavern World Info export, a character card (.png or .json), or a bare entry list."""
    path = Path(path)
    if path.suffix.lower() == ".png":
        d = read_card_png(path)
        if d is None:
            warn(f"{path.name}: no character card data found in this PNG")
            return None, []
    else:
        d = read_json(path, {})
    return parse_book_data(d, path.stem)


def key_match(key, hay, case, whole):
    m = re.fullmatch(r"/(.+)/([a-z]*)", key)
    if m:
        try:
            return re.search(m.group(1), hay, re.I if "i" in m.group(2) else 0) is not None
        except re.error:
            return False
    pat = name_re(key) if whole else re.escape(key)
    return re.search(pat, hay, 0 if case else re.I) is not None


def entry_triggered(e, hay, whole_default):
    case = bool(e["case"]) if e["case"] is not None else False
    whole = e["whole"] if isinstance(e["whole"], bool) else whole_default
    if not any(key_match(k, hay, case, whole) for k in e["keys"]):
        return False
    if e["selective"] and e["secondary"]:
        hits = [key_match(k, hay, case, whole) for k in e["secondary"]]
        return {0: any(hits), 1: not all(hits), 2: not any(hits), 3: all(hits)}.get(e["logic"], any(hits))
    return True


def name_variants(name, aliases):
    out = [name] + [a for a in aliases if a]
    if name and len(name.split()) > 1:
        out.append(name.split()[0])
    return [v for v in out if v]


def is_present(name, aliases, present):
    blob = " | ".join(present or [])
    return any(re.search(name_re(v), blob, re.I) for v in name_variants(name, aliases))


def pov_name(sc):
    present = sc.get("characters") or []
    pov = (sc.get("pov") or "").strip()
    for c in present:
        if pov and re.search(name_re(c), pov, re.I):
            return c
    for c in present:
        first = c.split()[0] if c.split() else c
        if pov and first and re.search(name_re(first), pov, re.I):
            return c
    if pov and len(pov.split()) <= 3 and not re.search(r"person|third|first|second|omniscient|close|limited|pov", pov, re.I):
        return pov
    return present[0] if present else "Narrator"


class Lore:
    def __init__(self, p, scenes):
        self.p = p
        self.dir = p.f("lorebooks")
        self.reg_path = p.f("lorebooks.json")
        self.reg = read_json(self.reg_path, {"books": {}})
        self.cache = {}
        self.sync(scenes)

    def sync(self, scenes):
        self.dir.mkdir(exist_ok=True)
        known = []
        for s in scenes:
            known += s.get("characters") or []
        changed = False
        for path in sorted(p for p in self.dir.iterdir() if p.suffix.lower() in (".json", ".png")):
            if path.name in self.reg["books"]:
                continue
            card_name, entries = parse_book(path)
            meta = {"on": False, "kind": "world", "character": "", "aliases": []}
            if card_name:
                meta.update(kind="character", character=card_name)
            else:
                stem = re.sub(r"[^a-z0-9]+", " ", path.stem.lower()).split()
                for name in known:
                    toks = name.lower().split()
                    if stem and toks and stem[0] == toks[0]:
                        meta.update(kind="character", character=name)
                        break
            self.reg["books"][path.name] = meta
            changed = True
            print(f"new lorebook {path.name}: {meta['kind']}{' ' + meta['character'] if meta['character'] else ''}, {len(entries)} entries, off")
        if changed:
            self.save()

    def save(self):
        write_json(self.reg_path, self.reg)

    def books(self):
        return [(n, m) for n, m in sorted(self.reg["books"].items()) if (self.dir / n).exists()]

    def entries(self, fname):
        if fname not in self.cache:
            self.cache[fname] = parse_book(self.dir / fname)[1]
        return self.cache[fname]

    def char_name(self, fname, meta):
        return meta.get("character") or Path(fname).stem

    def active(self):
        return [n for n, m in self.books() if m.get("on")]

    def absent_mentions(self, sc, text):
        present = sc.get("characters") or []
        out = set()
        for fname, meta in self.books():
            if meta.get("kind") != "character":
                continue
            name = self.char_name(fname, meta)
            aliases = meta.get("aliases", [])
            if is_present(name, aliases, present):
                continue
            if any(re.search(name_re(v), text, re.I) for v in name_variants(name, aliases)):
                out.add(name)
        return sorted(out)


def assemble_lore(p, lore, sc, hay, budget, model, pov, user):
    """Returns story-string fields (wiBefore, description, wiAfter), detail lines, skipped count."""
    rc = p.cfg["roles"]["writer"]
    present = sc.get("characters") or []
    mode = rc.get("absent_character_lore", "reference")
    whole_default = bool(rc.get("lore_match_whole_words", True))
    rank = {"description": 0, "present": 1, "wiBefore": 2, "wiAfter": 2, "absent": 3}
    cands, detail = [], []
    for fname, meta in lore.books():
        if not meta.get("on"):
            continue
        kind = meta.get("kind", "world")
        cname = lore.char_name(fname, meta) if kind == "character" else ""
        if kind == "character":
            aliases = meta.get("aliases", [])
            if is_present(cname, aliases, [pov]):
                section = "description"
            elif is_present(cname, aliases, present):
                section = "present"
            elif mode == "exclude":
                detail.append(f"skipped {fname}: {cname} not in scene (absent_character_lore=exclude)")
                continue
            else:
                section = "absent"
        for e in lore.entries(fname):
            if not e["enabled"] or not e["content"].strip():
                continue
            hit = entry_triggered(e, hay, whole_default)
            if kind == "character" and section == "absent":
                if not hit:
                    continue  # an absent character's constant entries never load
            elif not (e["constant"] or hit):
                continue
            sec = section if kind == "character" else ("wiBefore" if e["before"] else "wiAfter")
            content = e["content"].replace("{{char}}", cname or pov).replace("{{user}}", user)
            label = e["name"] or (e["keys"][0] if e["keys"] else "?")
            cands.append({"sec": sec, "prio": (rank[sec], 0 if e["constant"] else 1, -e["order"]),
                          "order": e["order"], "content": content.strip(), "book": fname, "label": label, "char": cname})
    cands.sort(key=lambda c: c["prio"])
    used, picked, skipped = 0, [], 0
    for c in cands:
        t = p.est(model, c["content"])
        if used + t > budget:
            skipped += 1
            continue
        used += t
        picked.append(c)
        detail.append(f"{c['sec']:<11} {c['book']} / {c['label']}")

    def join(secs, fmt=lambda c: c["content"]):
        items = sorted((c for c in picked if c["sec"] in secs), key=lambda c: c["order"])
        return "\n".join(fmt(c) for c in items)

    absent = join({"absent"}, lambda c: f"[{c['char']}] {c['content']}")
    after = "\n".join(x for x in (join({"present"}), join({"wiAfter"})) if x)
    if absent:
        after = (after + "\n\n" if after else "") + (
            "The following characters are NOT in this scene. Reference only: they must not appear, speak or act on the page.\n"
            + absent)
    fields = {"wiBefore": join({"wiBefore"}), "description": join({"description"}), "wiAfter": after}
    return fields, detail, skipped

