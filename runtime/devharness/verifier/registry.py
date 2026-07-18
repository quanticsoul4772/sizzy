"""Falsifier registry (B2.2). register_verifier is the sole writer (single-write)."""

from devharness.verifier.base import Verifier


class VerifierRegistrationError(RuntimeError):
    """Raised when registering a verifier name that is already registered."""


FALSIFIERS: dict[str, Verifier] = {}


def register_verifier(name: str, verifier: Verifier) -> None:
    if name in FALSIFIERS:
        raise VerifierRegistrationError(f"verifier {name!r} already registered")
    FALSIFIERS[name] = verifier
