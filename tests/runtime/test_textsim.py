"""rev 0.4.24: the shared word-shingle primitive (extracted from the 0.4.14 re-ask backstop)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.textsim import shingle_overlap, word_shingles


def test_tokenizer_keeps_paths_and_pins_single_token():
    # the interview-measured tokenizer: /=.- stay inside tokens, underscores split
    s = word_shingles("bump packaging==24.0 in requirements/dev.txt now please", n=5)
    assert "bump packaging==24.0 in requirements/dev.txt now" in s


def test_underscores_split_tokens():
    # 'quarantine_blocked' is two tokens — 4 total words below, so zero 5-shingles
    assert word_shingles("quarantine_blocked: ['encoded_payload']", n=5) == set()


def test_short_text_has_no_shingles():
    assert word_shingles("only four words here", n=5) == set()
    assert word_shingles("", n=5) == set()
    assert word_shingles(None, n=5) == set()


def test_shingle_overlap_counts_shared():
    a = "the parallax elicit tool returned an internal validation error to the operator"
    b = "the parallax elicit tool returned an unrelated thing entirely different text here"
    # shares exactly the two 5-shingles built from the common 6-word prefix
    assert shingle_overlap(a, b, n=5) == 2
    assert shingle_overlap(a, "no overlap at all whatsoever in this text", n=5) == 0
