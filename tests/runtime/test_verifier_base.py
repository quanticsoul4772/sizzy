"""B2.2: Verifier ABC + VerifierOk/VerifierFailed shape."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.verifier.base import Verifier, VerifierFailed, VerifierOk


def test_verifier_ok_shape():
    ok = VerifierOk(name="v", evidence={"k": 1})
    assert ok.name == "v" and ok.evidence == {"k": 1}
    assert VerifierOk(name="v").evidence == {}  # default empty


def test_verifier_failed_requires_non_empty_reason():
    VerifierFailed(name="v", reason="nope")  # ok
    with pytest.raises(ValueError):
        VerifierFailed(name="v", reason="")


def test_verifier_is_abstract():
    with pytest.raises(TypeError):
        Verifier()  # cannot instantiate the ABC
