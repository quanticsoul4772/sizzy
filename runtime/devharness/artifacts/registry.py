"""Handoff-artifact registry + validation (B1.1, Invariant 6 / commitment 13).

Roles communicate through harness-validated documents, never free-form chat. Every
artifact consumed by a downstream role is validated against its registered schema;
an invalid artifact is rejected, not consumed.
"""

import msgspec

from devharness.artifacts.spec import SpecArtifact


class HandoffValidationError(RuntimeError):
    """Raised when an artifact payload fails its registered schema."""


# Artifact-type name -> msgspec.Struct class. register_artifact_schema is the sole writer.
HANDOFF_ARTIFACTS: dict[str, type] = {}


def register_artifact_schema(name: str, struct_class: type) -> None:
    """Register an artifact schema. Single-write: re-registering a name is an error."""
    if name in HANDOFF_ARTIFACTS:
        raise HandoffValidationError(f"artifact schema {name!r} already registered")
    HANDOFF_ARTIFACTS[name] = struct_class


def validate_before_consumption(artifact_name: str, payload_dict: dict):
    """Return a validated typed instance, or raise HandoffValidationError naming the failure."""
    struct_class = HANDOFF_ARTIFACTS.get(artifact_name)
    if struct_class is None:
        raise HandoffValidationError(f"no schema registered for artifact {artifact_name!r}")
    try:
        return msgspec.convert(payload_dict, struct_class)
    except msgspec.ValidationError as exc:
        raise HandoffValidationError(f"{artifact_name} artifact invalid: {exc}") from exc


register_artifact_schema("spec", SpecArtifact)
