"""Deterministic banned-phrase / n-gram report."""

import re

STOP = set("the a an and or but of to in on at for with as by from that this it is was were be been he she they "
           "his her their i you we my your our him them its not no so then than there".split())


def check_report(scene_texts, banned_phrases, n, min_count, top, title):
    """Pure report calculation for cmd_check. scene_texts is an ordered list of
    (scene_id, [(node_id, node_text), ...], joined_active_text) tuples; only nodes on the
    active chain are supplied and joined_active_text is Tree.text() so separator behavior is
    unchanged. title is the full first line including the timestamp. Returns the complete
    report with its final newline."""
    lines = [title, "", "## Banned phrases", ""]
    counts, where = {}, {}
    hits = 0
    for sid, nodes, joined in scene_texts:
        for nid, t in nodes:
            for b in banned_phrases:
                for m in re.finditer(re.escape(b), t, re.I):
                    hits += 1
                    a, z = max(0, m.start() - 50), min(len(t), m.end() + 50)
                    snippet = re.sub(r"\s+", " ", t[a:z])
                    lines.append(f'- {sid}/{nid}: "{b}" ... {snippet} ...')
        toks = re.findall(r"[a-z']+", joined.lower())
        for k in range(len(toks) - n + 1):
            g = tuple(toks[k: k + n])
            if sum(1 for w in g if w in STOP) >= n - 1:
                continue
            counts[g] = counts.get(g, 0) + 1
            where.setdefault(g, set()).add(sid)
    if not hits:
        lines.append("(none)")
    lines += ["", f"## Repeated {n}-grams (count >= {min_count})", ""]
    rep = sorted(((c, g) for g, c in counts.items() if c >= min_count), reverse=True)[:top]
    if rep:
        for c, g in rep:
            lines.append(f'- {c}x "{" ".join(g)}" in {", ".join(sorted(where[g]))}')
    else:
        lines.append("(none)")
    return "\n".join(lines) + "\n"

