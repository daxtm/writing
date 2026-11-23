"""Tests for the branching Tree: add/chain/separators/delete/save-reload, all via tmp_path."""

from pathlib import Path

import pytest

import longform


class FakeProject:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def f(self, *parts):
        return self.root.joinpath(*parts)


@pytest.fixture
def proj(tmp_path):
    p = FakeProject(tmp_path / "proj")
    (p.f("trees")).mkdir(exist_ok=True)
    return p


def new_tree(proj, sid="s001"):
    return longform.Tree(proj, sid)


def test_tree_add_and_head(proj):
    t = new_tree(proj)
    assert t.head is None
    n1 = t.add(None, "First.")
    n2 = t.add(n1, "Second.")
    assert (n1, n2) == ("n1", "n2")
    t.head = n2
    assert t.head == "n2"
    assert t.chain() == ["n1", "n2"]


def test_tree_children_numeric_ordering(proj):
    t = new_tree(proj)
    root_id = t.add(None, "root.")
    t.add(root_id, "a")
    for _ in range(8):
        t.add(root_id, "more")
    t.add(root_id, "last")
    assert t.children(root_id) == [f"n{k}" for k in range(2, 12)]


def test_tree_chain_from_explicit_node_selects_branch(proj):
    t = new_tree(proj)
    n1 = t.add(None, "base.")
    n2 = t.add(n1, "left.")
    t.add(n1, "right.")
    n4 = t.add(n2, "leaf.")
    t.head = n4
    assert t.chain() == ["n1", "n2", "n4"]
    assert t.chain("n3") == ["n1", "n3"]


def test_tree_text_default_separator(proj):
    t = new_tree(proj)
    n1 = t.add(None, "  First.")  # leading whitespace of the first node is stripped
    n2 = t.add(n1, "Second.", sep="\n\n")
    t.head = n2
    assert t.text() == "First.\n\nSecond."


def test_tree_text_empty_separator_no_auto_space_mid_sentence(proj):
    t = new_tree(proj)
    n1 = t.add(None, "walking,")
    n2 = t.add(n1, "then stopped", sep="")
    t.head = n2
    assert t.text() == "walking,then stopped"


def test_tree_text_empty_separator_auto_space_after_sentence(proj):
    t = new_tree(proj)
    n1 = t.add(None, "He spoke!")
    n2 = t.add(n1, "Then left.", sep="")
    t.head = n2
    assert t.text() == "He spoke! Then left."


def test_tree_text_empty_separator_keeps_leading_space(proj):
    t = new_tree(proj)
    n1 = t.add(None, "He spoke!")
    n2 = t.add(n1, " then left.", sep="")
    t.head = n2
    assert t.text() == "He spoke! then left."


def test_tree_text_custom_separator(proj):
    t = new_tree(proj)
    n1 = t.add(None, "One.")
    n2 = t.add(n1, "Two.", sep=" --- ")
    t.head = n2
    assert t.text() == "One. --- Two."


def test_tree_delete_refuses_non_leaf(proj):
    t = new_tree(proj)
    n1 = t.add(None, "base.")
    t.add(n1, "child.")
    assert t.delete(n1) is False
    assert "n1" in t.d["nodes"]


def test_tree_delete_leaf_rewinds_head(proj):
    t = new_tree(proj)
    n1 = t.add(None, "base.")
    n2 = t.add(n1, "child.")
    t.head = n2
    assert t.delete(n2) is True
    assert t.head == "n1"
    assert t.delete(n1) is True
    assert t.head is None


def test_tree_delete_keeps_head_on_sibling(proj):
    t = new_tree(proj)
    n1 = t.add(None, "base.")
    n2 = t.add(n1, "a.")
    t.head = n2
    t.add(n1, "b.")  # n3
    assert t.delete("n3") is True
    assert t.head == "n2"


def test_tree_save_and_reload_roundtrip(proj):
    t = new_tree(proj, sid="sX")
    n1 = t.add(None, "base.")
    n2 = t.add(n1, "child.", source="model")
    t.head = n2
    t.d["steer"] = "go slow"
    t.save()
    assert list(proj.f("trees").glob("*.tmp")) == [], "save must not leave temp files"
    t2 = longform.Tree(proj, "sX")
    assert t2.d == t.d
    assert t2.text() == "base.\n\nchild."


def test_tree_empty_file_defaults(proj):
    t = new_tree(proj)
    assert t.d == {"nodes": {}, "head": None, "counter": 0}
    assert t.chain() == [] and t.text() == ""
