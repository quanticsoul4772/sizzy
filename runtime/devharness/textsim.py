"""Word-shingle text similarity (rev 0.4.24).

The 5-word-shingle math the rev-0.4.14 interview re-ask backstop measured and shipped as a closure
inside ``ResearchRole._answer_quote_reask`` — extracted here so the §S7 duplicate-candidate guard
(`retro/candidate_guard.py`) can reuse it without reaching into an interview-specific method. The
tokenizer keeps ``/=.-`` inside tokens, so paths/pins/versions stay single tokens; underscores split
(``quarantine_blocked`` → two tokens). A text under ``n`` tokens has no shingles.
"""

import re

_TOKEN_RE = re.compile(r"[a-z0-9/=.\-]+")


def word_shingles(text: str, n: int = 5) -> set:
    """The set of n-word space-joined shingles of ``text`` (lowercased, tokenizer above)."""
    words = _TOKEN_RE.findall((text or "").lower())
    return {" ".join(words[k:k + n]) for k in range(len(words) - n + 1)}


def shingle_overlap(a: str, b: str, n: int = 5) -> int:
    """How many n-word shingles ``a`` and ``b`` share."""
    return len(word_shingles(a, n) & word_shingles(b, n))
