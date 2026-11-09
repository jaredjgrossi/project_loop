"""Where a chip's words sit in the runner's sentence (the request screen, UI decisions log 2026-11-08).

Claude quotes the runner's exact words for each chip; this module finds them in the request text. It never guesses:
words that aren't there give no span. Matching forgives what typing and quoting change without changing the words:
letter case, curly quotes and apostrophes, dash variants, and runs of spaces. The span's text is always the
request's own characters at those positions, never Claude's quote.

Positions count Unicode code points (Python string indices; Swift: `text.unicodeScalars`), start inclusive, end
exclusive.
"""

import re

_SAME = str.maketrans({"‘": "'", "’": "'", "ʼ": "'", "“": '"', "”": '"',
                       "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-"})


def _fold(text: str) -> tuple[str, list[int]]:
    """The text folded for matching, and for each folded character the index it came from. A run of whitespace
    becomes one space; a character whose lower case isn't one character is kept as it is, so indices stay 1:1."""
    out, where = [], []
    prev_space = False
    for i, ch in enumerate(text):
        if ch.isspace():
            if prev_space:
                continue
            out.append(" ")
            where.append(i)
            prev_space = True
            continue
        prev_space = False
        ch = ch.translate(_SAME)
        low = ch.lower()
        out.append(low if len(low) == 1 else ch)
        where.append(i)
    return "".join(out), where


def find_span(text: str | None, words: str | None, taken: set[tuple[int, int]] | None = None) -> dict | None:
    """{"text", "start", "end"} for `words` in `text`, or None when they aren't there. With several matches, the first
    one not already in `taken` (so two chips quoting the same words can land on different occurrences)."""
    if not text or not words or not words.strip():
        return None
    folded, where = _fold(text)
    needle, _ = _fold(words.strip())
    first = None
    for m in re.finditer(re.escape(needle), folded):
        start, end = where[m.start()], where[m.end() - 1] + 1
        first = first or (start, end)
        if taken is None or (start, end) not in taken:
            return {"text": text[start:end], "start": start, "end": end}
    if first is not None:  # every occurrence is taken: overlapping spans are fine
        return {"text": text[first[0]:first[1]], "start": first[0], "end": first[1]}
    return None
