"""Verifier framework (B2.2, §S3 declared verification / commitment 8).

A verifier's decision rule is *code* in ``verify()`` — there is no model-supplied
"decision" field. Result is ``VerifierOk`` or ``VerifierFailed`` (with a non-empty
reason, mirroring GateDeny). ``verify`` is async so verifiers can await the parallax
MCP client.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class VerifierOk:
    name: str
    evidence: dict = field(default_factory=dict)


@dataclass(frozen=True)
class VerifierFailed:
    name: str
    reason: str
    evidence: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.reason:
            raise ValueError("VerifierFailed requires a non-empty reason")


class Verifier(ABC):
    """A falsifier. The decision rule lives in verify() as code."""

    name: str = "verifier"

    @abstractmethod
    async def verify(self, context: dict):  # -> VerifierOk | VerifierFailed
        ...
