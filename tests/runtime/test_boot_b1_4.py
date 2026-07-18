"""B1.4: C6 director-router boot-check passes and fails closed."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness import boot
from devharness.roles.director import DirectorRole


def test_registered_under_c6():
    assert "check_director_iteration_router_present" in boot.registered_check_names()
    assert boot.REQUIRED_GATES["check_director_iteration_router_present"] == "C6"


def test_passes_for_director():
    assert boot.check_director_iteration_router_present(role=DirectorRole) is True
    assert boot.check_director_iteration_router_present() is True  # default resolves DirectorRole


def test_fails_closed_when_router_absent():
    class NoRouter:
        pass

    with pytest.raises(boot.BootError):
        boot.check_director_iteration_router_present(role=NoRouter)


def test_fails_closed_when_router_wrong_interface():
    class WrongRouter:
        @staticmethod
        def iteration_rate_stakes_router(foo, bar):
            return (0, "T0", 1)

    with pytest.raises(boot.BootError):
        boot.check_director_iteration_router_present(role=WrongRouter)
