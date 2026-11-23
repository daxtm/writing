#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27"]
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
  gui DIR                      open the native read-only desktop reader (blocking; Tk)

API key: "api_key" in project.json, or else the environment variable named by "api_key_env"
(default: export FEATHERLESS_API_KEY=...).

Lorebooks: put SillyTavern World Info JSON files, or character cards (V1/V2/V3, as .png or .json) in
DIR/lorebooks/. A card becomes a character lorebook: its description + personality as one entry keyed on
the character's name, plus any embedded character_book entries. Toggle them and mark character books inside the draft loop (lb).
"""
import argparse

from .commands import (cmd_bible, cmd_check, cmd_compress, cmd_critique, cmd_draft, cmd_export,
                       cmd_init, cmd_limits, cmd_outline, cmd_revise, cmd_scenes, cmd_status,
                       cmd_update_state)
from .project import Project

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, **kw):
        sp = sub.add_parser(name, **kw)
        sp.add_argument("dir", help="project directory")
        return sp

    sp = add("init")
    sp.add_argument("--preset", help="SillyTavern master-export preset JSON to copy in as writer_preset.json")
    add("limits")
    add("bible")
    sp = add("outline")
    sp.add_argument("--n", type=int, default=3, help="number of candidates (default 3)")
    sp.add_argument("--notes", default="", help="extra direction for the planner")
    sp = add("scenes")
    sp.add_argument("--force", action="store_true")
    sp = add("draft")
    sp.add_argument("--scene")
    sp = add("update-state")
    sp.add_argument("--scene")
    sp.add_argument("--summary-only", action="store_true")
    sp = add("compress")
    sp.add_argument("--from", dest="from_id", required=True)
    sp.add_argument("--to", dest="to_id", required=True)
    sp.add_argument("--replace", action="store_true")
    sp = add("critique")
    sp.add_argument("--scene", required=True)
    sp = add("check")
    sp.add_argument("--scene")
    sp = add("revise")
    sp.add_argument("--scene", required=True)
    add("status")
    sp = add("export")
    sp.add_argument("--out")
    add("gui")
    args = ap.parse_args()

    if args.cmd == "init":
        return cmd_init(args)
    if args.cmd == "gui":
        from . import gui as reader_gui
        reader_gui.launch(args.dir)
        return
    p = Project(args.dir)
    {
        "limits": cmd_limits, "bible": cmd_bible, "outline": cmd_outline, "scenes": cmd_scenes, "draft": cmd_draft,
        "update-state": cmd_update_state, "compress": cmd_compress, "critique": cmd_critique,
        "check": cmd_check, "revise": cmd_revise, "status": cmd_status, "export": cmd_export,
    }[args.cmd](p, args)

