"""Tests for lorebook key matching: key_match, entry_triggered, name_variants."""

import longform


# --------------------------------------------------------------------------- key_match


def km(key, hay, case=None, whole=None):
    return longform.key_match(key, hay, case, whole)


def test_key_match_literal_case_insensitive_by_default():
    assert km("Alice", "alice went home") is True
    assert km("alice", "ALICE went home") is True


def test_key_match_case_sensitive():
    assert km("Alice", "alice", case=True) is False
    assert km("alice", "alice", case=True) is True


def test_key_match_whole_words():
    assert km("cat", "concatenate the files", whole=True) is False
    assert km("cat", "a cat sat", whole=True) is True
    assert km("cat", "concatenate the files", whole=False) is True


def test_key_match_literal_is_substring():
    assert km("ann", "channel", whole=False) is True


def test_key_match_regex_key():
    assert km(r"/ab+c/", "x abbbc y") is True
    assert km(r"/AB+C/", "abbc") is False
    assert km(r"/AB+C/i", "abbc") is True


def test_key_match_invalid_regex_is_false():
    assert km(r"/ab[/", "abc") is False


# --------------------------------------------------------------------------- entry_triggered


def entry(keys, secondary=(), selective=False, logic=0, case=None, whole=None):
    return {
        "keys": keys, "secondary": list(secondary), "selective": selective, "logic": logic,
        "case": case, "whole": whole,
    }


def test_entry_triggered_primary_key_hit():
    assert longform.entry_triggered(entry(["Alice"]), "alice speaks", True) is True
    assert longform.entry_triggered(entry(["Alice", "Bob"]), "bob speaks", True) is True


def test_entry_triggered_no_primary_key():
    assert longform.entry_triggered(entry(["Alice"]), "bob speaks", True) is False


def test_entry_triggered_non_selective_ignores_secondary():
    assert longform.entry_triggered(entry(["Alice"], ["missing"]), "alice speaks", True) is True


def test_entry_triggered_selective_without_secondary():
    assert longform.entry_triggered(entry(["Alice"], [], selective=True), "alice speaks", True) is True


def test_entry_triggered_logic_any_default():
    e = entry(["Alice"], ["Bob"], selective=True, logic=0)
    assert longform.entry_triggered(e, "alice meets bob", True) is True
    assert longform.entry_triggered(e, "alice alone", True) is False


def test_entry_triggered_logic_not_all():
    e = entry(["Alice"], ["Bob", "Cara"], selective=True, logic=1)
    assert longform.entry_triggered(e, "alice meets bob", True) is True
    assert longform.entry_triggered(e, "alice meets bob and cara", True) is False


def test_entry_triggered_logic_not_any():
    e = entry(["Alice"], ["Bob", "Cara"], selective=True, logic=2)
    assert longform.entry_triggered(e, "alice alone", True) is True
    assert longform.entry_triggered(e, "alice meets cara", True) is False


def test_entry_triggered_logic_all():
    e = entry(["Alice"], ["Bob", "Cara"], selective=True, logic=3)
    assert longform.entry_triggered(e, "alice meets bob and cara", True) is True
    assert longform.entry_triggered(e, "alice meets bob", True) is False


def test_entry_triggered_unknown_logic_falls_back_to_any():
    e = entry(["Alice"], ["Bob"], selective=True, logic=9)
    assert longform.entry_triggered(e, "alice meets bob", True) is True


def test_entry_triggered_case_and_whole_from_entry():
    assert longform.entry_triggered(entry(["Alice"], case=True), "alice", True) is False
    assert longform.entry_triggered(entry(["cat"], whole=False), "concatenate", True) is True
    assert longform.entry_triggered(entry(["cat"], whole=None), "concatenate", False) is True


# --------------------------------------------------------------------------- name_variants


def test_name_variants_aliases():
    assert longform.name_variants("Alice", ["Red", ""]) == ["Alice", "Red"]


def test_name_variants_first_name_appended_last():
    assert longform.name_variants("Alice Baker", ["Baker"]) == ["Alice Baker", "Baker", "Alice"]


def test_name_variants_single_word():
    assert longform.name_variants("Alice", []) == ["Alice"]


def test_name_variants_empty_name():
    assert longform.name_variants("", []) == []


def test_name_variants_preserves_duplicates_and_order():
    assert longform.name_variants("Alice", ["Alice", "Al"]) == ["Alice", "Alice", "Al"]
