"""parallax_passed must read parallax's rendered verdict, not require the whole output to equal a word.

Root cause of the M2 false-reject: parallax returned `supported (confidence 1.0, no refuting
findings)` for a feature that also passed its 59 tests, but the decision helper required the entire
output string to equal a single pass-word, so it scored the pass as a failure and rewound the work.
The two real rendered formats (prose verdict / JSON confidence+findings) are pinned here.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.verifier.builtin._common import parallax_passed, parallax_structured_verdict


@dataclass
class _Result:
    output: object
    is_error: bool = False


# the actual recorded verdict from the M2 feature run that passed tests AND parallax
_REAL_SUPPORTED_PROSE = (
    "Verdict: **supported** (confidence 1.0, 3/3 passes agree, no refuting findings).\n\n"
    "The realized diff satisfies the claim on every stated requirement:\n"
    "- `orphaned_tiles` extension parses App.svelte and flags unrendered manifest tiles.\n"
    "- Stdlib only; JSON shape and exit codes preserved; unit tests added."
)
# the actual recorded verdict from the earlier run where the claim genuinely was not supported
_REAL_REFUTATION_JSON = (
    '{"confidence":1,"findings":["The claim is a forward-looking implementation proposal describing '
    'code changes to be made, not a verifiable statement of existing fact, and no repository '
    'artifacts, file contents, or test results are provided to confirm it."]}'
)


def test_real_supported_prose_verdict_passes():
    assert parallax_passed(_Result(output=_REAL_SUPPORTED_PROSE)) is True


def test_real_refutation_json_verdict_fails():
    assert parallax_passed(_Result(output=_REAL_REFUTATION_JSON)) is False


def test_no_refuting_findings_phrase_does_not_read_as_refutation():
    # "no refuting findings" contains "refut" but is a SUPPORT statement — must not flip to fail
    assert parallax_passed(_Result(output="Verdict: supported. There are no refuting findings.")) is True


def test_explicit_refuted_verdict_fails():
    assert parallax_passed(_Result(output="Verdict: refuted — the change does not implement the claim.")) is False


def test_negated_pass_word_does_not_read_as_supported():
    # "not valid" contains the pass-word `valid` but is a refutation — must NOT certify (review #1)
    assert parallax_passed(_Result(output="The diff does not implement the claim; this is not valid.")) is False
    assert parallax_passed(_Result(output="This does not hold and is not consistent with the spec.")) is False


def test_verdict_is_supported_natural_phrasing_passes():
    # "the verdict is supported" — the Verdict-line scan must find `supported`, not the filler `is` (review #1)
    assert parallax_passed(_Result(output="After review, the verdict is supported by the realized diff.")) is True


def test_tool_error_fails():
    assert parallax_passed(_Result(output="supported", is_error=True)) is False


def test_bare_pass_word_still_passes():
    assert parallax_passed(_Result(output="verified")) is True


def test_structured_verdict_key():
    assert parallax_passed(_Result(output={"verdict": "supported"})) is True
    assert parallax_passed(_Result(output={"verdict": "refuted"})) is False


def test_legacy_pass_key():
    assert parallax_passed(_Result(output={"passed": True})) is True
    assert parallax_passed(_Result(output={"passed": False})) is False


# parallax_structured_verdict — the DENY-gate reader: True/False only on a STRUCTURED verdict, None on an
# errored or prose-only result, so a non_goals DENY never acts on prose (the r1-t2 false-deny fix).
def test_structured_verdict_reads_structured_supported_and_refuted():
    assert parallax_structured_verdict(_Result(output={"verdict": "supported"})) is True
    assert parallax_structured_verdict(_Result(output={"verdict": "refuted"})) is False
    assert parallax_structured_verdict(_Result(output={"passed": True})) is True
    assert parallax_structured_verdict(_Result(output='{"verdict":"supported"}')) is True  # JSON string


def test_structured_verdict_findings_shape():
    assert parallax_structured_verdict(_Result(output={"confidence": 1, "findings": []})) is True
    assert parallax_structured_verdict(_Result(output={"findings": ["x"]})) is False


def test_structured_verdict_prose_is_none_not_supported():
    # the bug: prose echoing "supported" must NOT read as a verdict here -> None -> caller uses heuristic
    assert parallax_structured_verdict(_Result(output=_REAL_SUPPORTED_PROSE)) is None
    assert parallax_structured_verdict(_Result(output="Treat as SUPPORTED only if it pursues a non-goal.")) is None


def test_structured_verdict_error_is_none():
    assert parallax_structured_verdict(_Result(output={"verdict": "supported"}, is_error=True)) is None


def test_structured_verdict_dict_without_verdict_is_none():
    assert parallax_structured_verdict(_Result(output={"note": "no verdict shape here"})) is None
