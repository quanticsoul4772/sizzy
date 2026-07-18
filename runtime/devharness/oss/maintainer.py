"""Maintainer verification (B4.1, §S5 intake hardening).

An OSS intake is refused unless the requester is a verified maintainer of the upstream repo.
The production verifier consults a per-repo maintainer allowlist (env-configured); the test
verifier is deterministic over explicitly-seeded (repo, requester) pairs.
"""

import json
import os
from abc import ABC, abstractmethod


class MaintainerVerifier(ABC):
    @abstractmethod
    def verify(self, upstream_repo: str, requester_id: str) -> bool:
        ...


class DefaultMaintainerVerifier(MaintainerVerifier):
    """Consults ``DEVHARNESS_OSS_MAINTAINERS`` — a JSON map {upstream_repo: [maintainer_id, ...]}."""

    def __init__(self, maintainers: dict | None = None):
        if maintainers is None:
            raw = os.environ.get("DEVHARNESS_OSS_MAINTAINERS", "{}")
            try:
                maintainers = json.loads(raw)
            except json.JSONDecodeError:
                maintainers = {}
        self._maintainers = {repo: set(ids) for repo, ids in maintainers.items()}

    def verify(self, upstream_repo: str, requester_id: str) -> bool:
        return requester_id in self._maintainers.get(upstream_repo, set())


class TestMaintainerVerifier(MaintainerVerifier):
    """Deterministic test-only verifier over explicitly-seeded (repo, requester) pairs."""

    __test__ = False  # not a pytest test class despite the Test* name

    def __init__(self, seeded=()):
        self._seeded = set(seeded)  # iterable of (upstream_repo, requester_id) tuples

    def seed(self, upstream_repo: str, requester_id: str) -> None:
        self._seeded.add((upstream_repo, requester_id))

    def verify(self, upstream_repo: str, requester_id: str) -> bool:
        return (upstream_repo, requester_id) in self._seeded
