"""Branching draft tree."""

from .utils import now, read_json, write_json

class Tree:
    """Branching passage tree. Each node has `sep`: the text placed between it and its parent.
    Text-completion continuations use sep "" and keep their own leading whitespace."""

    def __init__(self, p, sid):
        self.path = p.f("trees", f"{sid}.json")
        self.d = read_json(self.path, {"nodes": {}, "head": None, "counter": 0})

    @property
    def head(self):
        return self.d["head"]

    @head.setter
    def head(self, nid):
        self.d["head"] = nid

    def node(self, nid):
        return self.d["nodes"][nid]

    def add(self, parent, text, **meta):
        self.d["counter"] += 1
        nid = f"n{self.d['counter']}"
        self.d["nodes"][nid] = {"id": nid, "parent": parent, "text": text, "created": now(), "history": [], **meta}
        return nid

    def children(self, nid):
        kids = [n for n in self.d["nodes"].values() if n["parent"] == nid]
        return [n["id"] for n in sorted(kids, key=lambda n: int(n["id"][1:]))]

    def chain(self, nid="__head__"):
        nid = self.head if nid == "__head__" else nid
        out = []
        while nid is not None:
            out.append(nid)
            nid = self.d["nodes"][nid]["parent"]
        return list(reversed(out))

    def text(self, nid="__head__"):
        out = ""
        for k, i in enumerate(self.chain(nid)):
            n = self.d["nodes"][i]
            t = n["text"]
            if k == 0:
                out = t.lstrip()
                continue
            sep = n.get("sep", "\n\n")
            if sep == "" and t and not t[0].isspace() and out and out[-1] in ".!?…\"'”’*":
                sep = " "
            out += sep + (t if sep == "" or sep == " " else t.lstrip())
        return out

    def delete(self, nid):
        if self.children(nid):
            return False
        if self.head == nid:
            self.head = self.d["nodes"][nid]["parent"]
        del self.d["nodes"][nid]
        return True

    def save(self):
        write_json(self.path, self.d)

