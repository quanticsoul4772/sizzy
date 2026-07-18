"""Shared data model for specledger checks."""

from dataclasses import dataclass

# All four checks are severity "error": any violation sets ok=False / exit 1.
SEVERITY_ERROR = "error"


@dataclass(frozen=True)
class Violation:
    """A single repo-consistency violation.

    Attributes:
        check: the id of the check that produced it (e.g. "migration_contiguity").
        severity: always "error" in this version.
        detail: a human-readable description of what is wrong.
    """

    check: str
    severity: str
    detail: str

    def as_dict(self) -> dict:
        return {"check": self.check, "severity": self.severity, "detail": self.detail}
