"""Memory entry model + project identity (B5.5, §S7)."""

import os

import msgspec

DEFAULT_PROJECT_NAME = "devharness"


def project_name() -> str:
    """This project's federated-memory identity (DEVHARNESS_PROJECT_NAME env, default 'devharness')."""
    return os.environ.get("DEVHARNESS_PROJECT_NAME") or DEFAULT_PROJECT_NAME


class MemoryEntry(msgspec.Struct, frozen=True, kw_only=True):
    """One cross-project memory entry. ``verified_locally`` state lives in proj_memory (it changes over
    time as a project verifies an imported entry), not on this struct."""
    entry_id: str  # UUID, stable across export/import
    entry_type: str  # "antibody" (future: other types)
    entry_payload: dict  # type-specific content
    source_project: str  # the project that originally created it
    created_at_millis: int
    correlation_id: str
