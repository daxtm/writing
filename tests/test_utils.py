"""Tests for small text utilities: clean_continuation, split/join_bible, extractors."""

import longform


# --------------------------------------------------------------------------- clean_continuation


def clean(text, finish="stop", continuing=True):
    return longform.clean_continuation(text, finish, continuing)


def test_clean_strips_end_and_header_tokens():
    assert clean("text<|eot_id|>garbage") == ("text", False, False)
    assert clean("text<|start_header_id|>system junk") == ("text", False, False)


def test_clean_scene_end_marker_variants():
    for marker in ("[SCENE END]", "[scene end]", "[SCENE_END]", "[SCENE-END]", "[Scene  End]"):
        t, ended, trimmed = clean(f"story text {marker} trailing junk")
        assert (t, ended, trimmed) == ("story text", True, False), marker


def test_clean_scene_end_beats_length_trim():
    t, ended, trimmed = clean("Done sentence. [SCENE END] more", finish="length")
    assert (t, ended, trimmed) == ("Done sentence.", True, False)


def test_clean_length_trims_after_last_complete_sentence():
    t, ended, trimmed = clean("One sentence here. Second one. and unfinished", finish="length")
    assert (t, ended, trimmed) == ("One sentence here. Second one.", False, True)


def test_clean_length_keeps_all_when_no_late_sentence_end():
    body = "Ok. " + "z" * 100
    t, ended, trimmed = clean(body, finish="length")
    assert (t, ended, trimmed) == (body.rstrip(), False, False)


def test_clean_length_without_any_sentence_end_keeps_text():
    body = "words with no terminator at all"
    assert clean(body, finish="length") == (body, False, False)


def test_clean_collapses_blank_lines():
    t, ended, trimmed = clean("a\n\n\n\n\nb\n\n")
    assert (t, ended, trimmed) == ("a\n\nb", False, False)


def test_clean_leading_whitespace_depends_on_continuing():
    assert clean("   indented start") == ("   indented start", False, False)
    assert clean("   indented start", continuing=False) == ("indented start", False, False)


def test_clean_none_text():
    assert clean(None) == ("", False, False)


# --------------------------------------------------------------------------- bible split/join


def test_split_bible_preamble_and_sections():
    text = "# Story bible\n\nintro text\n\n## Title\nWorking title\n\n## Premise\nwho wants what"
    pre, secs = longform.split_bible(text)
    assert pre.strip() == "# Story bible\n\nintro text"
    assert secs == [("Title", "Working title"), ("Premise", "who wants what")]


def test_split_bible_empty_section_bodies():
    pre, secs = longform.split_bible("pre\n\n## A\n\n\n## B\nbody")
    assert pre.strip() == "pre"
    assert secs == [("A", ""), ("B", "body")]


def test_split_bible_no_headings():
    pre, secs = longform.split_bible("just some text")
    assert secs == [] and pre == "just some text"


def test_join_bible_normalizes_final_newline():
    assert longform.join_bible("# H\n", [("A", "x")]).endswith("\n")
    assert longform.join_bible("", []) == "\n"


def test_split_join_split_roundtrip():
    text = "pre\n\n## Title\na\n\n## Premise\nb"
    pre, secs = longform.split_bible(text)
    joined = longform.join_bible(pre, secs)
    pre2, secs2 = longform.split_bible(joined)
    assert (pre2, secs2) == (pre, secs)
    assert longform.join_bible(pre2, secs2) == joined


# --------------------------------------------------------------------------- extract_tagged


def test_extract_tagged_simple():
    assert longform.extract_tagged("<answer>hi</answer>", "answer") == ("hi", True)


def test_extract_tagged_uses_last_complete_pair():
    text = "mentions <answer> decoy <answer>real thing</answer> done"
    assert longform.extract_tagged(text, "answer") == ("real thing", True)


def test_extract_tagged_unfinished_final_open():
    assert longform.extract_tagged("prefix <answer>cut off", "answer") == ("cut off", False)


def test_extract_tagged_absent_tags_returns_all_text():
    assert longform.extract_tagged("  plain text  ", "answer") == ("plain text", False)


def test_extract_tagged_case_insensitive():
    assert longform.extract_tagged("<ANSWER>x</ANSWER>", "answer") == ("x", True)


def test_extract_tagged_none_text():
    assert longform.extract_tagged(None, "answer") == ("", False)


# --------------------------------------------------------------------------- extract_json_array


def test_extract_json_array_plain():
    assert longform.extract_json_array("data [1, 2, 3] end") == [1, 2, 3]


def test_extract_json_array_fenced():
    text = "```json\n[{\"chapter\": 1}]\n```"
    assert longform.extract_json_array(text) == [{"chapter": 1}]


def test_extract_json_array_tagged():
    assert longform.extract_json_array("<scenes>[1, 2]</scenes> trailing") == [1, 2]


def test_extract_json_array_empty_list():
    assert longform.extract_json_array("[]") == []


def test_extract_json_array_malformed():
    assert longform.extract_json_array("no brackets here") is None
    assert longform.extract_json_array("[1, 2") is None


def test_extract_json_array_non_array_json():
    assert longform.extract_json_array('{"a": 1}') is None


def test_extract_json_array_array_with_leading_prose_fails_to_parse():
    # a stray '[' before the real array makes the slice invalid JSON: None (existing behavior)
    assert longform.extract_json_array("[1] then [\"two\"] after") is None
    assert longform.extract_json_array("say [\"two\"] after") == ["two"]
