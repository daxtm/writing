#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.27", "pyside6>=6.12.0,<6.13"]
# ///
"""longform.py - plan-then-collaborate longform fiction pipeline for Featherless.

Writer: text completion (/v1/completions) driven by a SillyTavern master-export preset
(instruct + context + sysprompt + samplers). Planner/summarizer/critic/editor: chat completions.

Every command is its own step. No command runs another one for you.

  init DIR [--preset FILE]     create a project folder; --preset copies a SillyTavern preset in as writer_preset.json
  limits DIR                   fetch your plan + model context limits from Featherless -> limits.json
  bible DIR                    answer fixed questions per section; your answers go into bible.md as written
  outline DIR [--n N]          generate N competing outlines, pick one -> outline.md
  scenes DIR [--force]         break outline.md into scene cards -> scenes.json
  draft DIR [--scene ID]       interactive drafting loop (swipes, steer, edit, rewind, branches, lorebook toggles)
  update-state DIR [--scene ID] [--summary-only]
                               summarize a finished scene and update state.md
  compress DIR --from ID --to ID
                               condense a run of scene summaries into one arc summary
  critique DIR --scene ID      critic-model review of a scene -> critiques/ID.md
  check DIR [--scene ID]       deterministic banned-phrase + repeated n-gram report -> checks/ID.md
  revise DIR --scene ID        passage-by-passage line edit using critiques/ID.md and/or checks/ID.md
  status DIR                   project overview
  export DIR [--out FILE]      write manuscript.md
  gui [DIR]                    native Wayland window: saved branches, notes, per-scene steering
                               (DIR defaults to the current directory; running with no command opens it)

API key: "api_key" in project.json, or else the environment variable named by "api_key_env"
(default: export FEATHERLESS_API_KEY=...).

Lorebooks: put SillyTavern World Info JSON files, or character cards (V1/V2/V3, as .png or .json) in
DIR/lorebooks/. A card becomes a character lorebook: its description + personality as one entry keyed on
the character's name, plus any embedded character_book entries. Toggle them and mark character books inside the draft loop (lb).
"""

# Thin PEP 723 launcher: the implementation lives in the longform_core package
# (see docs/adr/0003-split-into-package.md). Everything public is re-exported
# here so `import longform` keeps working exactly as before the split.

import httpx  # noqa: F401  (re-exported: tests monkeypatch longform.httpx)
import time   # noqa: F401  (re-exported: tests monkeypatch longform.time)

from longform_core import api  # noqa: F401  (module handle for test monkeypatching)
from longform_core.cli import *        # noqa: F401,F403
from longform_core.api import *        # noqa: F401,F403
from longform_core.checks import *     # noqa: F401,F403
from longform_core.commands import *   # noqa: F401,F403
from longform_core.config import *     # noqa: F401,F403
from longform_core.lore import *       # noqa: F401,F403
from longform_core.project import *    # noqa: F401,F403
from longform_core.prompt import *     # noqa: F401,F403
from longform_core.tree import *       # noqa: F401,F403
from longform_core.utils import *      # noqa: F401,F403


if __name__ == "__main__":
    try:
        code = main()
    except KeyboardInterrupt:
        print("\naborted")
        sys.exit(130)
    except (HttpErr, NoAnswerErr) as e:
        die(str(e))
    sys.exit(code or 0)
