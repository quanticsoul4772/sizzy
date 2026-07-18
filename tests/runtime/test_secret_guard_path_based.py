"""B4.2-reconciliation: secret_guard path axis — secret-named files denied; env appends; override."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))

from devharness.gates.base import GateDeny, GateOk
from devharness.gates.secret_guard import DEFAULT_SECRET_PATH_PATTERNS, SecretGuard, secret_path_patterns


def _check(paths, **extra):
    return SecretGuard().check({"touched_paths": paths, **extra})


def test_each_default_pattern_detected():
    samples = [".env", ".env.local", "secrets.yml", "server.pem", "private.key", "id_rsa",
               "id_ed25519", "keystore.p12", "cert.pfx", "app.keystore", "credentials.json",
               ".npmrc", ".pypirc", "vault.kdbx"]
    for path in samples:
        r = _check([path])
        assert isinstance(r, GateDeny), f"{path} not caught"
        assert path in r.evidence["matched_paths"] and r.evidence["axes_triggered"] == ["path"]


def test_secret_named_file_in_subdir_detected():
    r = _check(["config/.env", "keys/id_rsa"])
    assert isinstance(r, GateDeny) and len(r.evidence["matched_paths"]) == 2


def test_non_secret_paths_pass():
    assert isinstance(_check(["src/app.py", "README.md", "env.example"]), GateOk)


def test_env_var_appends_without_losing_defaults(monkeypatch):
    monkeypatch.setenv("DEVHARNESS_SECRET_PATH_PATTERNS", "*.secret, vault.json")
    patterns = secret_path_patterns()
    assert set(DEFAULT_SECRET_PATH_PATTERNS) <= set(patterns)  # defaults retained
    assert "*.secret" in patterns and "vault.json" in patterns
    assert isinstance(_check(["config.secret"]), GateDeny)
    assert isinstance(_check([".env"]), GateDeny)  # default still enforced


def test_path_override_allows():
    r = _check([".env"], secret_guard_path_override=True)
    assert isinstance(r, GateOk) and r.reason == "secret_detected_with_override"
