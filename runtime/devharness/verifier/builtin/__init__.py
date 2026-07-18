"""Built-in verifiers. Importing this package registers all falsifiers (B2.2 + B3.2)."""

from devharness.verifier.builtin import (  # noqa: F401  (import side effect = registration)
    bugfix_regression,
    dependency_resolves,
    feature_spec_claim,
    parallax_check,
    parallax_grounded_verify,
    parallax_verify,
    refactor_behavior_preserving,
    test_suite,
)
