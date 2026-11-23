"""Smoke test: the longform launcher still exposes the pre-split public API.

longform.py is a thin PEP 723 launcher over the longform_core package
(ADR-0003); everything the single-file CLI exported must stay importable from
`longform` so tests and scripts keep working unchanged.
"""

import httpx
import time

import longform


def test_launcher_file_is_the_script():
    assert longform.__file__.endswith("longform.py")


def test_public_names_are_reexported():
    names = [
        "Api", "Project", "Tree", "Lore", "PromptInputs", "Progress",
        "DEFAULT_CONFIG", "DEFAULT_MODEL", "HttpErr", "NoAnswerErr",
        "check_report", "entry_triggered", "key_match", "name_variants",
        "card_png_json", "read_card_png", "parse_book", "parse_book_data",
        "layered_summary", "layered_summary_core", "writer_sampling",
        "render_story_string", "compose_writer_prompt", "build_writer_prompt",
        "clean_continuation", "extract_json_array", "extract_tagged",
        "split_bible", "join_bible", "warn", "die", "col", "now", "main",
    ]
    missing = [n for n in names if not hasattr(longform, n)]
    assert not missing, f"missing re-exports: {missing}"


def test_module_objects_are_shared():
    # conftest and tests patch longform.httpx / longform.time; the package
    # must use the very same module objects.
    assert longform.httpx is httpx
    assert longform.time is time
