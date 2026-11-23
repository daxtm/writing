"""Constants, default config, templates."""

import sys
import threading

DEFAULT_MODEL = "meta-llama/Llama-3.3-70B-Instruct"

DEFAULT_CONFIG = {
    "title": "Untitled",
    "target_words": 17000,
    "api_base": "https://api.featherless.ai/v1",
    "api_key": "",
    "api_key_env": "FEATHERLESS_API_KEY",
    "max_context_fallback": 32768,
    "context_safety_margin": 0.05,
    "prompt_budget": 16000,
    "chars_per_token_default": 3.5,
    "max_parallel": 1,
    "request_timeout_s": 600,
    "roles": {
        "planner": {"model": DEFAULT_MODEL, "temperature": 0.9, "min_p": 0.05, "max_tokens": 8000,
                    "thinking": True, "thinking_budget": 4000},
        "writer": {
            "model": DEFAULT_MODEL,
            "preset": "writer_preset.json",
            "preset_overrides": {"temp": 1.06},
            "swipes": 2,
            "passage_words": 220,
            "user_name": "Author",
            "absent_character_lore": "reference",
            "lore_match_whole_words": True,
        },
        "summarizer": {"model": DEFAULT_MODEL, "temperature": 0.3, "max_tokens": 8000, "thinking": False},
        "critic": {"model": DEFAULT_MODEL, "temperature": 0.4, "max_tokens": 8000, "thinking": False},
        "editor": {"model": DEFAULT_MODEL, "temperature": 0.6, "min_p": 0.05, "max_tokens": 1600},
    },
    "budget_tokens": {
        "bible": 1800,
        "scene_card": 700,
        "summary": 5000,
        "state": 2500,
        "lore": 2500,
        "recent": 3000,
        "steer": 400,
    },
    "summary": {"detailed_recent_scenes": 3, "detailed_words": 200, "brief_words": 50, "arc_words": 350},
    "banned_phrases": [
        "shivers down",
        "a testament to",
        "barely above a whisper",
        "ministrations",
        "tapestry of",
        "the air was thick with",
        "couldn't help but",
        "maybe, just maybe",
        "sparkling with mischief",
        "a dance of",
        "breath she didn't know",
        "breath he didn't know",
        "eyes widened in",
        "sent a jolt",
    ],
    "ngram": {"n": 5, "min_count": 3, "top": 40},
}

SAMPLING_KEYS = (
    "temperature", "top_p", "top_k", "min_p", "repetition_penalty",
    "presence_penalty", "frequency_penalty", "seed", "stop", "min_tokens", "max_tokens",
)
RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}

# SillyTavern sampler fields Featherless has no documented parameter for, with their "off" test.
ST_UNSENDABLE = (
    ("typical_p", lambda v: v not in (None, 1, 1.0)),
    ("tfs", lambda v: v not in (None, 1, 1.0)),
    ("top_a", lambda v: bool(v)),
    ("epsilon_cutoff", lambda v: bool(v)),
    ("eta_cutoff", lambda v: bool(v)),
    ("mirostat_mode", lambda v: bool(v)),
    ("smoothing_factor", lambda v: bool(v)),
    ("xtc_probability", lambda v: bool(v)),
    ("nsigma", lambda v: bool(v)),
    ("dynatemp", lambda v: bool(v)),
    ("no_repeat_ngram_size", lambda v: bool(v)),
    ("penalty_alpha", lambda v: bool(v)),
    ("encoder_rep_pen", lambda v: v not in (None, 1, 1.0)),
    ("guidance_scale", lambda v: v not in (None, 1, 1.0)),
    ("skew", lambda v: bool(v)),
)

BIBLE_TEMPLATE = """# Story bible

## Title
(working title)

## Premise
(2-5 sentences: who, what they want, what stands in the way, what's at stake)

## Source & canon
(fanfic only: fandom, where in canon this sits, the canon facts you rely on, where you deliberately diverge)

## POV & tense
(e.g. close third person, past tense, single POV: NAME)

## Style rules
- (voice, sentence rhythm, dialogue habits, explicitness level, what to dramatize vs summarize)

## Avoid
- (phrases, tropes, habits you don't want)

## Characters
### NAME
- Role:
- Look:
- Voice / speech:
- Wants / fears:
- Relationships:
"""

STATE_TEMPLATE = """# Continuity state

## Characters
- NAME: location - ; condition - ; knows - ; wants - ; relationships -

## Open threads
-

## Established facts
-

## Resolved
-
"""

SUMMARIZER_SYSTEM = (
    "You maintain continuity records for a story in progress. Be factual and specific. "
    "Record only what the text actually establishes. Never invent events, motives or details."
)

CRITIC_SYSTEM = (
    "You are a demanding fiction editor. Report problems only; do not praise. "
    "Quote the exact text for every issue so it can be found."
)

EDITOR_SYSTEM = (
    "You are a line editor. You revise one passage to fix specific listed problems, changing as little as possible. "
    "Preserve voice, POV, tense, events and approximate length unless a listed problem requires otherwise."
)

PLANNER_SYSTEM = (
    "You are a story architect who designs tightly plotted fiction. Every beat you write is a concrete event, "
    "never a theme or a mood."
)

COLOR = sys.stdout.isatty()
LOCK = threading.Lock()
