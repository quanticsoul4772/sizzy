"""Research memory hygiene: elicit consults parallax's GLOBAL memory store, which the caller cannot
scope, so a lesson from unrelated work (e.g. a Rust rmcp lesson matched on "router") can surface as a
divergence_point / governing_preference in a brand-new project's interview. `_strip_foreign_memory`
drops the cross-project items before the operator sees them or `_no_divergence` reads them, keying on
the verified provenance field (`strength=='revealed'` for preferences; a memory-source signal for
divergence points), and is a no-op on any non-elicit / malformed input."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.roles.research import ResearchRole

strip = ResearchRole._strip_foreign_memory
no_div = ResearchRole._no_divergence


def _payload(divs, prefs):
    return json.dumps({"assumed_objective": "Build the operator UI", "divergence_points": divs,
                       "governing_preferences": prefs, "memory_consulted": True, "signal_level": "low"})


def test_drops_memory_sourced_keeps_request_sourced():
    out = json.loads(strip(_payload(
        divs=[{"question": "real?", "signal": "the request"},
              {"question": "rust router?", "signal": "Stored verified preference: rmcp #[tool_handler]"}],
        prefs=[{"preference": "no LLM in the loop", "signal": "the request", "strength": "stated"},
               {"preference": "explicit router field", "signal": "stored preference", "strength": "revealed"}],
    )))
    assert [d["question"] for d in out["divergence_points"]] == ["real?"]
    assert [p["preference"] for p in out["governing_preferences"]] == ["no LLM in the loop"]


def test_preference_kept_on_strength_not_signal_prose():
    # finding 2: prefs are filtered ONLY on the verified `strength` field, never on freeform signal —
    # a stated preference with memory-sounding prose must survive (else we'd silently strip real prefs).
    out = json.loads(strip(_payload(
        divs=[], prefs=[{"preference": "keep me", "signal": "recalled from stored notes", "strength": "stated"}])))
    assert [p["preference"] for p in out["governing_preferences"]] == ["keep me"]


def test_missing_provenance_keys_are_kept():
    # finding 3: a divergence with no `signal` and a preference with no `strength` lack provenance —
    # the deliberate rule is keep-and-document (don't over-strip on absent provenance).
    out = json.loads(strip(_payload(
        divs=[{"question": "no signal here"}], prefs=[{"preference": "no strength here"}])))
    assert [d["question"] for d in out["divergence_points"]] == ["no signal here"]
    assert [p["preference"] for p in out["governing_preferences"]] == ["no strength here"]


def test_sole_foreign_divergence_becomes_empty_list_triggering_early_stop():
    # finding 5: stripping the only divergence leaves [], NOT a deleted key, so _no_divergence's
    # `== []` early-stop fires (interview ends a round earlier — the foreign item was noise).
    stripped = strip(_payload(divs=[{"question": "rust?", "signal": "stored preference"}], prefs=[]))
    assert json.loads(stripped)["divergence_points"] == []
    assert no_div(stripped) is True


def test_fenced_json_is_cleaned_and_still_parseable():
    fenced = "```json\n" + _payload(
        divs=[{"question": "rust?", "signal": "stored verified preference"}], prefs=[]) + "\n```"
    stripped = strip(fenced)
    assert json.loads(stripped)["divergence_points"] == []
    assert no_div(stripped) is True  # _no_divergence relocates the braces fine


def test_brace_free_plain_string_unchanged():
    # protects the existing research tests, whose elicit outputs are brace-free question strings.
    q = "What is the scope of the project?"
    assert strip(q) == q


def test_malformed_json_is_noop():
    assert strip("{ not valid json") == "{ not valid json"
    assert strip("{ broken, }") == "{ broken, }"


def test_all_request_sourced_payload_preserves_items():
    payload = _payload(
        divs=[{"question": "a?", "signal": "the request"}],
        prefs=[{"preference": "p", "signal": "the request", "strength": "stated"}])
    out = json.loads(strip(payload))
    assert len(out["divergence_points"]) == 1 and len(out["governing_preferences"]) == 1
