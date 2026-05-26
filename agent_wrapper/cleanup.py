"""Post-hoc text cleanup for model output that leaks chat-template markup.

Gemma 4 occasionally emits its internal `<|channel>` / `<channel|>`
template markers and bare `thought` / `analysis` channel labels in
the visible assistant content. The wrapper logs the raw artifact
(forensic value), but downstream consumers — Nara's narration log,
final summary, journal entries, worker fallback text — want it
stripped before it lands in the iteration_record.

The strip is conservative: it removes the template tokens themselves
and the bare channel-label words that immediately surround them, but
leaves all substantive content untouched. Tested with the actual
artifacts we've seen leak in iter-001..iter-008.
"""
from __future__ import annotations

import re


# Matches any of: `<channel|>`, `<|channel>`, `<|channel|>`, `<channel>`.
# Also captures the analysis variants the chat template uses.
_CHANNEL_TOKEN = re.compile(r"<\|?(?:channel|analysis|final|message)\|?>", re.IGNORECASE)

# Bare channel-label words that the model emits without the token wrapping.
# Only match when the word is alone on a line OR immediately before/after a
# `<|channel|>` token — never when it appears in normal prose like
# "the *thought* experiment in Schelling 1960...".
_LONE_CHANNEL_LABEL = re.compile(
    r"^\s*(?:thought|analysis|final|commentary)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def strip_channel_markup(text: str) -> str:
    """Remove Gemma's chat-template channel markers from a string.

    Preserves:
      - All substantive prose, code, JSON
      - Whitespace within paragraphs
      - The word "thought" / "analysis" when used in normal English
        (only strips lines that contain ONLY that word)

    Removes:
      - `<channel|>`, `<|channel>`, `<|channel|>`, `<channel>`
        and the analysis/final/message variants
      - Standalone "thought" / "analysis" / "final" / "commentary" lines
      - Any leading/trailing whitespace produced by the removals

    Returns text unchanged when input is None or not a string.
    """
    if not isinstance(text, str):
        return text
    if not text:
        return text
    # 1. Remove all channel-token instances.
    out = _CHANNEL_TOKEN.sub("", text)
    # 2. Remove lines that are JUST a bare channel-label word.
    out = _LONE_CHANNEL_LABEL.sub("", out)
    # 3. Collapse runs of blank lines (the removals leave behind empties).
    out = re.sub(r"\n{3,}", "\n\n", out)
    # 4. Trim leading/trailing whitespace.
    return out.strip()
